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

from runtime.core.models import ApprovalStatus, RecordLifecycleState, ReviewRecord, ReviewStatus, TaskStatus, new_id, now_iso
from runtime.core.models import DecisionProvenanceRecord
from runtime.core.provenance_store import save_decision_provenance
from runtime.core.task_events import append_event, make_event
from runtime.core.task_store import add_review_link, load_task, transition_task
from runtime.dashboard.rebuild_helpers import rebuild_all_outputs
from runtime.core.artifact_store import demote_artifact, select_task_artifact
from runtime.core.candidate_store import record_candidate_rejection


def reviews_dir(root: Optional[Path] = None) -> Path:
    base = root or ROOT
    path = base / "state" / "reviews"
    path.mkdir(parents=True, exist_ok=True)
    return path


def review_path(review_id: str, root: Optional[Path] = None) -> Path:
    return reviews_dir(root) / f"{review_id}.json"


def save_review(record: ReviewRecord, root: Optional[Path] = None) -> ReviewRecord:
    record.updated_at = now_iso()
    review_path(record.review_id, root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_review(review_id: str, root: Optional[Path] = None) -> Optional[ReviewRecord]:
    path = review_path(review_id, root)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return ReviewRecord.from_dict(data)


def list_reviews_for_task(task_id: str, root: Optional[Path] = None) -> list[ReviewRecord]:
    items: list[ReviewRecord] = []
    for path in reviews_dir(root).glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            record = ReviewRecord.from_dict(data)
            if record.task_id == task_id:
                items.append(record)
        except Exception:
            continue
    items.sort(key=lambda x: x.updated_at, reverse=True)
    return items


def latest_review_for_task(task_id: str, root: Optional[Path] = None) -> Optional[ReviewRecord]:
    items = list_reviews_for_task(task_id, root=root)
    return items[0] if items else None


def choose_followup_approval_reviewer(task) -> str:
    if task.task_type in {"deploy", "quant"}:
        return "anton"
    if task.risk_level == "high_stakes":
        return "anton"
    return "operator"


def request_review(
    *,
    task_id: str,
    reviewer_role: str,
    requested_by: str,
    lane: str,
    summary: str,
    details: str = "",
    linked_artifact_ids: Optional[list[str]] = None,
    root: Optional[Path] = None,
) -> ReviewRecord:
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

    existing = latest_review_for_task(task_id, root=root)
    if existing and existing.status == ReviewStatus.PENDING.value:
        return existing

    record = ReviewRecord(
        review_id=new_id("rev"),
        task_id=task_id,
        requested_at=now_iso(),
        updated_at=now_iso(),
        reviewer_role=reviewer_role,
        requested_by=requested_by,
        lane=lane,
        status=ReviewStatus.PENDING.value,
        summary=summary,
        details=details,
        linked_artifact_ids=linked_artifact_ids or [],
    )

    save_review(record, root=root)
    add_review_link(task_id, record.review_id, root=root)

    if task.status != TaskStatus.WAITING_REVIEW.value:
        transition_task(
            task_id=task_id,
            to_status=TaskStatus.WAITING_REVIEW.value,
            actor=requested_by,
            lane=lane,
            summary=f"Review requested from {reviewer_role}",
            root=root,
            details=summary,
        )

    append_event(
        make_event(
            task_id=task_id,
            event_type="review_requested",
            actor=requested_by,
            lane=lane,
            summary=f"Review request created: {record.review_id}",
            from_status=TaskStatus.WAITING_REVIEW.value,
            to_status=TaskStatus.WAITING_REVIEW.value,
            details=summary,
        ),
        root=root,
    )
    rebuild_all_outputs(Path(root or ROOT))
    return record


def record_review_verdict(
    *,
    review_id: str,
    verdict: str,
    actor: str,
    lane: str,
    reason: str = "",
    root: Optional[Path] = None,
) -> ReviewRecord:
    record = load_review(review_id, root=root)
    if record is None:
        raise ValueError(f"Review not found: {review_id}")

    if verdict not in {
        ReviewStatus.APPROVED.value,
        ReviewStatus.CHANGES_REQUESTED.value,
        ReviewStatus.REJECTED.value,
    }:
        raise ValueError(f"Invalid review verdict: {verdict}")

    record.status = verdict
    record.verdict_reason = reason
    save_review(record, root=root)

    task = load_task(record.task_id, root=root)
    if task is None:
        raise ValueError(f"Task not found for review: {record.task_id}")

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

    if verdict == ReviewStatus.APPROVED.value:
        if task.approval_required:
            from runtime.core.approval_store import latest_approval_for_task, request_approval

            latest_approval = latest_approval_for_task(record.task_id, root=root)

            if latest_approval is None or latest_approval.status != ApprovalStatus.PENDING.value:
                request_approval(
                    task_id=record.task_id,
                    approval_type=task.task_type,
                    requested_by=actor,
                    requested_reviewer=choose_followup_approval_reviewer(task),
                    lane=lane,
                    summary=f"Approval required after review approval: {task.normalized_request}",
                    details=reason,
                    linked_artifact_ids=record.linked_artifact_ids,
                    root=root,
                )
            elif task.status != TaskStatus.WAITING_APPROVAL.value:
                transition_task(
                    task_id=record.task_id,
                    to_status=TaskStatus.WAITING_APPROVAL.value,
                    actor=actor,
                    lane=lane,
                    summary=f"Review approved and pending approval already exists: {latest_approval.approval_id}",
                    root=root,
                    details=reason,
                    approval_id=latest_approval.approval_id,
                )
        else:
            promoted_artifact = select_task_artifact(
                task_id=record.task_id,
                root=root,
                preferred_artifact_ids=record.linked_artifact_ids,
                allowed_states={RecordLifecycleState.PROMOTED.value},
            )
            if task.final_outcome and promoted_artifact is not None:
                next_status = TaskStatus.READY_TO_SHIP.value
            else:
                next_status = TaskStatus.QUEUED.value

            transition_task(
                task_id=record.task_id,
                to_status=next_status,
                actor=actor,
                lane=lane,
                summary=f"Review approved: {review_id}",
                root=root,
                details=reason,
            )
    else:
        if artifact and artifact.lifecycle_state == RecordLifecycleState.CANDIDATE.value:
            demote_artifact(
                artifact_id=artifact.artifact_id,
                actor=actor,
                lane=lane,
                root=root,
            )
            record_candidate_rejection(
                artifact_id=artifact.artifact_id,
                actor=actor,
                lane=lane,
                reason=reason or f"Review verdict {verdict} rejected the candidate.",
                trigger_event=f"review:{review_id}",
                root=root,
            )
        transition_task(
            task_id=record.task_id,
            to_status=TaskStatus.BLOCKED.value,
            actor=actor,
            lane=lane,
            summary=f"Review returned non-approval: {review_id}",
            root=root,
            details=reason,
            )

    save_decision_provenance(
        DecisionProvenanceRecord(
            decision_provenance_id=new_id("dprov"),
            decision_kind="review_decision",
            decision_id=record.review_id,
            task_id=record.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            source_artifact_ids=list(record.linked_artifact_ids),
            source_refs={"verdict": verdict, "reason": reason},
            replay_input={"review_id": record.review_id, "verdict": verdict, "task_id": record.task_id},
        ),
        root=root,
    )
    append_event(
        make_event(
            task_id=record.task_id,
            event_type="review_recorded",
            actor=actor,
            lane=lane,
            summary=f"Review verdict recorded: {verdict}",
            from_status=None,
            to_status=None,
            details=reason,
        ),
        root=root,
    )
    rebuild_all_outputs(Path(root or ROOT))
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Request or resolve a review object for a task.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    sub = parser.add_subparsers(dest="command", required=True)

    req = sub.add_parser("request")
    req.add_argument("--task-id", required=True)
    req.add_argument("--reviewer-role", required=True)
    req.add_argument("--requested-by", default="operator")
    req.add_argument("--lane", default="review")
    req.add_argument("--summary", required=True)
    req.add_argument("--details", default="")

    verdict = sub.add_parser("verdict")
    verdict.add_argument("--review-id", required=True)
    verdict.add_argument("--verdict", required=True, choices=["approved", "changes_requested", "rejected"])
    verdict.add_argument("--actor", default="reviewer")
    verdict.add_argument("--lane", default="review")
    verdict.add_argument("--reason", default="")

    args = parser.parse_args()
    root = Path(args.root).resolve()

    if args.command == "request":
        record = request_review(
            task_id=args.task_id,
            reviewer_role=args.reviewer_role,
            requested_by=args.requested_by,
            lane=args.lane,
            summary=args.summary,
            details=args.details,
            root=root,
        )
    else:
        record = record_review_verdict(
            review_id=args.review_id,
            verdict=args.verdict,
            actor=args.actor,
            lane=args.lane,
            reason=args.reason,
            root=root,
        )

    print(json.dumps(record.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
