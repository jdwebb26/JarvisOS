#!/usr/bin/env python3
"""Tests for ptt_input — configurable PTT input backends.

Covers:
- Backend factory selection (auto, pynput, terminal)
- Terminal backend key resolution
- Pynput backend key/mouse resolution
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


class TestFactory:
    def test_create_auto_backend(self):
        from runtime.voice.ptt_input import create_ptt_backend
        backend = create_ptt_backend()
        assert backend.name in ("terminal", "pynput")
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

    def test_fallback_to_terminal_when_pynput_unavailable(self):
        """When pynput fails, factory falls back to terminal."""
        from runtime.voice.ptt_input import create_ptt_backend
        with patch("runtime.voice.ptt_input._pynput_available", return_value=False):
            backend = create_ptt_backend(backend="auto")
        assert backend.name == "terminal"


class TestBackendContract:
    """Verify both backends expose the same interface."""

    def test_terminal_contract(self):
        from runtime.voice.ptt_input import TerminalPTTInput
        backend = TerminalPTTInput("space")
        assert hasattr(backend, "name")
        assert hasattr(backend, "binding_description")
        assert hasattr(backend, "is_global")
        assert hasattr(backend, "start")
        assert hasattr(backend, "stop")
        assert hasattr(backend, "is_running")

    def test_pynput_contract(self):
        from runtime.voice.ptt_input import _pynput_available
        if not _pynput_available():
            pytest.skip("pynput not available")
        from runtime.voice.ptt_input import PynputPTTInput
        backend = PynputPTTInput("space")
        assert hasattr(backend, "name")
        assert hasattr(backend, "binding_description")
        assert hasattr(backend, "is_global")
        assert hasattr(backend, "start")
        assert hasattr(backend, "stop")
        assert hasattr(backend, "is_running")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
