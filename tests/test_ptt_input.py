#!/usr/bin/env python3
"""Tests for ptt_input — configurable PTT input backends.

Covers:
- Backend factory selection (auto, pynput, terminal)
- Terminal backend key resolution
- Pynput backend key/mouse resolution
- Chord parsing (modifier combos like ctrl+alt+shift+8)
- Probe reports
- Backend interface contract
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestProbeBackends:
    def test_probe_returns_dict(self):
        from runtime.voice.ptt_input import probe_backends
        result = probe_backends()
        assert "configured_backend" in result
        assert "configured_binding" in result
        assert "selected_backend" in result
        assert "pynput_available" in result
        assert "terminal_available" in result
        assert result["terminal_available"] is True

    def test_probe_reflects_env(self, monkeypatch):
        monkeypatch.setenv("CADENCE_PTT_BACKEND", "terminal")
        monkeypatch.setenv("CADENCE_PTT_BINDING", "f5")
        import importlib
        from runtime.voice import ptt_input
        importlib.reload(ptt_input)
        result = ptt_input.probe_backends()
        assert result["configured_backend"] == "terminal"
        assert result["configured_binding"] == "f5"
        # Restore
        monkeypatch.setenv("CADENCE_PTT_BACKEND", "auto")
        monkeypatch.setenv("CADENCE_PTT_BINDING", "space")
        importlib.reload(ptt_input)

    def test_probe_shows_active_chord(self, monkeypatch):
        monkeypatch.setenv("CADENCE_PTT_BINDING", "ctrl+alt+shift+8")
        import importlib
        from runtime.voice import ptt_input
        importlib.reload(ptt_input)
        result = ptt_input.probe_backends()
        assert result["has_modifiers"] is True
        assert "active_chord" in result
        assert "8" in result["active_chord"]
        # Restore
        monkeypatch.setenv("CADENCE_PTT_BINDING", "space")
        importlib.reload(ptt_input)


class TestTerminalBackend:
    def test_create_terminal_backend(self):
        from runtime.voice.ptt_input import TerminalPTTInput
        backend = TerminalPTTInput("space")
        assert backend.name == "terminal"
        assert "SPACE" in backend.binding_description
        assert not backend.is_global
        assert not backend.is_running()

    def test_key_resolution(self):
        from runtime.voice.ptt_input import _resolve_terminal_key
        assert _resolve_terminal_key("space") == " "
        assert _resolve_terminal_key("enter") == "\r"
        assert _resolve_terminal_key("tab") == "\t"
        assert _resolve_terminal_key("x") == "x"
        assert _resolve_terminal_key("SPACE") == " "


class TestChordParsing:
    """Test _parse_chord modifier+key decomposition."""

    def test_full_chord(self):
        from runtime.voice.ptt_input import _parse_chord
        mods, base = _parse_chord("ctrl+alt+shift+8")
        assert mods == frozenset({"ctrl", "alt", "shift"})
        assert base == "8"

    def test_two_modifier_chord(self):
        from runtime.voice.ptt_input import _parse_chord
        mods, base = _parse_chord("ctrl+shift+f5")
        assert mods == frozenset({"ctrl", "shift"})
        assert base == "f5"

    def test_single_key_no_modifiers(self):
        from runtime.voice.ptt_input import _parse_chord
        mods, base = _parse_chord("space")
        assert mods == frozenset()
        assert base == "space"

    def test_single_char_no_modifiers(self):
        from runtime.voice.ptt_input import _parse_chord
        mods, base = _parse_chord("x")
        assert mods == frozenset()
        assert base == "x"

    def test_mouse_binding_no_modifiers(self):
        from runtime.voice.ptt_input import _parse_chord
        mods, base = _parse_chord("mouse4")
        assert mods == frozenset()
        assert base == "mouse4"

    def test_case_insensitive(self):
        from runtime.voice.ptt_input import _parse_chord
        mods, base = _parse_chord("Ctrl+Alt+Shift+8")
        assert mods == frozenset({"ctrl", "alt", "shift"})
        assert base == "8"

    def test_cmd_modifier(self):
        from runtime.voice.ptt_input import _parse_chord
        mods, base = _parse_chord("cmd+space")
        assert mods == frozenset({"cmd"})
        assert base == "space"


class TestPynputBackend:
    def test_create_pynput_keyboard(self):
        from runtime.voice.ptt_input import PynputPTTInput, _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        backend = PynputPTTInput("space")
        assert backend.name == "pynput"
        assert backend.is_global
        assert "SPACE" in backend.binding_description

    def test_create_pynput_mouse(self):
        from runtime.voice.ptt_input import PynputPTTInput, _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        backend = PynputPTTInput("mouse5")
        assert backend.name == "pynput"
        assert backend.is_global
        assert "forward" in backend.binding_description.lower() or "mouse" in backend.binding_description.lower()

    def test_pynput_key_resolution(self):
        from runtime.voice.ptt_input import _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        from runtime.voice.ptt_input import _resolve_pynput_key
        from pynput import keyboard
        assert _resolve_pynput_key("space") == keyboard.Key.space
        assert _resolve_pynput_key("f5") == keyboard.Key.f5
        assert _resolve_pynput_key("enter") == keyboard.Key.enter

    def test_pynput_mouse_resolution(self):
        from runtime.voice.ptt_input import _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        from runtime.voice.ptt_input import _resolve_pynput_mouse
        from pynput import mouse
        assert _resolve_pynput_mouse("mouse1") == mouse.Button.left
        assert _resolve_pynput_mouse("mouse3") == mouse.Button.right

    def test_chord_binding_description(self):
        from runtime.voice.ptt_input import PynputPTTInput, _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        backend = PynputPTTInput("ctrl+alt+shift+8")
        desc = backend.binding_description
        assert "CTRL" in desc or "ALT" in desc or "SHIFT" in desc
        assert "8" in desc
        assert "(global)" in desc

    def test_chord_display(self):
        from runtime.voice.ptt_input import PynputPTTInput, _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        backend = PynputPTTInput("ctrl+alt+shift+8")
        display = backend.chord_display
        assert "Alt" in display
        assert "Ctrl" in display
        assert "Shift" in display
        assert "8" in display

    def test_chord_has_modifiers(self):
        from runtime.voice.ptt_input import PynputPTTInput, _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        backend = PynputPTTInput("ctrl+alt+shift+8")
        assert backend._modifiers == frozenset({"ctrl", "alt", "shift"})
        assert backend._base_key == "8"

    def test_simple_binding_no_modifiers(self):
        from runtime.voice.ptt_input import PynputPTTInput, _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        backend = PynputPTTInput("space")
        assert backend._modifiers == frozenset()
        assert backend._base_key == "space"


class TestShiftedKeyMatching:
    """Verify _key_matches handles shifted characters for chord bindings.

    When Shift is held as part of a chord (e.g. Ctrl+Alt+Shift+8), the OS
    reports the shifted character ('*') not the base character ('8').
    _key_matches must recognize these as equivalent.
    """

    def test_shift_8_produces_asterisk(self):
        from runtime.voice.ptt_input import _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        from pynput import keyboard
        from runtime.voice.ptt_input import _key_matches, _resolve_pynput_key

        target = _resolve_pynput_key("8")
        shifted = keyboard.KeyCode.from_char("*")
        assert _key_matches(shifted, target), "Shift+8='*' must match target '8'"

    def test_direct_match_still_works(self):
        from runtime.voice.ptt_input import _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        from pynput import keyboard
        from runtime.voice.ptt_input import _key_matches, _resolve_pynput_key

        target = _resolve_pynput_key("8")
        direct = keyboard.KeyCode.from_char("8")
        assert _key_matches(direct, target)

    def test_unrelated_key_no_match(self):
        from runtime.voice.ptt_input import _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        from pynput import keyboard
        from runtime.voice.ptt_input import _key_matches, _resolve_pynput_key

        target = _resolve_pynput_key("8")
        unrelated = keyboard.KeyCode.from_char("a")
        assert not _key_matches(unrelated, target)

    def test_all_digit_shift_pairs(self):
        """All US-keyboard digit→shifted pairs should match."""
        from runtime.voice.ptt_input import _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        from pynput import keyboard
        from runtime.voice.ptt_input import _key_matches, _resolve_pynput_key, _SHIFT_CHAR_MAP

        for base_char, shifted_char in _SHIFT_CHAR_MAP.items():
            if not base_char.isdigit():
                continue
            target = _resolve_pynput_key(base_char)
            pressed = keyboard.KeyCode.from_char(shifted_char)
            assert _key_matches(pressed, target), (
                f"Shift+{base_char}='{shifted_char}' must match target '{base_char}'"
            )

    def test_special_key_unaffected(self):
        """Special keys (F5, space) should still match normally."""
        from runtime.voice.ptt_input import _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        from pynput import keyboard
        from runtime.voice.ptt_input import _key_matches, _resolve_pynput_key

        target = _resolve_pynput_key("space")
        assert _key_matches(keyboard.Key.space, target)
        assert not _key_matches(keyboard.Key.enter, target)


class TestFactory:
    def test_create_auto_backend(self):
        from runtime.voice.ptt_input import create_ptt_backend
        backend = create_ptt_backend()
        assert backend.name in ("terminal", "pynput", "win_hotkey")
        assert backend.binding_description  # non-empty

    def test_create_terminal_explicit(self):
        from runtime.voice.ptt_input import create_ptt_backend
        backend = create_ptt_backend(backend="terminal", binding="enter")
        assert backend.name == "terminal"
        assert "ENTER" in backend.binding_description

    def test_create_pynput_explicit(self):
        from runtime.voice.ptt_input import create_ptt_backend, _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        backend = create_ptt_backend(backend="pynput", binding="f5")
        assert backend.name == "pynput"
        assert backend.is_global

    def test_create_pynput_mouse_binding(self):
        from runtime.voice.ptt_input import create_ptt_backend, _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        backend = create_ptt_backend(backend="pynput", binding="mouse5")
        assert backend.name == "pynput"
        assert backend.is_global

    def test_fallback_to_terminal_when_no_global_available(self):
        """When pynput and win_hotkey fail, factory falls back to terminal."""
        from runtime.voice.ptt_input import create_ptt_backend
        with patch("runtime.voice.ptt_input._pynput_available", return_value=False), \
             patch("runtime.voice.ptt_input._is_wsl2", return_value=False):
            backend = create_ptt_backend(backend="auto")
        assert backend.name == "terminal"


class TestWinHotkeyBackend:
    """Tests for WinHotkeyPTTInput backend."""

    def test_win_hotkey_creates(self):
        from runtime.voice.ptt_input import WinHotkeyPTTInput
        backend = WinHotkeyPTTInput("ctrl+alt+shift+8")
        assert backend.name == "win_hotkey"
        assert backend.is_global
        assert "CTRL" in backend.binding_description or "ALT" in backend.binding_description
        assert "8" in backend.binding_description

    def test_win_hotkey_chord_display(self):
        from runtime.voice.ptt_input import WinHotkeyPTTInput
        backend = WinHotkeyPTTInput("ctrl+alt+shift+8")
        display = backend.chord_display
        assert "Alt" in display
        assert "Ctrl" in display
        assert "Shift" in display
        assert "8" in display

    def test_win_hotkey_simple_binding(self):
        from runtime.voice.ptt_input import WinHotkeyPTTInput
        backend = WinHotkeyPTTInput("f5")
        assert backend._modifiers == frozenset()
        assert backend._base_key == "f5"
        assert "F5" in backend.binding_description

    def test_not_running_before_start(self):
        from runtime.voice.ptt_input import WinHotkeyPTTInput
        backend = WinHotkeyPTTInput("ctrl+alt+shift+8")
        assert not backend.is_running()


class TestWSL2Detection:
    """Tests for WSL2 auto-detection in factory."""

    def test_wsl2_prefers_win_hotkey(self):
        """On WSL2 with win_hotkey available, factory should select it."""
        from runtime.voice.ptt_input import create_ptt_backend
        with patch("runtime.voice.ptt_input._is_wsl2", return_value=True), \
             patch("runtime.voice.ptt_input._win_hotkey_available", return_value=True), \
             patch("runtime.voice.ptt_input.WinHotkeyPTTInput") as MockWin:
            mock_instance = MagicMock()
            mock_instance.name = "win_hotkey"
            MockWin.return_value = mock_instance
            backend = create_ptt_backend(backend="auto")
        assert backend.name == "win_hotkey"

    def test_non_wsl2_uses_pynput(self):
        """On non-WSL2 with pynput, factory should use pynput."""
        from runtime.voice.ptt_input import create_ptt_backend, _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        with patch("runtime.voice.ptt_input._is_wsl2", return_value=False):
            backend = create_ptt_backend(backend="auto")
        assert backend.name == "pynput"

    def test_probe_reports_win_hotkey(self):
        """probe_backends should report win_hotkey availability."""
        import importlib
        from runtime.voice import ptt_input
        with patch.object(ptt_input, "_is_wsl2", return_value=True), \
             patch.object(ptt_input, "_win_hotkey_available", return_value=True):
            result = ptt_input.probe_backends()
        assert result.get("is_wsl2") is True
        assert result.get("win_hotkey_available") is True
        assert result["selected_backend"] == "win_hotkey"


class TestBackendContract:
    """Verify all backends expose the same interface."""

    _REQUIRED_ATTRS = ["name", "binding_description", "is_global", "start", "stop", "is_running"]

    def test_terminal_contract(self):
        from runtime.voice.ptt_input import TerminalPTTInput
        backend = TerminalPTTInput("space")
        for attr in self._REQUIRED_ATTRS:
            assert hasattr(backend, attr)

    def test_pynput_contract(self):
        from runtime.voice.ptt_input import _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        from runtime.voice.ptt_input import PynputPTTInput
        backend = PynputPTTInput("space")
        for attr in self._REQUIRED_ATTRS:
            assert hasattr(backend, attr)

    def test_win_hotkey_contract(self):
        from runtime.voice.ptt_input import WinHotkeyPTTInput
        backend = WinHotkeyPTTInput("ctrl+alt+shift+8")
        for attr in self._REQUIRED_ATTRS:
            assert hasattr(backend, attr)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
