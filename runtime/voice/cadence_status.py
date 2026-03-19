#!/usr/bin/env python3
"""cadence_status — durable status file for the Cadence voice daemon.

Writes state/cadence_status.json on every meaningful state transition so
operators can inspect daemon health without reading journal logs.

Status file shape:
    {
        "state": "standby" | "wake_detected" | "command_window" | "routing" | "error",
        "updated_at": "2026-03-18T23:40:03Z",
        "started_at": "2026-03-18T23:00:00Z",
        "listener_mode": "live" | "legacy",
        "audio_device": "RDPSource",
        "mic_available": true | false,
        "mic_error": "",
        "wake_count": 42,
        "route_count": 30,
        "error_count": 3,
        "timeout_count": 9,
        "last_wake_at": "2026-03-18T23:38:00Z",
        "last_wake_phrase": "Jarvis",
        "last_transcript": "browse finance.yahoo.com",
        "last_intent": "browser_action",
        "last_route_ok": true,
        "last_route_error": "",
        "last_route_at": "2026-03-18T23:38:02Z",
        "uptime_seconds": 2403
    }
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]

_STATUS_FILE = ROOT / "state" / "cadence_status.json"
_started_at: float = 0.0
_counters: dict[str, int] = {"wake": 0, "route": 0, "error": 0, "timeout": 0}
_last: dict[str, Any] = {}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()[:19] + "Z"


def init_status(*, listener_mode: str = "", audio_device: str = "", root: Optional[Path] = None) -> None:
    """Call once at daemon start."""
    global _started_at, _counters, _last, _STATUS_FILE
    _started_at = time.monotonic()
    _counters = {"wake": 0, "route": 0, "error": 0, "timeout": 0}
    _last = {}
    if root:
        _STATUS_FILE = Path(root).resolve() / "state" / "cadence_status.json"
    _write_status(
        state="standby",
        listener_mode=listener_mode,
        audio_device=audio_device,
    )


def record_wake(*, phrase: str = "", score: float = 0.0) -> None:
    _counters["wake"] += 1
    _last["wake_at"] = _now_iso()
    _last["wake_phrase"] = phrase
    _last["wake_score"] = round(score, 3)
    _write_status(state="wake_detected")


def record_command_window() -> None:
    _write_status(state="command_window")


def record_route(*, transcript: str, intent: str, ok: bool, error: str = "") -> None:
    _counters["route"] += 1
    if not ok:
        _counters["error"] += 1
    _last["transcript"] = transcript
    _last["intent"] = intent
    _last["route_ok"] = ok
    _last["route_error"] = error
    _last["route_at"] = _now_iso()
    _write_status(state="standby")


def record_timeout() -> None:
    _counters["timeout"] += 1
    _write_status(state="standby")


def record_error(*, error: str) -> None:
    _counters["error"] += 1
    _last["route_error"] = error
    _write_status(state="standby")


def record_mic_status(*, available: bool, error: str = "", device: str = "") -> None:
    _last["mic_available"] = available
    _last["mic_error"] = error
    if device:
        _last["audio_device"] = device
    _write_status(state="standby")


def _write_status(*, state: str, listener_mode: str = "", audio_device: str = "") -> None:
    uptime = time.monotonic() - _started_at if _started_at else 0.0
    status = {
        "state": state,
        "updated_at": _now_iso(),
        "started_at": _last.get("_started_at_iso", _now_iso()),
        "listener_mode": listener_mode or _last.get("listener_mode", ""),
        "audio_device": audio_device or _last.get("audio_device", ""),
        "mic_available": _last.get("mic_available", True),
        "mic_error": _last.get("mic_error", ""),
        "wake_count": _counters["wake"],
        "route_count": _counters["route"],
        "error_count": _counters["error"],
        "timeout_count": _counters["timeout"],
        "last_wake_at": _last.get("wake_at", ""),
        "last_wake_phrase": _last.get("wake_phrase", ""),
        "last_transcript": _last.get("transcript", ""),
        "last_intent": _last.get("intent", ""),
        "last_route_ok": _last.get("route_ok", None),
        "last_route_error": _last.get("route_error", ""),
        "last_route_at": _last.get("route_at", ""),
        "uptime_seconds": round(uptime),
    }
    if listener_mode:
        _last["listener_mode"] = listener_mode
    if audio_device:
        _last["audio_device"] = audio_device
    if "_started_at_iso" not in _last:
        _last["_started_at_iso"] = status["updated_at"]

    try:
        _STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        tmp.replace(_STATUS_FILE)
    except Exception:
        pass


def load_status(root: Optional[Path] = None) -> dict[str, Any]:
    """Read the current status file. Returns empty dict if not found."""
    path = Path(root or ROOT).resolve() / "state" / "cadence_status.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
