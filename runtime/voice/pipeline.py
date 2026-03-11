#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from runtime.core.models import VoiceCommandRecord, new_id, now_iso
from runtime.core.risk_tier import evaluate_risk_tier
from runtime.controls.control_store import assert_control_allows
from runtime.voice.feedback import play_voice_cue
from runtime.voice.wakeword import validate_wake_phrase


ROOT = Path(__file__).resolve().parents[2]


VOICE_COMMAND_ACTION_MAP = {
    "show status": "show_status",
    "open dashboard": "open_dashboard",
    "read logs": "read_logs",
    "recall memory": "recall_memory",
    "send external message": "send_external_message",
    "change credentials": "change_credentials",
    "delete files": "delete_files",
    "mutate files": "mutate_files",
}


def voice_commands_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "voice_commands"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _command_path(command_id: str, *, root: Optional[Path] = None) -> Path:
    return voice_commands_dir(root=root) / f"{command_id}.json"


def save_voice_command(record: VoiceCommandRecord, *, root: Optional[Path] = None) -> VoiceCommandRecord:
    record.updated_at = now_iso()
    _command_path(record.command_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_voice_command(command_id: str, *, root: Optional[Path] = None) -> VoiceCommandRecord:
    return VoiceCommandRecord.from_dict(
        json.loads(_command_path(command_id, root=root).read_text(encoding="utf-8"))
    )


def process_voice_transcript(
    raw_transcript,
    *,
    voice_session_id,
    actor,
    lane,
    task_id="",
    speaker_confidence=0.0,
    root=None,
) -> dict:
    resolved_root = Path(root or ROOT).resolve()
    assert_control_allows(
        action="voice_command",
        root=resolved_root,
        task_id=task_id or None,
        subsystem="voice_pipeline",
        actor=actor,
        lane=lane,
    )

    wake = validate_wake_phrase(raw_transcript)
    normalized_command = wake["normalized_command"]
    normalized_command_key = normalized_command.strip().lower()
    risk_action = VOICE_COMMAND_ACTION_MAP.get(normalized_command_key)
    if not risk_action:
        parts = normalized_command.split()
        risk_action = "_".join(part.lower() for part in parts) if parts else "show_status"
    risk = evaluate_risk_tier(
        risk_action,
        "voice_pipeline",
        {"transcript": raw_transcript},
    )
    status = "accepted" if wake["valid"] else "rejected"
    feedback_events = []
    if wake["wake_phrase_detected"]:
        feedback_events.append(play_voice_cue("wake_detected", actor=actor, lane=lane, root=resolved_root))
    elif not wake["valid"]:
        feedback_events.append(play_voice_cue("wake_rejected", actor=actor, lane=lane, root=resolved_root))

    record = save_voice_command(
        VoiceCommandRecord(
            command_id=new_id("voicecmd"),
            voice_session_id=voice_session_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            raw_transcript=str(raw_transcript or ""),
            normalized_command=normalized_command,
            wake_phrase_detected=bool(wake["wake_phrase_detected"]),
            speaker_confidence=float(speaker_confidence or 0.0),
            risk_tier=risk["tier"],
            task_id=task_id or "",
            status=status,
        ),
        root=resolved_root,
    )
    if status == "accepted":
        feedback_events.append(play_voice_cue("command_accepted", actor=actor, lane=lane, root=resolved_root))
        if risk["tier"] == "high":
            feedback_events.append(play_voice_cue("confirmation_required", actor=actor, lane=lane, root=resolved_root))
    else:
        feedback_events.append(play_voice_cue("command_rejected", actor=actor, lane=lane, root=resolved_root))

    return {
        "status": status,
        "voice_command": record.to_dict(),
        "wakeword": wake,
        "risk": risk,
        "feedback": feedback_events,
    }
