#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import OutputStatus, RecordLifecycleState, TaskRecord, TaskStatus
from runtime.controls.control_store import get_effective_control_state, list_control_records


def _load_jsons(folder: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not folder.exists():
        return rows

    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return rows


def _load_tasks(root: Path) -> list[TaskRecord]:
    return [TaskRecord.from_dict(row) for row in _load_jsons(root / "state" / "tasks")]


def _load_events_by_task(root: Path) -> dict[str, list[dict[str, Any]]]:
    rows = _load_jsons(root / "state" / "events")
    events_by_task: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        task_id = row.get("task_id")
        if not task_id:
            continue
        events_by_task.setdefault(task_id, []).append(row)
    for task_id in events_by_task:
        events_by_task[task_id].sort(key=lambda row: row.get("created_at", ""))
    return events_by_task


def _sort_key(task: TaskRecord) -> tuple[str, str]:
    created_at = getattr(task, "created_at", "") or ""
    updated_at = getattr(task, "updated_at", "") or ""
    return (updated_at, created_at)


def _latest_reason(task: TaskRecord, events_by_task: dict[str, list[dict[str, Any]]]) -> str:
    if task.last_error:
        return task.last_error

    for event in reversed(events_by_task.get(task.task_id, [])):
        reason = event.get("reason") or ""
        if reason:
            return reason
    return ""


def _task_summary(task: TaskRecord, events_by_task: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    control_state = get_effective_control_state(
        root=ROOT,
        task_id=task.task_id,
        subsystem=task.execution_backend if task.execution_backend != "unassigned" else task.source_lane,
    )
    return {
        "task_id": task.task_id,
        "summary": task.normalized_request,
        "status": task.status,
        "lifecycle_state": task.lifecycle_state,
        "priority": task.priority,
        "task_type": task.task_type,
        "execution_backend": task.execution_backend,
        "review_required": task.review_required,
        "approval_required": task.approval_required,
        "promoted_artifact_id": task.promoted_artifact_id,
        "candidate_artifact_ids": list(task.candidate_artifact_ids),
        "demoted_artifact_ids": list(task.demoted_artifact_ids),
        "revoked_artifact_ids": list(task.revoked_artifact_ids),
        "impacted_output_ids": list(task.impacted_output_ids),
        "reason": _latest_reason(task, events_by_task),
        "control_status": control_state["effective_status"],
        "control_run_state": control_state["effective_run_state"],
        "control_safety_mode": control_state["effective_safety_mode"],
        "control_reasons": control_state["active_reasons"],
        "updated_at": task.updated_at,
    }


def _artifact_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": artifact.get("artifact_id"),
        "task_id": artifact.get("task_id"),
        "title": artifact.get("title"),
        "artifact_type": artifact.get("artifact_type"),
        "lifecycle_state": artifact.get("lifecycle_state"),
        "producer_kind": artifact.get("producer_kind"),
        "execution_backend": artifact.get("execution_backend"),
        "superseded_by_artifact_id": artifact.get("superseded_by_artifact_id"),
        "downstream_impacted_output_ids": artifact.get("downstream_impacted_output_ids", []),
        "revoked_at": artifact.get("revoked_at"),
        "revocation_reason": artifact.get("revocation_reason", ""),
        "updated_at": artifact.get("updated_at"),
    }


def _output_summary(output: dict[str, Any]) -> dict[str, Any]:
    return {
        "output_id": output.get("output_id"),
        "task_id": output.get("task_id"),
        "artifact_id": output.get("artifact_id"),
        "title": output.get("title"),
        "status": output.get("status", OutputStatus.PUBLISHED.value),
        "superseded_by_artifact_id": output.get("superseded_by_artifact_id"),
        "impacted_by_artifact_ids": output.get("impacted_by_artifact_ids", []),
        "revocation_reason": output.get("revocation_reason", ""),
        "published_at": output.get("published_at"),
    }


def build_status(root: Path) -> dict[str, Any]:
    tasks = sorted(_load_tasks(root), key=_sort_key, reverse=True)
    events_by_task = _load_events_by_task(root)
    task_rows = []
    for task in tasks:
        control_state = get_effective_control_state(
            root=root,
            task_id=task.task_id,
            subsystem=task.execution_backend if task.execution_backend != "unassigned" else task.source_lane,
        )
        row = {
            "task_id": task.task_id,
            "summary": task.normalized_request,
            "status": task.status,
            "lifecycle_state": task.lifecycle_state,
            "priority": task.priority,
            "task_type": task.task_type,
            "execution_backend": task.execution_backend,
            "review_required": task.review_required,
            "approval_required": task.approval_required,
            "promoted_artifact_id": task.promoted_artifact_id,
            "candidate_artifact_ids": list(task.candidate_artifact_ids),
            "demoted_artifact_ids": list(task.demoted_artifact_ids),
            "revoked_artifact_ids": list(task.revoked_artifact_ids),
            "impacted_output_ids": list(task.impacted_output_ids),
            "reason": _latest_reason(task, events_by_task),
            "control_status": control_state["effective_status"],
            "control_run_state": control_state["effective_run_state"],
            "control_safety_mode": control_state["effective_safety_mode"],
            "control_reasons": control_state["active_reasons"],
            "updated_at": task.updated_at,
        }
        task_rows.append(row)

    artifacts = _load_jsons(root / "state" / "artifacts")
    outputs = _load_jsons(root / "workspace" / "out")
    reviews = _load_jsons(root / "state" / "reviews")
    approvals = _load_jsons(root / "state" / "approvals")
    control_records = [record.to_dict() for record in list_control_records(root=root)]
    paused_controls = [row for row in control_records if row.get("run_state") == "paused"]
    stopped_controls = [row for row in control_records if row.get("run_state") == "stopped"]
    degraded_controls = [row for row in control_records if row.get("safety_mode") == "degraded"]
    revoked_controls = [row for row in control_records if row.get("safety_mode") == "revoked"]
    global_control = get_effective_control_state(root=root)
    effective_run_state = "active"
    effective_safety_mode = "normal"
    if stopped_controls:
        effective_run_state = "stopped"
    elif paused_controls:
        effective_run_state = "paused"
    if revoked_controls:
        effective_safety_mode = "revoked"
    elif degraded_controls:
        effective_safety_mode = "degraded"
    effective_status = "active"
    if effective_run_state == "stopped":
        effective_status = "stopped"
    elif effective_run_state == "paused":
        effective_status = "paused"
    elif effective_safety_mode == "revoked":
        effective_status = "revoked"
    elif effective_safety_mode == "degraded":
        effective_status = "degraded"
    effective_control = {
        "effective_status": effective_status,
        "effective_run_state": effective_run_state,
        "effective_safety_mode": effective_safety_mode,
        "records": global_control.get("records", []),
        "active_reasons": global_control.get("active_reasons", []),
        "has_active_controls": bool(control_records),
    }

    queued_now = [row for row in task_rows if row["status"] == TaskStatus.QUEUED.value]
    running_now = [row for row in task_rows if row["status"] == TaskStatus.RUNNING.value]
    blocked = [row for row in task_rows if row["status"] == TaskStatus.BLOCKED.value]
    waiting_review = [row for row in task_rows if row["status"] == TaskStatus.WAITING_REVIEW.value]
    waiting_approval = [row for row in task_rows if row["status"] == TaskStatus.WAITING_APPROVAL.value]
    ready_to_ship = [row for row in task_rows if row["status"] == TaskStatus.READY_TO_SHIP.value]
    shipped = [row for row in task_rows if row["status"] == TaskStatus.SHIPPED.value]
    finished_recently = [
        row
        for row in task_rows
        if row["status"] in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
            TaskStatus.ARCHIVED.value,
        }
    ][:10]

    candidate_artifacts = [
        _artifact_summary(row)
        for row in artifacts
        if row.get("lifecycle_state") == RecordLifecycleState.CANDIDATE.value
    ]
    impacted_artifacts = [
        _artifact_summary(row)
        for row in artifacts
        if row.get("lifecycle_state") in {RecordLifecycleState.DEMOTED.value, RecordLifecycleState.SUPERSEDED.value}
    ]
    revoked_artifacts = [
        _artifact_summary(row)
        for row in artifacts
        if row.get("revoked_at")
    ]
    impacted_outputs = [
        _output_summary(row)
        for row in outputs
        if row.get("status") == OutputStatus.IMPACTED.value
    ]
    revoked_outputs = [
        _output_summary(row)
        for row in outputs
        if row.get("status") == OutputStatus.REVOKED.value
    ]

    pending_reviews = [row for row in reviews if row.get("status") == "pending"]
    pending_approvals = [row for row in approvals if row.get("status") == "pending"]

    counts = {
        "total_tasks": len(task_rows),
        "queued": len(queued_now),
        "running": len(running_now),
        "blocked": len(blocked),
        "waiting_review": len(waiting_review),
        "waiting_approval": len(waiting_approval),
        "ready_to_ship": len(ready_to_ship),
        "shipped": len(shipped),
        "finished_recently": len(finished_recently),
        "candidate_artifacts": len(candidate_artifacts),
        "impacted_artifacts": len(impacted_artifacts),
        "revoked_artifacts": len(revoked_artifacts),
        "impacted_outputs": len(impacted_outputs),
        "revoked_outputs": len(revoked_outputs),
        "pending_reviews": len(pending_reviews),
        "pending_approvals": len(pending_approvals),
        "controls": len(control_records),
        "paused_controls": len(paused_controls),
        "stopped_controls": len(stopped_controls),
        "degraded_controls": len(degraded_controls),
        "revoked_controls": len(revoked_controls),
    }

    if control_records:
        next_move = "Inspect active control-state before resuming apply, promotion, or publish work."
    elif blocked:
        next_move = "Clear blocked tasks and inspect the linked lifecycle reasons first."
    elif waiting_review:
        next_move = "Review tasks waiting on reviewer verdicts."
    elif waiting_approval:
        next_move = "Review approval-gated tasks first."
    elif impacted_outputs or revoked_artifacts:
        next_move = "Inspect impacted or revoked outputs before shipping any dependent work."
    elif ready_to_ship:
        next_move = "Ship or publish the ready-to-ship tasks with promoted artifacts."
    elif running_now:
        next_move = "Let current in-progress work continue or inspect the top active task."
    elif queued_now:
        next_move = "Start the highest-priority queued task or inspect queued work."
    else:
        next_move = "No active work is currently queued or running."

    return {
        "queued_now": queued_now,
        "running_now": running_now,
        "blocked": blocked,
        "waiting_review": waiting_review,
        "waiting_approval": waiting_approval,
        "ready_to_ship": ready_to_ship,
        "shipped": shipped,
        "finished_recently": finished_recently,
        "candidate_artifacts": candidate_artifacts,
        "impacted_artifacts": impacted_artifacts,
        "revoked_artifacts": revoked_artifacts,
        "impacted_outputs": impacted_outputs,
        "revoked_outputs": revoked_outputs,
        "control_state": {
            "effective": effective_control,
            "records": control_records,
            "paused": paused_controls,
            "stopped": stopped_controls,
            "degraded": degraded_controls,
            "revoked": revoked_controls,
        },
        "counts": counts,
        "next_recommended_move": next_move,
    }


def summarize_status(root: Path) -> dict[str, Any]:
    return build_status(root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build task status summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    result = build_status(Path(args.root).resolve())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
