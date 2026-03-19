#!/usr/bin/env python3
"""ptt_input — configurable PTT input backends for Cadence.

Provides a unified interface for detecting press/release events from
different input sources: terminal raw mode, pynput keyboard, pynput mouse.

The active backend is selected via CADENCE_PTT_BACKEND env var:
  - "auto"     — pynput if available + DISPLAY set, else terminal (default)
  - "pynput"   — pynput keyboard/mouse (requires X11)
  - "terminal" — raw terminal mode (active-terminal only)

The binding is configured via CADENCE_PTT_BINDING:
  - Keyboard: "space", "f5", "ctrl+space", any single char
  - Mouse:    "mouse4", "mouse5" (side buttons)
  - Terminal:  "space", "enter", any single char

Usage:
    backend = create_ptt_backend()
    backend.start(on_press=my_press_handler, on_release=my_release_handler)
    ...
    backend.stop()
"""
from __future__ import annotations

import os
import select
import sys
import threading
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BACKEND_ENV = os.environ.get("CADENCE_PTT_BACKEND", "auto")
BINDING_ENV = os.environ.get("CADENCE_PTT_BINDING", "space")


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class PTTInputBackend(ABC):
    """Abstract PTT input backend."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name."""
        ...

    @property
    @abstractmethod
    def binding_description(self) -> str:
        """Human-readable description of what button/key is bound."""
        ...

    @property
    def is_global(self) -> bool:
        """True if this backend captures input globally (not just active terminal)."""
        return False

    @abstractmethod
    def start(self, *, on_press: Callable[[], None], on_release: Callable[[], None]) -> None:
        """Start listening for press/release events. Calls handlers on PTT key/button."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop listening."""
        ...

    @abstractmethod
    def is_running(self) -> bool:
        ...


# ---------------------------------------------------------------------------
# Terminal backend (raw mode, active-terminal only)
# ---------------------------------------------------------------------------

class TerminalPTTInput(PTTInputBackend):
    """PTT input via raw terminal key detection. Works everywhere, terminal-only."""

    def __init__(self, binding: str = "space"):
        self._binding = binding
        self._key_char = _resolve_terminal_key(binding)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._on_press: Optional[Callable] = None
        self._on_release: Optional[Callable] = None

    @property
    def name(self) -> str:
        return "terminal"

    @property
    def binding_description(self) -> str:
        return f"hold {self._binding.upper()} (terminal)" if len(self._binding) > 1 else f"hold '{self._binding}' (terminal)"

    def start(self, *, on_press: Callable[[], None], on_release: Callable[[], None]) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        pressed = False
        try:
            tty.setraw(fd)
            while not self._stop_event.is_set():
                rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
                if rlist:
                    ch = sys.stdin.read(1)
                    if ch == "\x03":  # Ctrl+C
                        self._stop_event.set()
                        break
                    if ch == self._key_char and not pressed:
                        pressed = True
                        if self._on_press:
                            self._on_press()
                elif pressed:
                    # No key in this poll — check once more for release
                    rlist2, _, _ = select.select([sys.stdin], [], [], 0.12)
                    if rlist2:
                        ch2 = sys.stdin.read(1)
                        if ch2 == self._key_char:
                            continue  # still held
                        if ch2 == "\x03":
                            self._stop_event.set()
                            break
                    # Key released
                    pressed = False
                    if self._on_release:
                        self._on_release()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _resolve_terminal_key(binding: str) -> str:
    mapping = {"space": " ", "enter": "\r", "tab": "\t"}
    lower = binding.lower().strip()
    return mapping.get(lower, lower[0] if lower else " ")


# ---------------------------------------------------------------------------
# Pynput backend (global keyboard + mouse)
# ---------------------------------------------------------------------------

def _pynput_available() -> bool:
    """Check if pynput can be used (installed + X11 display available)."""
    if not os.environ.get("DISPLAY"):
        return False
    try:
        from pynput import keyboard  # noqa: F401
        return True
    except ImportError:
        return False


