#!/usr/bin/env python3
"""ptt_input — configurable PTT input backends for Cadence.

Provides a unified interface for detecting press/release events from
different input sources: terminal raw mode, pynput keyboard, pynput mouse.

The active backend is selected via CADENCE_PTT_BACKEND env var:
  - "auto"     — pynput if available + DISPLAY set, else terminal (default)
  - "pynput"   — pynput keyboard/mouse (requires X11)
  - "terminal" — raw terminal mode (active-terminal only)

The binding is configured via CADENCE_PTT_BINDING:
  - Chord:    "ctrl+alt+shift+8" (modifier combos, primary Cadence trigger)
  - Keyboard: "space", "f5", any single char
  - Mouse:    "mouse4", "mouse5" (side buttons)
  - Terminal:  "space", "enter", any single char (chords not supported)

Usage:
    backend = create_ptt_backend()
    backend.start(on_press=my_press_handler, on_release=my_release_handler)
    ...
    backend.stop()
"""
from __future__ import annotations

import logging
import os
import select
import subprocess
import sys
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BACKEND_ENV = os.environ.get("CADENCE_PTT_BACKEND", "auto")
BINDING_ENV = os.environ.get("CADENCE_PTT_BINDING", "ctrl+alt+shift+8")

# Known modifier names (normalized to lowercase).
_MODIFIER_NAMES = frozenset({"ctrl", "alt", "shift", "cmd", "meta", "super"})


def _parse_chord(binding: str) -> tuple[frozenset[str], str]:
    """Parse a binding string into (modifier_set, base_key).

    Examples:
        "ctrl+alt+shift+8"  -> ({"ctrl","alt","shift"}, "8")
        "space"             -> (set(), "space")
        "f5"                -> (set(), "f5")
        "mouse4"            -> (set(), "mouse4")
    """
    parts = [p.strip().lower() for p in binding.split("+")]
    modifiers: set[str] = set()
    base = parts[-1]  # last segment is always the base key
    for p in parts[:-1]:
        if p in _MODIFIER_NAMES:
            modifiers.add(p)
        else:
            # Unknown modifier — treat whole string as base key (legacy)
            return frozenset(), binding.lower().strip()
    return frozenset(modifiers), base


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
    """PTT input via pynput — global keyboard and mouse hooks.

    Supports modifier chords (e.g. ctrl+alt+shift+8).  Modifier state is
    tracked internally so that the press callback only fires when *all*
    required modifiers are held and the base key is pressed.  The release
    callback fires when *any* part of the chord is released.
    """

    def __init__(self, binding: str = "ctrl+alt+shift+8"):
        self._binding_raw = binding
        self._binding = binding.lower().strip()
        self._is_mouse = self._binding.startswith("mouse")
        self._modifiers, self._base_key = _parse_chord(self._binding)
        self._on_press: Optional[Callable] = None
        self._on_release: Optional[Callable] = None
        self._listener: Any = None
        self._pressed = False
        # Live modifier tracking (set of currently-held modifier names).
        self._held_modifiers: set[str] = set()

    @property
    def name(self) -> str:
        return "pynput"

    @property
    def binding_description(self) -> str:
        if self._is_mouse:
            btn_names = {"mouse4": "mouse side-back", "mouse5": "mouse side-forward",
                         "mouse1": "left click", "mouse2": "middle click", "mouse3": "right click"}
            return f"hold {btn_names.get(self._binding, self._binding)} (global)"
        if self._modifiers:
            mod_str = "+".join(sorted(self._modifiers)).upper()
            return f"hold {mod_str}+{self._base_key.upper()} (global)"
        return f"hold {self._binding.upper()} (global)"

    @property
    def chord_display(self) -> str:
        """Short display string for the active chord (e.g. 'Ctrl+Alt+Shift+8')."""
        if self._modifiers:
            parts = [m.capitalize() for m in sorted(self._modifiers)]
            parts.append(self._base_key.upper() if len(self._base_key) > 1 else self._base_key)
            return "+".join(parts)
        return self._binding.upper()

    @property
    def is_global(self) -> bool:
        return True

    def start(self, *, on_press: Callable[[], None], on_release: Callable[[], None]) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._pressed = False
        self._held_modifiers.clear()

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

        target_key = _resolve_pynput_key(self._base_key)
        required_mods = self._modifiers

        # Map modifier names to pynput Key objects for tracking.
        _mod_keys = _modifier_key_map()

        def _mod_name_for(key) -> Optional[str]:
            """Return the modifier name if *key* is a known modifier, else None."""
            for name, keys in _mod_keys.items():
                if key in keys:
                    return name
            return None

        def on_press(key):
            # Track modifier state
            mod = _mod_name_for(key)
            if mod:
                self._held_modifiers.add(mod)

            if self._pressed:
                return

            # Check base key
            if not _key_matches(key, target_key):
                return

            # Check all required modifiers are held
            if not required_mods.issubset(self._held_modifiers):
                return

            self._pressed = True
            if self._on_press:
                self._on_press()

        def on_release(key):
            # Track modifier state
            mod = _mod_name_for(key)
            if mod:
                self._held_modifiers.discard(mod)

            if not self._pressed:
                return

            # Release when base key is released OR any required modifier is released
            is_base = _key_matches(key, target_key)
            is_required_mod = mod in required_mods if mod else False

            if is_base or is_required_mod:
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


