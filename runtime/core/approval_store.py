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

from runtime.core.artifact_store import demote_artifact, promote_artifact, revoke_artifact, select_task_artifact
from runtime.core.models import (
    ApprovalCheckpointRecord,
    ApprovalRecord,
    ApprovalStatus,
    RecordLifecycleState,
    TaskStatus,
    new_id,
    now_iso,
)
from runtime.core.task_events import append_event, make_event
from runtime.core.task_runtime import ready_to_ship_task, save_task
from runtime.core.task_store import add_approval_link, load_task, transition_task
from runtime.controls.control_store import assert_control_allows, control_blocks_action
from runtime.dashboard.rebuild_helpers import rebuild_all_outputs


def approvals_dir(root: Optional[Path] = None) -> Path:
    base = root or ROOT
    path = base / "state" / "approvals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def approval_checkpoints_dir(root: Optional[Path] = None) -> Path:
    base = root or ROOT
    path = base / "state" / "approval_checkpoints"
    path.mkdir(parents=True, exist_ok=True)
    return path


def approval_path(approval_id: str, root: Optional[Path] = None) -> Path:
    return approvals_dir(root) / f"{approval_id}.json"


def checkpoint_path(checkpoint_id: str, root: Optional[Path] = None) -> Path:
    return approval_checkpoints_dir(root) / f"{checkpoint_id}.json"


