"""Tests for cadence_status — durable daemon status tracking.

Covers:
- init_status creates file
- record_wake increments counter and stores phrase
- record_route stores transcript/intent/ok
- record_timeout increments counter
- record_error increments counter
- load_status round-trips
- run_turn with --transcript writes status
- replay via cadence_status script
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def status_dir(tmp_path):
    """Provide a temp root with state/ directory for status file."""
    state = tmp_path / "state"
    state.mkdir()
    return tmp_path


def test_init_creates_status_file(status_dir):
    from runtime.voice import cadence_status as cs
    cs._STATUS_FILE = status_dir / "state" / "cadence_status.json"
    cs._started_at = 0.0
    cs._counters = {"wake": 0, "route": 0, "error": 0, "timeout": 0}
    cs._last = {}
    cs.init_status(listener_mode="live", audio_device="TestMic", root=status_dir)
    assert cs._STATUS_FILE.exists()
    data = json.loads(cs._STATUS_FILE.read_text())
    assert data["state"] == "standby"
    assert data["listener_mode"] == "live"
    assert data["audio_device"] == "TestMic"


def test_record_wake_increments(status_dir):
    from runtime.voice import cadence_status as cs
    cs._STATUS_FILE = status_dir / "state" / "cadence_status.json"
    cs._started_at = 0.0
    cs._counters = {"wake": 0, "route": 0, "error": 0, "timeout": 0}
    cs._last = {}
    cs.init_status(root=status_dir)
    cs.record_wake(phrase="Jarvis", score=0.95)
    data = json.loads(cs._STATUS_FILE.read_text())
    assert data["wake_count"] == 1
    assert data["last_wake_phrase"] == "Jarvis"
    assert data["state"] == "wake_detected"


def test_record_route_stores_transcript(status_dir):
    from runtime.voice import cadence_status as cs
    cs._STATUS_FILE = status_dir / "state" / "cadence_status.json"
    cs._started_at = 0.0
    cs._counters = {"wake": 0, "route": 0, "error": 0, "timeout": 0}
    cs._last = {}
    cs.init_status(root=status_dir)
    cs.record_route(transcript="browse yahoo", intent="browser_action", ok=True)
    data = json.loads(cs._STATUS_FILE.read_text())
    assert data["route_count"] == 1
    assert data["last_transcript"] == "browse yahoo"
    assert data["last_intent"] == "browser_action"
    assert data["last_route_ok"] is True
    assert data["state"] == "standby"


def test_record_timeout_increments(status_dir):
    from runtime.voice import cadence_status as cs
    cs._STATUS_FILE = status_dir / "state" / "cadence_status.json"
    cs._started_at = 0.0
    cs._counters = {"wake": 0, "route": 0, "error": 0, "timeout": 0}
    cs._last = {}
    cs.init_status(root=status_dir)
    cs.record_timeout()
    cs.record_timeout()
    data = json.loads(cs._STATUS_FILE.read_text())
    assert data["timeout_count"] == 2


def test_record_error_increments(status_dir):
    from runtime.voice import cadence_status as cs
    cs._STATUS_FILE = status_dir / "state" / "cadence_status.json"
    cs._started_at = 0.0
    cs._counters = {"wake": 0, "route": 0, "error": 0, "timeout": 0}
    cs._last = {}
    cs.init_status(root=status_dir)
    cs.record_error(error="test error")
    data = json.loads(cs._STATUS_FILE.read_text())
    assert data["error_count"] == 1
    assert data["last_route_error"] == "test error"


def test_load_status_round_trips(status_dir):
    from runtime.voice import cadence_status as cs
    cs._STATUS_FILE = status_dir / "state" / "cadence_status.json"
    cs._started_at = 0.0
    cs._counters = {"wake": 0, "route": 0, "error": 0, "timeout": 0}
    cs._last = {}
    cs.init_status(listener_mode="legacy", root=status_dir)
    loaded = cs.load_status(root=status_dir)
    assert loaded["state"] == "standby"
    assert loaded["listener_mode"] == "legacy"


def test_load_status_missing_returns_empty(tmp_path):
    from runtime.voice.cadence_status import load_status
    result = load_status(root=tmp_path)
    assert result == {}


def test_run_turn_writes_status(tmp_path):
    """run_turn with a canned transcript should write status via record_*."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    # Pre-init status so the file path points to tmp
    from runtime.voice import cadence_status as cs
    cs._STATUS_FILE = state_dir / "cadence_status.json"
    cs._started_at = 0.0
    cs._counters = {"wake": 0, "route": 0, "error": 0, "timeout": 0}
    cs._last = {}
    cs.init_status(root=tmp_path)

    from runtime.voice.cadence_daemon import run_turn
    result = run_turn(
        passive_transcript="Jarvis research the latest VIX data",
        execute=False,
        root=ROOT,
        verbose=False,
    )
    assert result["phase"] == "routed"

    data = json.loads(cs._STATUS_FILE.read_text())
    assert data["wake_count"] == 1
    assert data["route_count"] == 1
    assert data["last_wake_phrase"] == "Jarvis"
    assert "VIX" in data["last_transcript"] or "vix" in data["last_transcript"].lower()


def test_run_turn_timeout_writes_status(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    from runtime.voice import cadence_status as cs
    cs._STATUS_FILE = state_dir / "cadence_status.json"
    cs._started_at = 0.0
    cs._counters = {"wake": 0, "route": 0, "error": 0, "timeout": 0}
    cs._last = {}
    cs.init_status(root=tmp_path)

    from runtime.voice.cadence_daemon import run_turn
    result = run_turn(
        passive_transcript="Jarvis",
        command_transcript="",
        execute=False,
        root=ROOT,
        verbose=False,
    )
    assert result["phase"] == "command_timeout"

    data = json.loads(cs._STATUS_FILE.read_text())
    assert data["wake_count"] == 1
    assert data["timeout_count"] == 1