# US-keyboard shift map: unshifted → shifted character.
# When Shift is held as a chord modifier, the OS reports the shifted char
# (e.g. Shift+8 → '*'), but our target is the unshifted char '8'.
_SHIFT_CHAR_MAP: dict[str, str] = {
    "1": "!", "2": "@", "3": "#", "4": "$", "5": "%",
    "6": "^", "7": "&", "8": "*", "9": "(", "0": ")",
    "-": "_", "=": "+", "[": "{", "]": "}", "\\": "|",
    ";": ":", "'": '"', ",": "<", ".": ">", "/": "?", "`": "~",
}


def _key_matches(pressed_key, target_key) -> bool:
    """Check if a pressed key matches the target key.

    Handles the Shift-modifier case: when Shift is held as part of a chord,
    the OS may report the shifted character (e.g. '*' instead of '8').
    We check both direct equality and shifted-character equivalence.
    """
    if pressed_key == target_key:
        return True
    # Compare virtual keycodes if available (platform-dependent)
    try:
        pvk = getattr(pressed_key, "vk", None)
        tvk = getattr(target_key, "vk", None)
        if pvk is not None and tvk is not None and pvk == tvk:
            return True
    except Exception:
        pass
    # Check shifted character equivalence
    try:
        pressed_char = getattr(pressed_key, "char", None)
        target_char = getattr(target_key, "char", None)
        if pressed_char and target_char:
            if _SHIFT_CHAR_MAP.get(target_char) == pressed_char:
                return True
    except Exception:
        pass
    return False


