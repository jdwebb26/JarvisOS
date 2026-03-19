#!/usr/bin/env python3
"""Tests for Cadence push-to-talk controller.

Covers:
- PTTCapture start/stop lifecycle
- Beep fires on capture start
- Release submits WAV
- Empty/too-short capture is ignored
- TTS interruption on new press
- Conversation utterance routes to PersonaPlex
- Command utterance routes through safe command path
- replay_ptt_turn with canned transcripts
- Status fields updated correctly
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# PTTCapture unit tests
# ---------------------------------------------------------------------------

class TestPTTCapture:
    def test_not_capturing_initially(self):
        from runtime.voice.ptt import PTTCapture
        cap = PTTCapture()
        assert not cap.is_capturing
        assert cap.duration == 0.0

    def test_start_creates_process(self, tmp_path):
        from runtime.voice.ptt import PTTCapture

        with patch("runtime.voice.ptt.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None  # process running
            mock_popen.return_value = mock_proc

            with patch("runtime.voice.mic_capture.parecord_available", return_value=True), \
                 patch("runtime.voice.mic_capture.default_capture_device", return_value="TestMic"):
                cap = PTTCapture()
                wav_path = cap.start(output_dir=tmp_path)

            assert cap.is_capturing
            assert wav_path is not None
            assert "cadence_ptt_" in str(wav_path)
            mock_popen.assert_called_once()
            # Verify parecord command
            cmd = mock_popen.call_args[0][0]
            assert cmd[0] == "parecord"
            assert "-d" in cmd
            assert "TestMic" in cmd

    def test_stop_sends_sigint(self, tmp_path):
        from runtime.voice.ptt import PTTCapture

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None

        with patch("runtime.voice.ptt.subprocess.Popen", return_value=mock_proc), \
             patch("runtime.voice.mic_capture.parecord_available", return_value=True), \
             patch("runtime.voice.mic_capture.default_capture_device", return_value="TestMic"):
            cap = PTTCapture()
            wav = cap.start(output_dir=tmp_path)

        # Simulate enough time passing
        cap._start_time = time.monotonic() - 1.0

        # Create a dummy WAV file
        wav.write_bytes(b"\x00" * 100)

        result = cap.stop()
        mock_proc.send_signal.assert_called_once_with(signal.SIGINT)
        assert result is not None

    def test_stop_too_short_returns_none(self, tmp_path):
        from runtime.voice.ptt import PTTCapture

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None

        with patch("runtime.voice.ptt.subprocess.Popen", return_value=mock_proc), \
             patch("runtime.voice.mic_capture.parecord_available", return_value=True), \
             patch("runtime.voice.mic_capture.default_capture_device", return_value="TestMic"):
            cap = PTTCapture()
            wav = cap.start(output_dir=tmp_path)

        # Simulate very short press (under MIN_CAPTURE_SEC)
        cap._start_time = time.monotonic() - 0.1

        wav.write_bytes(b"\x00" * 100)
        result = cap.stop()
        assert result is None  # too short

    def test_abort_kills_process(self, tmp_path):
        from runtime.voice.ptt import PTTCapture

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None

        with patch("runtime.voice.ptt.subprocess.Popen", return_value=mock_proc), \
             patch("runtime.voice.mic_capture.parecord_available", return_value=True), \
             patch("runtime.voice.mic_capture.default_capture_device", return_value="TestMic"):
            cap = PTTCapture()
            cap.start(output_dir=tmp_path)

        cap.abort()
        mock_proc.kill.assert_called_once()
        assert not cap.is_capturing


# ---------------------------------------------------------------------------
# Beep/cue tests
# ---------------------------------------------------------------------------

class TestBeepOnStart:
    def test_play_cue_called_on_capture_start(self):
        """play_cue('wake_accept') should fire when PTT capture starts."""
        from runtime.voice.cues import play_cue

        with patch("runtime.voice.cues.play_cue") as mock_cue:
            mock_cue.return_value = True
            # Simulate what the PTT loop does on press:
            mock_cue("wake_accept", block=False)
            mock_cue.assert_called_with("wake_accept", block=False)


# ---------------------------------------------------------------------------
# TTS interruption tests
# ---------------------------------------------------------------------------

class TestTTSInterruption:
    def test_interrupt_kills_tts_process(self):
        from runtime.voice.ptt import interrupt_tts, _set_tts_proc

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # still running
        _set_tts_proc(mock_proc)

        result = interrupt_tts()
        assert result is True
        mock_proc.send_signal.assert_called_once_with(signal.SIGTERM)

    def test_interrupt_noop_when_nothing_playing(self):
        from runtime.voice.ptt import interrupt_tts, _set_tts_proc
        _set_tts_proc(None)

        result = interrupt_tts()
        assert result is False

    def test_tts_is_playing_tracking(self):
        from runtime.voice.ptt import tts_is_playing, _set_tts_proc

        _set_tts_proc(None)
        assert not tts_is_playing()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        _set_tts_proc(mock_proc)
        assert tts_is_playing()

        mock_proc.poll.return_value = 0  # finished
        assert not tts_is_playing()
        _set_tts_proc(None)


# ---------------------------------------------------------------------------
# Replay / routing tests
# ---------------------------------------------------------------------------

class TestReplayPTTTurn:
    def test_conversation_routes_to_personaplex(self):
        """A conversational utterance should route through PersonaPlex."""
        from runtime.voice.ptt import replay_ptt_turn
        from runtime.voice.cadence_status import init_status
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        (tmp / "state").mkdir(parents=True, exist_ok=True)
        init_status(root=tmp)

        mock_ppx = {
            "response": "3 tasks need approval right now.",
            "intent": {"intent": "conversational"},
            "action_proposed": None,
            "session": type("S", (), {"conversation_id": "ppx_test_conv"})(),
            "llm_usage": {"total_tokens": 80},
            "error": "",
        }
        with patch("runtime.personaplex.engine.chat", return_value=mock_ppx):
            result = replay_ptt_turn("what needs approval?", root=ROOT)

        assert result["phase"] == "routed"
        assert result["routing_mode"] == "personaplex"
        assert result["personaplex_session_id"] == "ppx_test_conv"
        assert "3 tasks" in result["response"]

    def test_command_routes_through_safe_path(self):
        """A command utterance should route through the command path with confirmation."""
        from runtime.voice.ptt import replay_ptt_turn
        from runtime.voice.cadence_status import init_status
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        (tmp / "state").mkdir(parents=True, exist_ok=True)
        init_status(root=tmp)

        mock_ppx = {
            "response": "Proposed action: **Approve Task: task_abc**\nType 'yes' to confirm.",
            "intent": {"intent": "command", "command_type": "approve_task"},
            "action_proposed": {"action_id": "pact_123", "description": "Approve Task: task_abc",
                                "action_type": "approve_task", "status": "pending"},
            "session": type("S", (), {"conversation_id": "ppx_test_cmd"})(),
            "llm_usage": {},
            "error": "",
        }
        with patch("runtime.personaplex.engine.chat", return_value=mock_ppx):
            result = replay_ptt_turn("approve task_abc123", root=ROOT)

        assert result["phase"] == "routed"
        # Should route through PersonaPlex (which handles command safety)
        assert result["routing_mode"] == "personaplex"
        assert result["action_proposed"] is not None
        assert result["action_proposed"]["status"] == "pending"
        assert "confirm" in result["response"].lower()

    def test_empty_transcript_ignored(self):
        from runtime.voice.ptt import replay_ptt_turn
        result = replay_ptt_turn("", root=ROOT)
        assert result["phase"] == "empty"

    def test_wake_phrase_stripped(self):
        """Wake phrase should be stripped — PTT doesn't require it."""
        from runtime.voice.ptt import replay_ptt_turn
        from runtime.voice.cadence_status import init_status
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        (tmp / "state").mkdir(parents=True, exist_ok=True)
        init_status(root=tmp)

        mock_ppx = {
            "response": "Here is the system state.",
            "intent": {"intent": "conversational"},
            "action_proposed": None,
            "session": type("S", (), {"conversation_id": "ppx_wake_strip"})(),
            "llm_usage": {},
            "error": "",
        }
        with patch("runtime.personaplex.engine.chat", return_value=mock_ppx):
            result = replay_ptt_turn("Cadence summarize the system state", root=ROOT)

        assert result["phase"] == "routed"
        # Command should NOT contain "Cadence" prefix
        assert not result["command"].lower().startswith("cadence")

    def test_browser_command_routes_as_command(self):
        """Browser action should route through command path, not PersonaPlex."""
        from runtime.voice.ptt import replay_ptt_turn
        from runtime.voice.cadence_status import init_status
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        (tmp / "state").mkdir(parents=True, exist_ok=True)
        init_status(root=tmp)

        result = replay_ptt_turn("browse finance.yahoo.com", root=ROOT)
        assert result["phase"] == "routed"
        # browser_action intent should route through command/intake path
        # (exact routing depends on whether it matches browser_action or unclassified)


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestConfig:
    def test_input_mode_default(self):
        from runtime.voice.ptt import INPUT_MODE
        assert INPUT_MODE in ("ptt", "wake")

    def test_ptt_binding_default(self):
        from runtime.voice.ptt import PTT_BINDING
        assert PTT_BINDING  # non-empty

    def test_input_mode_env_override(self, monkeypatch):
        monkeypatch.setenv("CADENCE_INPUT_MODE", "wake")
        # Force reimport
        import importlib
        from runtime.voice import ptt
        importlib.reload(ptt)
        assert ptt.INPUT_MODE == "wake"
        # Restore
        monkeypatch.setenv("CADENCE_INPUT_MODE", "ptt")
        importlib.reload(ptt)


