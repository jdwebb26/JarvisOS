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

from runtime.core.models import (
    ApprovalDecisionContextRecord,
    ApprovalResumeTokenRecord,
    ApprovalSessionRecord,
    ApprovalStatus,
    now_iso,
    new_id,
)


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    root_path = Path(root or ROOT).resolve()
    path = root_path / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def approval_sessions_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("approval_sessions", root=root)


def approval_contexts_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("approval_decision_contexts", root=root)


def approval_resume_tokens_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("approval_resume_tokens", root=root)


def _path(folder: Path, record_id: str) -> Path:
    return folder / f"{record_id}.json"


def save_approval_session(record: ApprovalSessionRecord, root: Optional[Path] = None) -> ApprovalSessionRecord:
    record.updated_at = now_iso()
    _path(approval_sessions_dir(root), record.approval_session_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def save_approval_context(record: ApprovalDecisionContextRecord, root: Optional[Path] = None) -> ApprovalDecisionContextRecord:
    record.updated_at = now_iso()
    _path(approval_contexts_dir(root), record.context_snapshot_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def save_resume_token(record: ApprovalResumeTokenRecord, root: Optional[Path] = None) -> ApprovalResumeTokenRecord:
    record.updated_at = now_iso()
    _path(approval_resume_tokens_dir(root), record.resume_token_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def _load_rows(folder: Path, model) -> list:
    rows = []
    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(model.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def list_approval_sessions(root: Optional[Path] = None) -> list[ApprovalSessionRecord]:
    return _load_rows(approval_sessions_dir(root), ApprovalSessionRecord)


def list_approval_contexts(root: Optional[Path] = None) -> list[ApprovalDecisionContextRecord]:
    return _load_rows(approval_contexts_dir(root), ApprovalDecisionContextRecord)


def list_resume_tokens(root: Optional[Path] = None) -> list[ApprovalResumeTokenRecord]:
    return _load_rows(approval_resume_tokens_dir(root), ApprovalResumeTokenRecord)


def latest_approval_session(root: Optional[Path] = None) -> Optional[ApprovalSessionRecord]:
    rows = list_approval_sessions(root=root)
    return rows[0] if rows else None


def _load_session_by_approval_id(approval_id: str, root: Optional[Path] = None) -> Optional[ApprovalSessionRecord]:
    for row in list_approval_sessions(root=root):
        if row.approval_id == approval_id:
            return row
    return None


def ensure_approval_session(
    *,
    approval_id: str,
    task_id: str,
    approval_type: str,
    actor: str,
    lane: str,
    linked_artifact_ids: list[str],
    root: Optional[Path] = None,
) -> ApprovalSessionRecord:
    existing = _load_session_by_approval_id(approval_id, root=root)
    if existing is not None:
        return existing
    return save_approval_session(
        ApprovalSessionRecord(
            approval_session_id=new_id("aps"),
            approval_id=approval_id,
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            approval_type=approval_type,
            session_state="pending",
            resumable=True,
            terminal=False,
            linked_artifact_ids=list(linked_artifact_ids),
            decision_status=ApprovalStatus.PENDING.value,
        ),
        root=root,
    )


def record_pending_decision_context(
    *,
    approval_session_id: str,
    approval_id: str,
    task_id: str,
    actor: str,
    lane: str,
    task_snapshot: dict,
    linked_artifact_ids: list[str],
    checkpoint_summary: str,
    pending_reason: str,
    root: Optional[Path] = None,
) -> ApprovalDecisionContextRecord:
    context = save_approval_context(
        ApprovalDecisionContextRecord(
            context_snapshot_id=new_id("apctx"),
            approval_session_id=approval_session_id,
            approval_id=approval_id,
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            task_snapshot=dict(task_snapshot),
            linked_artifact_ids=list(linked_artifact_ids),
            checkpoint_summary=checkpoint_summary,
            pending_reason=pending_reason,
        ),
        root=root,
    )
    session = _load_session_by_approval_id(approval_id, root=root)
    if session is not None:
        session.latest_context_snapshot_id = context.context_snapshot_id
        session.linked_artifact_ids = list(linked_artifact_ids)
        session.session_state = "resumable_pending"
        save_approval_session(session, root=root)
    return context


def create_resume_token(
    *,
    approval_session_id: str,
    approval_id: str,
    checkpoint_id: str,
    task_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
) -> ApprovalResumeTokenRecord:
    token = save_resume_token(
        ApprovalResumeTokenRecord(
            resume_token_id=new_id("aprt"),
            approval_session_id=approval_session_id,
            approval_id=approval_id,
            checkpoint_id=checkpoint_id,
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            token_ref=f"resume:{approval_id}:{checkpoint_id}",
            status="active",
        ),
        root=root,
    )
    session = _load_session_by_approval_id(approval_id, root=root)
    if session is not None:
        session.latest_resume_token_id = token.resume_token_id
        session.latest_checkpoint_id = checkpoint_id
        session.resumable = True
        session.session_state = "resumable_pending"
        save_approval_session(session, root=root)
    return token


def update_approval_session_decision(
    *,
    approval_id: str,
    decision_status: str,
    decision_reason: str,
    resumable: bool,
    terminal: bool,
    session_state: str,
    root: Optional[Path] = None,
) -> Optional[ApprovalSessionRecord]:
    session = _load_session_by_approval_id(approval_id, root=root)
    if session is None:
        return None
    session.decision_status = decision_status
    session.decision_reason = decision_reason
    session.resumable = resumable
    session.terminal = terminal
    session.session_state = session_state
    return save_approval_session(session, root=root)


def mark_resume_token_consumed(
    *,
    approval_id: str,
    actor: str,
    root: Optional[Path] = None,
) -> Optional[ApprovalResumeTokenRecord]:
    session = _load_session_by_approval_id(approval_id, root=root)
    if session is None or not session.latest_resume_token_id:
        return None
    for token in list_resume_tokens(root=root):
        if token.resume_token_id != session.latest_resume_token_id:
            continue
        token.status = "consumed"
        token.consumed_at = now_iso()
        token.consumed_by = actor
        save_resume_token(token, root=root)
        return token
    return None


def mark_approval_session_resumed(
    *,
    approval_id: str,
    actor: str,
    root: Optional[Path] = None,
) -> Optional[ApprovalSessionRecord]:
    token = mark_resume_token_consumed(approval_id=approval_id, actor=actor, root=root)
    session = _load_session_by_approval_id(approval_id, root=root)
    if session is None:
        return None
    session.session_state = "resumed"
    session.resumable = False
    session.terminal = False
    if token is not None:
        session.latest_resume_token_id = token.resume_token_id
    return save_approval_session(session, root=root)


def build_approval_session_summary(root: Optional[Path] = None) -> dict:
    sessions = list_approval_sessions(root=root)
    contexts = list_approval_contexts(root=root)
    tokens = list_resume_tokens(root=root)
    return {
        "approval_session_count": len(sessions),
        "approval_context_count": len(contexts),
        "approval_resume_token_count": len(tokens),
        "latest_approval_session": sessions[0].to_dict() if sessions else None,
        "latest_resume_token": tokens[0].to_dict() if tokens else None,
        "resumable_session_count": sum(1 for row in sessions if row.resumable and not row.terminal),
        "terminal_session_count": sum(1 for row in sessions if row.terminal),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show resumable approval session summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_approval_session_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
