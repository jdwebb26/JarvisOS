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
        active_task_id=None,
        barge_in_supported=False,
        escalation_state="disabled_by_policy",
        consent_state="required",
    )
    return save_voice_session(record, root=root)


def build_voice_session_summary(*, root: Optional[Path] = None) -> dict:
    latest = ensure_default_voice_session_contract(root=root)
    rows = list_voice_sessions(root=root)
    return {
        "voice_session_count": len(rows),
        "latest_voice_session": latest.to_dict(),
        "active_voice_session_count": sum(1 for row in rows if row.active_task_id),
        "barge_in_supported_count": sum(1 for row in rows if row.barge_in_supported),
        "consent_state_counts": {
            state: sum(1 for row in rows if row.consent_state == state)
            for state in sorted({row.consent_state for row in rows})
        },
        "escalation_state_counts": {
            state: sum(1 for row in rows if row.escalation_state == state)
            for state in sorted({row.escalation_state for row in rows})
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