class PynputPTTInput(PTTInputBackend):
    """PTT input via pynput — global keyboard and mouse hooks."""

    def __init__(self, binding: str = "space"):
        self._binding = binding.lower().strip()
        self._is_mouse = self._binding.startswith("mouse")
        self._on_press: Optional[Callable] = None
        self._on_release: Optional[Callable] = None
        self._listener: Any = None
        self._pressed = False

    @property
    def name(self) -> str:
        return "pynput"

    @property
    def binding_description(self) -> str:
        if self._is_mouse:
            btn_names = {"mouse4": "mouse side-back", "mouse5": "mouse side-forward",
                         "mouse1": "left click", "mouse2": "middle click", "mouse3": "right click"}
            return f"hold {btn_names.get(self._binding, self._binding)} (global)"
        return f"hold {self._binding.upper()} (global)"

    @property
    def is_global(self) -> bool:
        return True

    def start(self, *, on_press: Callable[[], None], on_release: Callable[[], None]) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._pressed = False

        if self._is_mouse:
            self._start_mouse()
        else:
            self._start_keyboard()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def is_running(self) -> bool:
        return self._listener is not None and self._listener.is_alive()

    def _start_keyboard(self) -> None:
        from pynput import keyboard

        target_key = _resolve_pynput_key(self._binding)

        def on_press(key):
            if self._pressed:
                return
            if _key_matches(key, target_key):
                self._pressed = True
                if self._on_press:
                    self._on_press()

        def on_release(key):
            if not self._pressed:
                return
            if _key_matches(key, target_key):
                self._pressed = False
                if self._on_release:
                    self._on_release()

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener.start()

    def _start_mouse(self) -> None:
        from pynput import mouse

        target_button = _resolve_pynput_mouse(self._binding)

        def on_click(x, y, button, pressed):
            if button != target_button:
                return
            if pressed and not self._pressed:
                self._pressed = True
                if self._on_press:
                    self._on_press()
            elif not pressed and self._pressed:
                self._pressed = False
                if self._on_release:
                    self._on_release()

        self._listener = mouse.Listener(on_click=on_click)
        self._listener.start()


def _resolve_pynput_key(binding: str):
    """Resolve a binding string to a pynput Key or KeyCode."""
    from pynput import keyboard
    special = {
        "space": keyboard.Key.space,
        "enter": keyboard.Key.enter,
        "tab": keyboard.Key.tab,
        "f1": keyboard.Key.f1, "f2": keyboard.Key.f2, "f3": keyboard.Key.f3,
        "f4": keyboard.Key.f4, "f5": keyboard.Key.f5, "f6": keyboard.Key.f6,
        "f7": keyboard.Key.f7, "f8": keyboard.Key.f8, "f9": keyboard.Key.f9,
        "f10": keyboard.Key.f10, "f11": keyboard.Key.f11, "f12": keyboard.Key.f12,
        "pause": keyboard.Key.pause,
        "scroll_lock": keyboard.Key.scroll_lock,
    }
    lower = binding.lower().strip()
    if lower in special:
        return special[lower]
    if len(lower) == 1:
        return keyboard.KeyCode.from_char(lower)
    return keyboard.Key.space  # fallback


def _key_matches(pressed_key, target_key) -> bool:
    """Check if a pressed key matches the target key."""
    return pressed_key == target_key


def _resolve_pynput_mouse(binding: str):
    """Resolve a mouse binding string to a pynput Button."""
    from pynput import mouse
    mapping = {
        "mouse1": mouse.Button.left,
        "mouse2": mouse.Button.middle,
        "mouse3": mouse.Button.right,
    }
    lower = binding.lower().strip()
    if lower in mapping:
        return mapping[lower]
    # mouse4/mouse5 — X11 side buttons
    # pynput uses Button.x1 and Button.x2 for these on some platforms
    # but they may also be Button.button8/button9 depending on X11 config
    try:
        if lower in ("mouse4", "x1", "back"):
            return mouse.Button.x1
        if lower in ("mouse5", "x2", "forward"):
            return mouse.Button.x2
    except AttributeError:
        pass
    # Fallback: try numeric
    try:
        btn_num = int(lower.replace("mouse", ""))
        return mouse.Button(btn_num)
    except (ValueError, AttributeError):
        pass
    return mouse.Button.middle  # safe fallback


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_ptt_backend(
    *,
    backend: str = "",
    binding: str = "",
) -> PTTInputBackend:
    """Create the appropriate PTT input backend based on config.

    Args:
        backend: "auto", "pynput", or "terminal". Default from CADENCE_PTT_BACKEND.
        binding: Key/button binding. Default from CADENCE_PTT_BINDING.
    """
    backend = backend or BACKEND_ENV
    binding = binding or BINDING_ENV

    if backend == "pynput" or (backend == "auto" and _pynput_available()):
        try:
            return PynputPTTInput(binding)
        except Exception:
            pass  # fall through to terminal

    return TerminalPTTInput(binding)


def probe_backends() -> dict[str, Any]:
    """Report which backends are available and which is selected."""
    pynput_ok = _pynput_available()
    selected = BACKEND_ENV
    if selected == "auto":
        selected = "pynput" if pynput_ok else "terminal"

    return {
        "configured_backend": BACKEND_ENV,
        "configured_binding": BINDING_ENV,
        "selected_backend": selected,
        "pynput_available": pynput_ok,
        "display_set": bool(os.environ.get("DISPLAY")),
        "terminal_available": True,
    }
