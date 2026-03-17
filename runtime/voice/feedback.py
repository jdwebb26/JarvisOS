#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from runtime.core.models import new_id, now_iso


ROOT = Path(__file__).resolve().parents[2]

SUPPORTED_EVENT_TYPES = {
    "wake_detected",
    "wake_rejected",
    "command_accepted",
    "command_rejected",
    "confirmation_required",
}


def voice_feedback_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "voice_feedback"
    path.mkdir(parents=True, exist_ok=True)
    return path


def voice_responses_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "voice_responses"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _feedback_path(feedback_id: str, *, root: Optional[Path] = None) -> Path:
    return voice_feedback_dir(root=root) / f"{feedback_id}.json"


def _response_path(response_id: str, *, root: Optional[Path] = None) -> Path:
    return voice_responses_dir(root=root) / f"{response_id}.json"


def play_voice_cue(event_type: str, *, actor: str = "system", lane: str = "voice", root=None) -> dict:
    if event_type not in SUPPORTED_EVENT_TYPES:
        raise ValueError(f"Unsupported voice cue event_type: {event_type}")
    record = {
        "feedback_id": new_id("voicefb"),
        "event_type": event_type,
        "text": "",
        "status": "stubbed",
        "mode": "cue_placeholder",
        "reason": "audio_playback_not_connected",
        "actor": actor,
        "lane": lane,
        "created_at": now_iso(),
    }
    _feedback_path(record["feedback_id"], root=root).write_text(
        json.dumps(record, indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def _try_gateway_tts(text: str) -> str:
    """Attempt to play TTS via the openclaw gateway tts tool.

    Calls `openclaw agent --agent cadence --message <text>` with a tts request.
    Returns "ok", "skipped", or "failed:<reason>".
    Non-fatal — caller always falls through to record either way.
    """
    import shutil
    import subprocess as _sp

    if not shutil.which("openclaw"):
        return "skipped:no_openclaw_binary"
    try:
        # Use cadence_tts_request tag so Cadence responds with a TTS cue
        msg = f"[voice_cue] {text}"
        _sp.run(
            ["openclaw", "agent", "--agent", "cadence", "--message", msg, "--json"],
            capture_output=True, text=True, timeout=15,
        )
        return "ok"
    except Exception as exc:
        return f"failed:{exc}"


def speak_response(text: str, *, actor: str = "system", lane: str = "voice", root=None) -> dict:
    tts_status = _try_gateway_tts(text) if text else "skipped:empty"
    record = {
        "response_id": new_id("voicersp"),
        "event_type": "speak_response",
        "text": str(text or ""),
        "status": "attempted" if tts_status.startswith("ok") else "stubbed",
        "mode": "gateway_tts" if tts_status.startswith("ok") else "tts_placeholder",
        "reason": tts_status,
        "actor": actor,
        "lane": lane,
        "created_at": now_iso(),
    }
    _response_path(record["response_id"], root=root).write_text(
        json.dumps(record, indent=2) + "\n",
        encoding="utf-8",
    )
    return record