def save_approval(record: ApprovalRecord, root: Optional[Path] = None) -> ApprovalRecord:
    record.updated_at = now_iso()
    approval_path(record.approval_id, root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_approval(approval_id: str, root: Optional[Path] = None) -> Optional[ApprovalRecord]:
    path = approval_path(approval_id, root)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return ApprovalRecord.from_dict(data)


def save_approval_checkpoint(record: ApprovalCheckpointRecord, root: Optional[Path] = None) -> ApprovalCheckpointRecord:
    record.updated_at = now_iso()
    checkpoint_path(record.checkpoint_id, root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_approval_checkpoint(checkpoint_id: str, root: Optional[Path] = None) -> Optional[ApprovalCheckpointRecord]:
    path = checkpoint_path(checkpoint_id, root)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return ApprovalCheckpointRecord.from_dict(data)


def _is_ready_for_live_apply(task) -> bool:
    return (task.final_outcome or "").strip() == "candidate_ready_for_live_apply"


def _build_checkpoint(
    *,
    approval_id: str,
    task,
    actor: str,
    lane: str,
    linked_artifact_ids: list[str],
    summary: str,
    details: str,
) -> ApprovalCheckpointRecord:
    return ApprovalCheckpointRecord(
        checkpoint_id=new_id("chk"),
        approval_id=approval_id,
        task_id=task.task_id,
        created_at=now_iso(),
        updated_at=now_iso(),
        created_by=actor,
        lane=lane,
        status="pending",
        linked_artifact_ids=linked_artifact_ids,
        task_status_when_paused=task.status,
        task_lifecycle_state_when_paused=task.lifecycle_state,
        checkpoint_summary=task.checkpoint_summary or summary,
        final_outcome_snapshot=task.final_outcome,
        execution_backend=task.execution_backend,
        backend_run_id=task.backend_run_id,
        resume_target_status=TaskStatus.READY_TO_SHIP.value if _is_ready_for_live_apply(task) else TaskStatus.QUEUED.value,
        resume_reason=details or summary,
        task_snapshot={
            "status": task.status,
            "lifecycle_state": task.lifecycle_state,
            "checkpoint_summary": task.checkpoint_summary,
            "final_outcome": task.final_outcome,
            "execution_backend": task.execution_backend,
            "backend_run_id": task.backend_run_id,
            "promoted_artifact_id": task.promoted_artifact_id,
        },
    )


def ensure_approval_checkpoint(
    *,
    approval: ApprovalRecord,
    task,
    actor: str,
    lane: str,
    summary: str,
    details: str,
    root: Optional[Path] = None,
) -> ApprovalCheckpointRecord:
    if approval.resumable_checkpoint_id:
        existing = load_approval_checkpoint(approval.resumable_checkpoint_id, root=root)
        if existing is not None:
            return existing

    checkpoint = _build_checkpoint(
        approval_id=approval.approval_id,
        task=task,
        actor=actor,
        lane=lane,
        linked_artifact_ids=list(approval.linked_artifact_ids),
        summary=summary,
        details=details,
    )
    save_approval_checkpoint(checkpoint, root=root)
    approval.resumable_checkpoint_id = checkpoint.checkpoint_id
    save_approval(approval, root=root)

    append_event(
        make_event(
            task_id=approval.task_id,
            event_type="approval_checkpoint_created",
            actor=actor,
            lane=lane,
            summary=f"Approval checkpoint created: {checkpoint.checkpoint_id}",
            from_status=task.status,
            to_status=TaskStatus.WAITING_APPROVAL.value,
            checkpoint_summary=checkpoint.checkpoint_summary,
            artifact_id=checkpoint.linked_artifact_ids[0] if checkpoint.linked_artifact_ids else None,
            execution_backend=checkpoint.execution_backend,
            backend_run_id=checkpoint.backend_run_id,
            details=details or summary,
        ),
        root=root,
    )
    return checkpoint


def list_approvals_for_task(task_id: str, root: Optional[Path] = None) -> list[ApprovalRecord]:
    items: list[ApprovalRecord] = []
    for path in approvals_dir(root).glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            record = ApprovalRecord.from_dict(data)
            if record.task_id == task_id:
                items.append(record)
        except Exception:
            continue
    items.sort(key=lambda x: x.updated_at, reverse=True)
    return items


def latest_approval_for_task(task_id: str, root: Optional[Path] = None) -> Optional[ApprovalRecord]:
    items = list_approvals_for_task(task_id, root=root)
    return items[0] if items else None


def request_approval(
    *,
    task_id: str,
    approval_type: str,
    requested_by: str,
    requested_reviewer: str,
    lane: str,
    summary: str,
    details: str = "",
    linked_artifact_ids: Optional[list[str]] = None,
    root: Optional[Path] = None,
) -> ApprovalRecord:
    task = load_task(task_id, root=root)
    if task is None:
        raise ValueError(f"Task not found: {task_id}")

    if linked_artifact_ids is None:
        artifact = select_task_artifact(
            task_id=task_id,
            root=root,
            allowed_states={RecordLifecycleState.CANDIDATE.value, RecordLifecycleState.PROMOTED.value},
        )
        linked_artifact_ids = [artifact.artifact_id] if artifact else []

    existing = latest_approval_for_task(task_id, root=root)
    if existing and existing.status == ApprovalStatus.PENDING.value:
        ensure_approval_checkpoint(
            approval=existing,
            task=task,
            actor=requested_by,
            lane=lane,
            summary=summary,
            details=details,
            root=root,
        )
        return existing

    record = ApprovalRecord(
        approval_id=new_id("apr"),
        task_id=task_id,
        requested_at=now_iso(),
        updated_at=now_iso(),
        requested_by=requested_by,
        requested_reviewer=requested_reviewer,
        lane=lane,
        approval_type=approval_type,
        status=ApprovalStatus.PENDING.value,
        summary=summary,
        details=details,
        linked_artifact_ids=linked_artifact_ids or [],
    )

    save_approval(record, root=root)
    checkpoint = ensure_approval_checkpoint(
        approval=record,
        task=task,
        actor=requested_by,
        lane=lane,
        summary=summary,
        details=details,
        root=root,
    )
    record.resumable_checkpoint_id = checkpoint.checkpoint_id
    save_approval(record, root=root)
    add_approval_link(task_id, record.approval_id, root=root)

    if task.status != TaskStatus.WAITING_APPROVAL.value:
        transition_task(
            task_id=task_id,
            to_status=TaskStatus.WAITING_APPROVAL.value,
            actor=requested_by,
            lane=lane,
            summary=f"Approval requested from {requested_reviewer}",
            root=root,
            details=summary,
            approval_id=record.approval_id,
        )

    append_event(
        make_event(
            task_id=task_id,
            event_type="approval_requested",
            actor=requested_by,
            lane=lane,
            summary=f"Approval request created: {record.approval_id}",
            from_status=TaskStatus.WAITING_APPROVAL.value,
            to_status=TaskStatus.WAITING_APPROVAL.value,
            checkpoint_summary=checkpoint.checkpoint_summary,
            details=summary,
            approval_id=record.approval_id,
        ),
        root=root,
    )
    rebuild_all_outputs(Path(root or ROOT))
    return record


def resume_approval_from_checkpoint(
    *,
    approval_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    reason: str = "",
) -> dict:
    approval = load_approval(approval_id, root=root)
    if approval is None:
        raise ValueError(f"Approval not found: {approval_id}")
    if approval.status != ApprovalStatus.APPROVED.value:
        raise ValueError(f"Approval {approval_id} is `{approval.status}` and cannot be resumed.")
    if not approval.resumable_checkpoint_id:
        raise ValueError(f"Approval {approval_id} has no resumable checkpoint.")

    checkpoint = load_approval_checkpoint(approval.resumable_checkpoint_id, root=root)
    if checkpoint is None:
        raise ValueError(f"Approval checkpoint not found: {approval.resumable_checkpoint_id}")
    if checkpoint.approval_id != approval_id:
        raise ValueError(f"Checkpoint {checkpoint.checkpoint_id} does not belong to approval {approval_id}.")
    if checkpoint.task_id != approval.task_id:
        raise ValueError(f"Checkpoint {checkpoint.checkpoint_id} does not match task {approval.task_id}.")

    task = load_task(approval.task_id, root=root)
    if task is None:
        raise ValueError(f"Task not found for approval resume: {approval.task_id}")
    subsystem = task.execution_backend if task.execution_backend != "unassigned" else lane
    assert_control_allows(
        action="approval_resume",
        root=root,
        task_id=approval.task_id,
        subsystem=subsystem,
    )

    artifact = select_task_artifact(
        task_id=approval.task_id,
        root=root,
        preferred_artifact_ids=checkpoint.linked_artifact_ids or approval.linked_artifact_ids,
        allowed_states={
            RecordLifecycleState.CANDIDATE.value,
            RecordLifecycleState.PROMOTED.value,
            RecordLifecycleState.DEMOTED.value,
            RecordLifecycleState.SUPERSEDED.value,
        },
    )
    if checkpoint.linked_artifact_ids and artifact is None:
        raise ValueError(f"Approval resume checkpoint {checkpoint.checkpoint_id} cannot bind a linked artifact.")

    if artifact is not None and artifact.lifecycle_state == RecordLifecycleState.CANDIDATE.value:
        artifact = promote_artifact(
            artifact_id=artifact.artifact_id,
            actor=actor,
            lane=lane,
            root=root,
            provenance_ref=f"approval:{approval_id}",
        )
        task = load_task(approval.task_id, root=root)
        if task is None:
            raise ValueError(f"Task not found after artifact promotion: {approval.task_id}")

    task.checkpoint_summary = checkpoint.checkpoint_summary or task.checkpoint_summary
    if not task.final_outcome and checkpoint.final_outcome_snapshot:
        task.final_outcome = checkpoint.final_outcome_snapshot
    task.execution_backend = checkpoint.execution_backend or task.execution_backend
    if checkpoint.backend_run_id:
        task.backend_run_id = checkpoint.backend_run_id
    task.backend_metadata.setdefault("approval_resume", {})
    task.backend_metadata["approval_resume"] = {
        "approval_id": approval_id,
        "checkpoint_id": checkpoint.checkpoint_id,
        "resumed_at": now_iso(),
        "resumed_by": actor,
    }
    save_task(Path(root or ROOT).resolve(), task)

    resume_target_status = (
        TaskStatus.READY_TO_SHIP.value
        if _is_ready_for_live_apply(task)
        else checkpoint.resume_target_status
    )
    checkpoint.resume_target_status = resume_target_status

    if resume_target_status == TaskStatus.READY_TO_SHIP.value:
        result = ready_to_ship_task(
            root=Path(root or ROOT).resolve(),
            task_id=approval.task_id,
            actor=actor,
            lane=lane,
            reason=reason or checkpoint.resume_reason or f"Resumed after approval: {approval_id}",
        )
    else:
        result = transition_task(
            task_id=approval.task_id,
            to_status=TaskStatus.QUEUED.value,
            actor=actor,
            lane=lane,
            summary=f"Approval resume queued task: {approval_id}",
            root=root,
            details=reason or checkpoint.resume_reason,
            approval_id=approval_id,
        ).to_dict()

    checkpoint.status = "resumed"
    checkpoint.resume_count += 1
    checkpoint.resumed_at = now_iso()
    save_approval_checkpoint(checkpoint, root=root)

    append_event(
        make_event(
            task_id=approval.task_id,
            event_type="approval_resumed_from_checkpoint",
            actor=actor,
            lane=lane,
            summary=f"Approval resumed from checkpoint: {checkpoint.checkpoint_id}",
            from_status=checkpoint.task_status_when_paused,
            to_status=result.get("status"),
            checkpoint_summary=checkpoint.checkpoint_summary,
            artifact_id=artifact.artifact_id if artifact else None,
            artifact_type=artifact.artifact_type if artifact else None,
            artifact_title=artifact.title if artifact else None,
            execution_backend=task.execution_backend,
            backend_run_id=task.backend_run_id,
            details=reason or checkpoint.resume_reason,
        ),
        root=root,
    )
    rebuild_all_outputs(Path(root or ROOT))
    return {
        "approval_id": approval_id,
        "checkpoint_id": checkpoint.checkpoint_id,
        "task_id": approval.task_id,
        "artifact_id": artifact.artifact_id if artifact else None,
        "task_status_after": result.get("status"),
        "resume_target_status": checkpoint.resume_target_status,
        "resume_count": checkpoint.resume_count,
    }


def record_approval_decision(
    *,
    approval_id: str,
    decision: str,
    actor: str,
    lane: str,
    reason: str = "",
    root: Optional[Path] = None,
) -> ApprovalRecord:
    record = load_approval(approval_id, root=root)
    if record is None:
        raise ValueError(f"Approval not found: {approval_id}")

    if decision not in {
        ApprovalStatus.APPROVED.value,
        ApprovalStatus.REJECTED.value,
        ApprovalStatus.CANCELLED.value,
    }:
        raise ValueError(f"Invalid approval decision: {decision}")

    record.status = decision
    record.decision_reason = reason
    save_approval(record, root=root)

    task = load_task(record.task_id, root=root)
    if task is None:
        raise ValueError(f"Task not found for approval: {record.task_id}")

    artifact = select_task_artifact(
        task_id=record.task_id,
        root=root,
        preferred_artifact_ids=record.linked_artifact_ids,
        allowed_states={
            RecordLifecycleState.CANDIDATE.value,
            RecordLifecycleState.PROMOTED.value,
            RecordLifecycleState.DEMOTED.value,
            RecordLifecycleState.SUPERSEDED.value,
        },
    )

    control_hold_reason = ""
    if decision == ApprovalStatus.APPROVED.value:
        subsystem = task.execution_backend if task.execution_backend != "unassigned" else lane
        blocked, message, _ = control_blocks_action(
            action="approval_resume",
            root=root,
            task_id=record.task_id,
            subsystem=subsystem,
        )
        if blocked:
            control_hold_reason = message
            transition_task(
                task_id=record.task_id,
                to_status=TaskStatus.BLOCKED.value,
                actor=actor,
                lane=lane,
                summary=f"Approval granted but held by control state: {approval_id}",
                root=root,
                details=message,
                approval_id=approval_id,
            )
            append_event(
                make_event(
                    task_id=record.task_id,
                    event_type="approval_resume_blocked_by_control_state",
                    actor=actor,
                    lane=lane,
                    summary=f"Approval resume blocked by control state: {approval_id}",
                    from_status=task.status,
                    to_status=TaskStatus.BLOCKED.value,
                    checkpoint_summary=task.checkpoint_summary,
                    artifact_id=artifact.artifact_id if artifact else None,
                    artifact_type=artifact.artifact_type if artifact else None,
                    artifact_title=artifact.title if artifact else None,
                    execution_backend=task.execution_backend,
                    backend_run_id=task.backend_run_id,
                    details=message,
                ),
                root=root,
            )
        else:
            try:
                resume_approval_from_checkpoint(
                    approval_id=approval_id,
                    actor=actor,
                    lane=lane,
                    root=root,
                    reason=reason or f"Approval granted: {approval_id}",
                )
            except Exception as exc:
                transition_task(
                    task_id=record.task_id,
                    to_status=TaskStatus.BLOCKED.value,
                    actor=actor,
                    lane=lane,
                    summary=f"Approval granted but resume failed: {approval_id}",
                    root=root,
                    details=str(exc),
                    approval_id=approval_id,
                )
                raise
    else:
        checkpoint = (
            load_approval_checkpoint(record.resumable_checkpoint_id, root=root)
            if record.resumable_checkpoint_id
            else None
        )
        if checkpoint is not None:
            checkpoint.status = "cancelled"
            save_approval_checkpoint(checkpoint, root=root)
        if artifact:
            if artifact.lifecycle_state == RecordLifecycleState.CANDIDATE.value:
                demote_artifact(
                    artifact_id=artifact.artifact_id,
                    actor=actor,
                    lane=lane,
                    root=root,
                )
            elif artifact.lifecycle_state == RecordLifecycleState.PROMOTED.value:
                revoke_artifact(
                    artifact_id=artifact.artifact_id,
                    actor=actor,
                    lane=lane,
                    root=root,
                    reason=reason or f"Approval decision {decision} revoked promoted artifact.",
                )
        transition_task(
            task_id=record.task_id,
            to_status=TaskStatus.BLOCKED.value,
            actor=actor,
            lane=lane,
            summary=f"Approval not granted: {approval_id}",
            root=root,
            details=reason,
            approval_id=approval_id,
        )

    append_event(
        make_event(
            task_id=record.task_id,
            event_type="approval_recorded",
            actor=actor,
            lane=lane,
            summary=f"Approval decision recorded: {decision}",
            from_status=None,
            to_status=None,
            details=control_hold_reason or reason,
            approval_id=approval_id,
        ),
        root=root,
    )
    rebuild_all_outputs(Path(root or ROOT))
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Request, resume, or resolve an approval object for a task.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    sub = parser.add_subparsers(dest="command", required=True)

    req = sub.add_parser("request")
    req.add_argument("--task-id", required=True)
    req.add_argument("--approval-type", required=True)
    req.add_argument("--requested-by", default="operator")
    req.add_argument("--requested-reviewer", default="anton")
    req.add_argument("--lane", default="review")
    req.add_argument("--summary", required=True)
    req.add_argument("--details", default="")

    dec = sub.add_parser("decide")
    dec.add_argument("--approval-id", required=True)
    dec.add_argument("--decision", required=True, choices=["approved", "rejected", "cancelled"])
    dec.add_argument("--actor", default="reviewer")
    dec.add_argument("--lane", default="review")
    dec.add_argument("--reason", default="")

    resume = sub.add_parser("resume")
    resume.add_argument("--approval-id", required=True)
    resume.add_argument("--actor", default="operator")
    resume.add_argument("--lane", default="review")
    resume.add_argument("--reason", default="")

    args = parser.parse_args()
    root = Path(args.root).resolve()

    if args.command == "request":
        record = request_approval(
            task_id=args.task_id,
            approval_type=args.approval_type,
            requested_by=args.requested_by,
            requested_reviewer=args.requested_reviewer,
            lane=args.lane,
            summary=args.summary,
            details=args.details,
            root=root,
        )
        print(json.dumps(record.to_dict(), indent=2))
        return 0

    if args.command == "resume":
        result = resume_approval_from_checkpoint(
            approval_id=args.approval_id,
            actor=args.actor,
            lane=args.lane,
            reason=args.reason,
            root=root,
        )
        print(json.dumps(result, indent=2))
        return 0

    record = record_approval_decision(
        approval_id=args.approval_id,
        decision=args.decision,
        actor=args.actor,
        lane=args.lane,
        reason=args.reason,
        root=root,
    )

    print(json.dumps(record.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
