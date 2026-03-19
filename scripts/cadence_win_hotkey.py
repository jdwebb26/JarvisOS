#!/usr/bin/env python3
"""cadence_win_hotkey — Windows-side global keyboard hook for Cadence PTT.

Runs on the WINDOWS Python (not WSL). Uses ctypes to install a low-level
keyboard hook (SetWindowsHookExW) that detects chord press/release events.

Communication: writes line-delimited events to stdout:
    ready               — hook installed, listening
    press               — chord fully held (all modifiers + base key down)
    release             — chord broken (any part released)
    debug:KEY:down/up   — per-key events (when --debug flag is set)

Designed to be spawned from WSL by WinHotkeyPTTInput and read via pipe.

Usage (from Windows or WSL):
    python.exe -u scripts/cadence_win_hotkey.py ctrl+alt+shift+8
    python.exe -u scripts/cadence_win_hotkey.py --debug ctrl+alt+shift+8
    python.exe -u scripts/cadence_win_hotkey.py --probe
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import sys
import threading

# Force unbuffered stdout for pipe communication
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(write_through=True)
elif not os.environ.get("PYTHONUNBUFFERED"):
    sys.stdout = os.fdopen(sys.stdout.fileno(), "w", buffering=1)

# ---------------------------------------------------------------------------
# Windows constants
# ---------------------------------------------------------------------------

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

# Virtual key codes
VK_MAP: dict[str, int] = {
    "ctrl": 0x11, "lctrl": 0xA2, "rctrl": 0xA3,
    "shift": 0x10, "lshift": 0xA0, "rshift": 0xA1,
    "alt": 0x12, "lalt": 0xA4, "ralt": 0xA5,
    "space": 0x20, "enter": 0x0D, "tab": 0x09,
    "pause": 0x13, "scroll_lock": 0x91,
}
# F1–F12
for _i in range(1, 13):
    VK_MAP[f"f{_i}"] = 0x6F + _i
# 0–9 (top row)
for _i in range(10):
    VK_MAP[str(_i)] = 0x30 + _i
# A–Z
for _i in range(26):
    VK_MAP[chr(ord("a") + _i)] = 0x41 + _i

# Modifier VK groups: any of these counts as "that modifier held"
_MOD_GROUPS: dict[str, set[int]] = {
    "ctrl":  {0x11, 0xA2, 0xA3},
    "shift": {0x10, 0xA0, 0xA1},
    "alt":   {0x12, 0xA4, 0xA5},
}

_MODIFIER_NAMES = frozenset({"ctrl", "alt", "shift", "cmd", "meta", "super"})


# ---------------------------------------------------------------------------
# KBDLLHOOKSTRUCT
# ---------------------------------------------------------------------------

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.wintypes.ULONG)),
    ]


# Callback type: LRESULT CALLBACK LowLevelKeyboardProc(int nCode, WPARAM wParam, LPARAM lParam)
HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


# ---------------------------------------------------------------------------
# Chord parsing
# ---------------------------------------------------------------------------

def parse_chord(binding: str) -> tuple[frozenset[str], str]:
    """Parse 'ctrl+alt+shift+8' into (frozenset({'ctrl','alt','shift'}), '8')."""
    parts = [p.strip().lower() for p in binding.split("+")]
    modifiers: set[str] = set()
    base = parts[-1]
    for p in parts[:-1]:
        if p in _MODIFIER_NAMES:
            modifiers.add(p)
        else:
            return frozenset(), binding.lower().strip()
    return frozenset(modifiers), base


def resolve_vk(key_name: str) -> int:
    """Resolve a key name to a Windows virtual key code."""
    lower = key_name.lower().strip()
    if lower in VK_MAP:
        return VK_MAP[lower]
    # Single character
    if len(lower) == 1:
        return ord(lower.upper())
    raise ValueError(f"Unknown key: {key_name!r}")


def vk_name(vk: int) -> str:
    """Best-effort human name for a VK code."""
    for name, code in VK_MAP.items():
        if code == vk:
            return name
    return f"0x{vk:02X}"


# ---------------------------------------------------------------------------
# Main hook
# ---------------------------------------------------------------------------

def run_hook(binding: str, *, debug: bool = False) -> None:
    """Install keyboard hook and write events to stdout."""
    required_mods, base_key = parse_chord(binding)
    base_vk = resolve_vk(base_key)

    # Build set of VK codes that represent each required modifier
    mod_vk_groups: dict[str, set[int]] = {}
    for mod in required_mods:
        if mod in _MOD_GROUPS:
            mod_vk_groups[mod] = _MOD_GROUPS[mod]
        else:
            # cmd/meta/super — map to Win key (not common on this platform)
            mod_vk_groups[mod] = {0x5B, 0x5C}

    held_vks: set[int] = set()
    pressed = False

    def _emit(msg: str) -> None:
        try:
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()
        except Exception:
            pass

    def _mods_held() -> bool:
        """Check if all required modifiers are currently held."""
        for mod, vks in mod_vk_groups.items():
            if not (held_vks & vks):
                return False
        return True

    def hook_callback(nCode: int, wParam: int, lParam: int) -> int:
        nonlocal pressed
        if nCode >= 0:
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = kb.vkCode

            is_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            is_up = wParam in (WM_KEYUP, WM_SYSKEYUP)

            if debug:
                direction = "down" if is_down else "up" if is_up else "?"
                _emit(f"debug:{vk_name(vk)}({vk:#04x}):{direction}")

            if is_down:
                held_vks.add(vk)
                if vk == base_vk and _mods_held() and not pressed:
                    pressed = True
                    _emit("press")

            elif is_up:
                held_vks.discard(vk)
                if pressed:
                    # Release when base key or any required modifier is released
                    is_base = (vk == base_vk)
                    is_req_mod = any(vk in vks for vks in mod_vk_groups.values())
                    if is_base or is_req_mod:
                        pressed = False
                        _emit("release")

        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    # Install the hook
    callback = HOOKPROC(hook_callback)
    user32 = ctypes.windll.user32

    # Set proper function signatures
    user32.SetWindowsHookExW.restype = ctypes.wintypes.HHOOK
    user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int, ctypes.c_void_p,
        ctypes.wintypes.HINSTANCE, ctypes.wintypes.DWORD,
    ]

    # hMod=None is correct for WH_KEYBOARD_LL with an in-process callback
    hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, callback, None, 0)

    if not hook:
        err = ctypes.GetLastError()
        _emit(f"error:SetWindowsHookExW failed (err={err})")
        sys.exit(1)

    mod_display = "+".join(sorted(required_mods)).upper()
    _emit(f"ready:{mod_display}+{base_key.upper()}")

    # Message loop (required for hook to receive events)
    msg = ctypes.wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    except KeyboardInterrupt:
        pass
    finally:
        user32.UnhookWindowsHookEx(hook)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    args = sys.argv[1:]
    debug = "--debug" in args
    if debug:
        args.remove("--debug")

    if "--probe" in args:
        print("win_hotkey:ok")
        return 0

    binding = args[0] if args else "ctrl+alt+shift+8"

    try:
        required_mods, base_key = parse_chord(binding)
        resolve_vk(base_key)
    except ValueError as e:
        print(f"error:bad binding: {e}", file=sys.stderr)
        return 1

    run_hook(binding, debug=debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