def _modifier_key_map() -> dict[str, set]:
    """Return {modifier_name: set_of_pynput_Key} for modifier tracking."""
    from pynput import keyboard
    return {
        "ctrl":  {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
        "alt":   {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r,
                  keyboard.Key.alt_gr},
        "shift": {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r},
        "cmd":   {keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r},
        "meta":  {keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r},
        "super": {keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r},
    }


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
# Windows hotkey relay backend (WSL2 — spawns Windows-side keyboard hook)
# ---------------------------------------------------------------------------

def _is_wsl2() -> bool:
    """Detect if running under WSL2."""
    try:
        text = Path("/proc/version").read_text()
        return "microsoft" in text.lower() or "wsl" in text.lower()
    except Exception:
        return False


def _find_win_python() -> Optional[str]:
    """Find a Windows Python that can run the hotkey script."""
    import glob as globmod
    patterns = [
        "/mnt/c/Users/*/AppData/Local/Programs/Python/Python3*/python.exe",
        "/mnt/c/Python3*/python.exe",
    ]
    for pat in patterns:
        matches = sorted(globmod.glob(pat))
        if matches:
            return matches[-1]
    # Try PATH
    try:
        result = subprocess.run(
            ["which", "python.exe"], capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _win_hotkey_available() -> bool:
    """Check if the Windows hotkey relay can be used."""
    if not _is_wsl2():
        return False
    wp = _find_win_python()
    if not wp:
        return False
    # Verify ctypes works (it always does on CPython for Windows, but check)
    script = Path(__file__).resolve().parents[2] / "scripts" / "cadence_win_hotkey.py"
    return script.exists()


class WinHotkeyPTTInput(PTTInputBackend):
    """PTT input via a Windows-side low-level keyboard hook.

    On WSL2, pynput cannot see physical keyboard events because WSLg does
    not forward them through XRecord.  This backend spawns a small Python
    script on the *Windows* Python interpreter that uses ctypes
    SetWindowsHookExW to capture global key events, and communicates
    press/release over a stdout pipe back to WSL.

    No extra pip packages are needed on the Windows side.
    """

    def __init__(self, binding: str = "ctrl+alt+shift+8", *, debug: bool = False):
        self._binding_raw = binding
        self._binding = binding.lower().strip()
        self._debug = debug or os.environ.get("CADENCE_PTT_DEBUG", "") == "1"
        self._modifiers, self._base_key = _parse_chord(self._binding)
        self._on_press: Optional[Callable] = None
        self._on_release: Optional[Callable] = None
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

    @property
    def name(self) -> str:
        return "win_hotkey"

    @property
    def binding_description(self) -> str:
        if self._modifiers:
            mod_str = "+".join(sorted(self._modifiers)).upper()
            return f"hold {mod_str}+{self._base_key.upper()} (global/Windows hook)"
        return f"hold {self._binding.upper()} (global/Windows hook)"

    @property
    def chord_display(self) -> str:
        if self._modifiers:
            parts = [m.capitalize() for m in sorted(self._modifiers)]
            parts.append(self._base_key.upper() if len(self._base_key) > 1 else self._base_key)
            return "+".join(parts)
        return self._binding.upper()

    @property
    def is_global(self) -> bool:
        return True

    def start(self, *, on_press: Callable[[], None], on_release: Callable[[], None]) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._ready.clear()

        win_python = _find_win_python()
        if not win_python:
            raise RuntimeError("No Windows Python found for hotkey relay")

        script = Path(__file__).resolve().parents[2] / "scripts" / "cadence_win_hotkey.py"
        if not script.exists():
            raise RuntimeError(f"Hotkey script not found: {script}")

        cmd = [win_python, "-u", str(script)]
        if self._debug:
            cmd.append("--debug")
        cmd.append(self._binding)

        _log.debug("Spawning win_hotkey: %s", " ".join(cmd))

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,  # line-buffered
        )

        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

        # Wait for "ready" signal (up to 5 seconds)
        if not self._ready.wait(timeout=5.0):
            _log.warning("win_hotkey: did not receive 'ready' within 5s")

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=3)
            except Exception:
                pass
            self._proc = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _read_loop(self) -> None:
        """Read events from the Windows hotkey script stdout."""
        if self._proc is None or self._proc.stdout is None:
            return
        try:
            for line in self._proc.stdout:
                line = line.strip()
                if not line:
                    continue

                if line.startswith("ready"):
                    _log.debug("win_hotkey ready: %s", line)
                    self._ready.set()
                elif line == "press":
                    _log.debug("win_hotkey: PRESS")
                    if self._on_press:
                        self._on_press()
                elif line == "release":
                    _log.debug("win_hotkey: RELEASE")
                    if self._on_release:
                        self._on_release()
                elif line.startswith("debug:"):
                    _log.debug("win_hotkey: %s", line)
                elif line.startswith("error:"):
                    _log.error("win_hotkey: %s", line)
                else:
                    _log.debug("win_hotkey unknown: %s", line)
        except Exception as exc:
            _log.debug("win_hotkey read loop ended: %s", exc)


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
        backend: "auto", "pynput", "win_hotkey", or "terminal".
                 Default from CADENCE_PTT_BACKEND.
        binding: Key/button binding. Default from CADENCE_PTT_BINDING.

    On WSL2 with "auto", prefers win_hotkey (Windows-side keyboard hook)
    over pynput, because pynput cannot receive physical keyboard events
    through WSLg's X server.
    """
    backend = backend or BACKEND_ENV
    binding = binding or BINDING_ENV

    if backend == "win_hotkey":
        try:
            return WinHotkeyPTTInput(binding)
        except Exception:
            _log.warning("win_hotkey backend requested but failed, falling back")

    if backend == "auto":
        # On WSL2, prefer win_hotkey over pynput (pynput can't see keyboard events)
        if _is_wsl2() and _win_hotkey_available():
            try:
                return WinHotkeyPTTInput(binding)
            except Exception:
                _log.debug("win_hotkey auto-detect failed, trying pynput")

        if _pynput_available():
            try:
                return PynputPTTInput(binding)
            except Exception:
                pass

    elif backend == "pynput":
        try:
            return PynputPTTInput(binding)
        except Exception:
            pass

    return TerminalPTTInput(binding)


def probe_backends() -> dict[str, Any]:
    """Report which backends are available and which is selected."""
    pynput_ok = _pynput_available()
    wsl2 = _is_wsl2()
    win_hotkey_ok = _win_hotkey_available() if wsl2 else False

    selected = BACKEND_ENV
    if selected == "auto":
        if wsl2 and win_hotkey_ok:
            selected = "win_hotkey"
        elif pynput_ok:
            selected = "pynput"
        else:
            selected = "terminal"

    modifiers, base_key = _parse_chord(BINDING_ENV)
    chord_display = BINDING_ENV
    if modifiers:
        parts = [m.capitalize() for m in sorted(modifiers)]
        parts.append(base_key.upper() if len(base_key) > 1 else base_key)
        chord_display = "+".join(parts)

    return {
        "configured_backend": BACKEND_ENV,
        "configured_binding": BINDING_ENV,
        "active_chord": chord_display,
        "has_modifiers": bool(modifiers),
        "selected_backend": selected,
        "pynput_available": pynput_ok,
        "win_hotkey_available": win_hotkey_ok,
        "is_wsl2": wsl2,
        "display_set": bool(os.environ.get("DISPLAY")),
        "terminal_available": True,
    }
