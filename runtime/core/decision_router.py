#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.approval_store import latest_approval_for_task, request_approval
from runtime.core.review_store import latest_review_for_task, request_review
from runtime.core.task_store import load_task


def choose_reviewer(task_type: str, risk_level: str) -> str:
    if task_type == "code":
        return "archimedes"
    if task_type in {"deploy", "quant"}:
        return "anton"
    if risk_level in {"risky", "high_stakes"}:
        return "anton"
    return "archimedes"


def choose_approval_reviewer(task_type: str, risk_level: str) -> str:
    if task_type in {"deploy", "quant"}:
        return "anton"
    if risk_level == "high_stakes":
        return "anton"
    return "operator"


def route_task_for_decision(
    *,
    task_id: str,
    actor: str,
    lane: str,
    root: Path,
) -> dict:
    task = load_task(task_id, root=root)
    if task is None:
        raise ValueError(f"Task not found: {task_id}")

    latest_review = latest_review_for_task(task_id, root=root)
    latest_approval = latest_approval_for_task(task_id, root=root)

    if task.review_required:
        if latest_review is None:
            review = request_review(
                task_id=task_id,
                reviewer_role=choose_reviewer(task.task_type, task.risk_level),
                requested_by=actor,
                lane=lane,
                summary=f"Review required for task {task_id}: {task.normalized_request}",
                root=root,
            )
            return {
                "kind": "review_requested",
                "task_id": task_id,
                "review_id": review.review_id,
                "reviewer_role": review.reviewer_role,
                "status": review.status,
            }

        if latest_review.status == "pending":
            return {
                "kind": "waiting_review",
                "task_id": task_id,
                "review_id": latest_review.review_id,
                "reviewer_role": latest_review.reviewer_role,
                "status": latest_review.status,
                "message": "A review already exists and is still pending.",
            }

        if latest_review.status != "approved":
            return {
                "kind": "blocked_by_review",
                "task_id": task_id,
                "review_id": latest_review.review_id,
                "reviewer_role": latest_review.reviewer_role,
                "status": latest_review.status,
                "message": "The latest review is not approved, so the task cannot proceed.",
            }

    if task.approval_required:
        if latest_approval is None:
            approval = request_approval(
                task_id=task_id,
                approval_type=task.task_type,
                requested_by=actor,
                requested_reviewer=choose_approval_reviewer(task.task_type, task.risk_level),
                lane=lane,
                summary=f"Approval required for task {task_id}: {task.normalized_request}",
                root=root,
            )
            return {
                "kind": "approval_requested",
                "task_id": task_id,
                "approval_id": approval.approval_id,
                "requested_reviewer": approval.requested_reviewer,
                "status": approval.status,
            }

        if latest_approval.status == "pending":
            return {
                "kind": "waiting_approval",
                "task_id": task_id,
                "approval_id": latest_approval.approval_id,
                "requested_reviewer": latest_approval.requested_reviewer,
                "status": latest_approval.status,
                "message": "An approval request already exists and is still pending.",
            }

        if latest_approval.status != "approved":
            return {
                "kind": "blocked_by_approval",
                "task_id": task_id,
                "approval_id": latest_approval.approval_id,
                "requested_reviewer": latest_approval.requested_reviewer,
                "status": latest_approval.status,
                "message": "The latest approval is not approved, so the task cannot proceed.",
            }

    return {
        "kind": "no_action",
        "task_id": task_id,
        "message": "No new review or approval request was needed.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Route a task into review or approval if policy requires it.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--actor", default="operator", help="Requester")
    parser.add_argument("--lane", default="review", help="Lane")
    args = parser.parse_args()

    result = route_task_for_decision(
        task_id=args.task_id,
        actor=args.actor,
        lane=args.lane,
        root=Path(args.root).resolve(),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
