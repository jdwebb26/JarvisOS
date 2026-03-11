#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import VoiceSessionRecord, new_id, now_iso


def voice_sessions_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "voice_sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(voice_session_id: str, *, root: Optional[Path] = None) -> Path:
    return voice_sessions_dir(root) / f"{voice_session_id}.json"


def voice_session_artifacts_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "voice_session_artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _artifact_path(voice_session_artifact_id: str, *, root: Optional[Path] = None) -> Path:
    return voice_session_artifacts_dir(root) / f"{voice_session_artifact_id}.json"


def save_voice_session(record: VoiceSessionRecord, *, root: Optional[Path] = None) -> VoiceSessionRecord:
    record.updated_at = now_iso()
    _path(record.voice_session_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def list_voice_sessions(*, root: Optional[Path] = None) -> list[VoiceSessionRecord]:
    rows: list[VoiceSessionRecord] = []
    for path in voice_sessions_dir(root).glob("*.json"):
        try:
            rows.append(VoiceSessionRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: (row.updated_at, row.created_at), reverse=True)
    return rows


def load_voice_session(voice_session_id: str, *, root: Optional[Path] = None) -> Optional[VoiceSessionRecord]:
    path = _path(voice_session_id, root=root)
    if not path.exists():
        return None
    return VoiceSessionRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def ensure_default_voice_session_contract(*, root: Optional[Path] = None) -> VoiceSessionRecord:
    rows = list_voice_sessions(root=root)
    if rows:
        return rows[0]
    record = VoiceSessionRecord(
        voice_session_id=new_id("voicesess"),
        created_at=now_iso(),
        updated_at=now_iso(),
        actor="system",
        lane="voice",
        channel_type="text_fallback_only",
        caller_identity="unassigned",
        transcript_ref="",
        summary_ref="",
        active_task_id=None,
        barge_in_supported=False,
        escalation_state="disabled_by_policy",
        consent_state="required",
    )
    return save_voice_session(record, root=root)


def ensure_voice_session(
    *,
    voice_session_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
) -> VoiceSessionRecord:
    existing = load_voice_session(voice_session_id, root=root)
    if existing is not None:
        return existing
    return save_voice_session(
        VoiceSessionRecord(
            voice_session_id=voice_session_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            channel_type="text_fallback_only",
            caller_identity="unassigned",
            transcript_ref="",
            summary_ref="",
            active_task_id=None,
            barge_in_supported=False,
            escalation_state="disabled_by_policy",
            consent_state="required",
        ),
        root=root,
    )


def save_voice_session_artifact(
    *,
    voice_session_id: str,
    actor: str,
    lane: str,
    artifact_kind: str,
    title: str,
    summary: str,
    content: str,
    root: Optional[Path] = None,
    command_id: str = "",
    task_id: str = "",
) -> dict:
    record = {
        "voice_session_artifact_id": new_id("voiceart"),
        "voice_session_id": voice_session_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "actor": actor,
        "lane": lane,
        "artifact_kind": artifact_kind,
        "title": title,
        "summary": summary,
        "content": content,
        "command_id": command_id,
        "task_id": task_id,
    }
    _artifact_path(record["voice_session_artifact_id"], root=root).write_text(
        json.dumps(record, indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def update_voice_session_from_command(
    *,
    voice_session_id: str,
    actor: str,
    lane: str,
    command_id: str,
    raw_transcript: str,
    normalized_command: str,
    task_id: str,
    command_status: str,
    risk_tier: str,
    confirmation_required: bool = False,
    confirmation_state: str = "not_required",
    challenge_id: str | None = None,
    action_id: str | None = None,
    verification_status: str = "none",
    root: Optional[Path] = None,
) -> VoiceSessionRecord:
    session = ensure_voice_session(voice_session_id=voice_session_id, actor=actor, lane=lane, root=root)
    transcript_artifact = save_voice_session_artifact(
        voice_session_id=voice_session_id,
        actor=actor,
        lane=lane,
        artifact_kind="transcript",
        title="Voice transcript",
        summary=f"Transcript captured for command {command_id}.",
        content=str(raw_transcript or ""),
        command_id=command_id,
        task_id=task_id,
        root=root,
    )
    summary_artifact = save_voice_session_artifact(
        voice_session_id=voice_session_id,
        actor=actor,
        lane=lane,
        artifact_kind="summary",
        title="Voice session summary",
        summary=f"Voice command {command_status}; confirmation state {confirmation_state}.",
        content=(
            f"normalized_command: {normalized_command}\n"
            f"command_status: {command_status}\n"
            f"risk_tier: {risk_tier}\n"
            f"confirmation_required: {str(bool(confirmation_required)).lower()}\n"
            f"confirmation_state: {confirmation_state}\n"
            f"challenge_id: {challenge_id or ''}\n"
            f"action_id: {action_id or ''}\n"
            f"verification_status: {verification_status}\n"
        ),
        command_id=command_id,
        task_id=task_id,
        root=root,
    )
    session.actor = actor
    session.lane = lane
    session.transcript_ref = transcript_artifact["voice_session_artifact_id"]
    session.summary_ref = summary_artifact["voice_session_artifact_id"]
    session.active_task_id = task_id or session.active_task_id
    session.confirmation_required = bool(confirmation_required)
    session.confirmation_state = confirmation_state
    session.latest_command_id = command_id
    session.latest_challenge_id = challenge_id
    session.latest_action_id = action_id
    session.latest_verification_status = verification_status
    return save_voice_session(session, root=root)


def build_voice_session_summary(*, root: Optional[Path] = None) -> dict:
    latest = ensure_default_voice_session_contract(root=root)
    rows = list_voice_sessions(root=root)
    return {
        "voice_session_count": len(rows),
        "latest_voice_session": latest.to_dict(),
        "active_voice_session_count": sum(1 for row in rows if row.active_task_id),
        "transcript_present_count": sum(1 for row in rows if row.transcript_ref),
        "summary_present_count": sum(1 for row in rows if row.summary_ref),
        "confirmation_required_count": sum(1 for row in rows if row.confirmation_required),
        "challenge_linked_session_count": sum(1 for row in rows if row.latest_challenge_id),
        "barge_in_supported_count": sum(1 for row in rows if row.barge_in_supported),
        "consent_state_counts": {
            state: sum(1 for row in rows if row.consent_state == state)
            for state in sorted({row.consent_state for row in rows})
        },
        "escalation_state_counts": {
            state: sum(1 for row in rows if row.escalation_state == state)
            for state in sorted({row.escalation_state for row in rows})
        },
        "confirmation_state_counts": {
            state: sum(1 for row in rows if row.confirmation_state == state)
            for state in sorted({row.confirmation_state for row in rows})
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current VoiceSession summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_voice_session_summary(root=Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