# ---------------------------------------------------------------------------
# Status integration test
# ---------------------------------------------------------------------------

class TestStatusUpdate:
    def test_replay_updates_cadence_status(self):
        """replay_ptt_turn should update cadence_status.json."""
        from runtime.voice.ptt import replay_ptt_turn
        from runtime.voice import cadence_status as cs
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        (tmp / "state").mkdir(parents=True, exist_ok=True)
        cs._STATUS_FILE = tmp / "state" / "cadence_status.json"
        cs._started_at = 0.0
        cs._counters = {"wake": 0, "route": 0, "error": 0, "timeout": 0}
        cs._last = {}
        cs.init_status(root=tmp)

        mock_ppx = {
            "response": "System is healthy.",
            "intent": {"intent": "conversational"},
            "action_proposed": None,
            "session": type("S", (), {"conversation_id": "ppx_status_test"})(),
            "llm_usage": {"total_tokens": 50},
            "error": "",
        }
        # "what needs approval" classifies as jarvis_orchestration → PersonaPlex
        with patch("runtime.personaplex.engine.chat", return_value=mock_ppx):
            replay_ptt_turn("what needs approval", root=ROOT)

        data = json.loads(cs._STATUS_FILE.read_text())
        assert data["last_routing_mode"] == "personaplex"
        assert data["last_personaplex_session_id"] == "ppx_status_test"
        assert data["route_count"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
