#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import TaskEventRecord, TaskRecord, TaskStatus, new_id, now_iso
from runtime.controls.control_store import assert_control_allows


def _tasks_dir(root: Path) -> Path:
    return root / "state" / "tasks"


def _events_dir(root: Path) -> Path:
    return root / "state" / "events"


def _task_path(root: Path, task_id: str) -> Path:
    return _tasks_dir(root) / f"{task_id}.json"


def _event_path(root: Path, event_id: str) -> Path:
    return _events_dir(root) / f"{event_id}.json"


def load_task(root: Path, task_id: str) -> TaskRecord:
    path = _task_path(root, task_id)
    if not path.exists():
        raise ValueError(f"Task not found: {task_id}")
    return TaskRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_task(root: Path, task: TaskRecord) -> TaskRecord:
    _tasks_dir(root).mkdir(parents=True, exist_ok=True)
    task.updated_at = now_iso()
    _task_path(root, task.task_id).write_text(
        json.dumps(task.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return task


def append_event(root: Path, event: TaskEventRecord) -> TaskEventRecord:
    _events_dir(root).mkdir(parents=True, exist_ok=True)
    _event_path(root, event.event_id).write_text(
        json.dumps(event.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return event

def append_task_event(root: Path, event: TaskEventRecord) -> TaskEventRecord:
    return append_event(root, event)

def set_task_status(
    *,
    root: Path,
    task_id: str,
    new_status: str,
    actor: str,
    lane: str,
    reason: str = "",
    final_outcome: str = "",
) -> dict:
    task = load_task(root, task_id)
    previous_status = task.status
    subsystem = task.execution_backend if task.execution_backend != "unassigned" else lane

    if new_status in {TaskStatus.QUEUED.value, TaskStatus.RUNNING.value}:
        assert_control_allows(
            action="task_progress",
            root=root,
            task_id=task_id,
            subsystem=subsystem,
        )
    elif new_status == TaskStatus.READY_TO_SHIP.value:
        assert_control_allows(
            action="ready_to_ship",
            root=root,
            task_id=task_id,
            subsystem=subsystem,
        )
    elif new_status == TaskStatus.SHIPPED.value:
        assert_control_allows(
            action="ship",
            root=root,
            task_id=task_id,
            subsystem=subsystem,
        )

    if previous_status == new_status:
        return {
            "task_id": task.task_id,
            "previous_status": previous_status,
            "status": task.status,
            "reason": reason,
            "final_outcome": task.final_outcome,
            "event_id": None,
            "already_in_status": True,
        }

    task.status = new_status
    if new_status == TaskStatus.COMPLETED.value:
        task.checkpoint_summary = "Task completed."
        if final_outcome:
            task.final_outcome = final_outcome
    elif new_status == TaskStatus.FAILED.value:
        task.error_count = int(task.error_count or 0) + 1
        if reason:
            task.last_error = reason

    save_task(root, task)

    event = TaskEventRecord(
        event_id=new_id("evt"),
        task_id=task.task_id,
        event_type="task_status_changed",
        actor=actor,
        lane=lane,
        created_at=now_iso(),
        from_status=previous_status,
        to_status=new_status,
        from_lifecycle_state=task.lifecycle_state,
        to_lifecycle_state=task.lifecycle_state,
        reason=reason or None,
        final_outcome=final_outcome or (task.final_outcome or None),
    )
    append_event(root, event)

    return {
        "task_id": task.task_id,
        "previous_status": previous_status,
        "status": task.status,
        "reason": reason,
        "final_outcome": task.final_outcome,
        "event_id": event.event_id,
    }


def record_checkpoint(
    *,
    root: Path,
    task_id: str,
    actor: str,
    lane: str,
    checkpoint_summary: str,
) -> dict:
    task = load_task(root, task_id)
    task.checkpoint_summary = checkpoint_summary
    save_task(root, task)

    event = TaskEventRecord(
        event_id=new_id("evt"),
        task_id=task.task_id,
        event_type="checkpoint_recorded",
        actor=actor,
        lane=lane,
        created_at=now_iso(),
        from_lifecycle_state=task.lifecycle_state,
        to_lifecycle_state=task.lifecycle_state,
        checkpoint_summary=checkpoint_summary,
    )
    append_event(root, event)

    return {
        "task_id": task.task_id,
        "status": task.status,
        "checkpoint_summary": checkpoint_summary,
        "event_id": event.event_id,
    }


def start_task(*, root: Path, task_id: str, actor: str, lane: str, reason: str) -> dict:
    return set_task_status(
        root=root,
        task_id=task_id,
        new_status=TaskStatus.RUNNING.value,
        actor=actor,
        lane=lane,
        reason=reason,
    )


def block_task(*, root: Path, task_id: str, actor: str, lane: str, reason: str) -> dict:
    return set_task_status(
        root=root,
        task_id=task_id,
        new_status=TaskStatus.BLOCKED.value,
        actor=actor,
        lane=lane,
        reason=reason,
    )


def complete_task(
    *,
    root: Path,
    task_id: str,
    actor: str,
    lane: str,
    final_outcome: str,
) -> dict:
    return set_task_status(
        root=root,
        task_id=task_id,
        new_status=TaskStatus.COMPLETED.value,
        actor=actor,
        lane=lane,
        reason="Task completed.",
        final_outcome=final_outcome,
    )


def fail_task(*, root: Path, task_id: str, actor: str, lane: str, reason: str) -> dict:
    return set_task_status(
        root=root,
        task_id=task_id,
        new_status=TaskStatus.FAILED.value,
        actor=actor,
        lane=lane,
        reason=reason,
    )


def ready_to_ship_task(
    *,
    root: Path,
    task_id: str,
    actor: str,
    lane: str,
    reason: str,
) -> dict:
    from runtime.core.artifact_store import select_task_artifact
    task = load_task(root, task_id)
    artifact = select_task_artifact(
        task_id=task_id,
        root=root,
        preferred_artifact_ids=[task.promoted_artifact_id] if task.promoted_artifact_id else None,
        allowed_states={ "promoted" },
    )
    if artifact is None:
        raise ValueError(f"Task {task_id} has no promoted artifact and cannot move to ready_to_ship.")
    return set_task_status(
        root=root,
        task_id=task_id,
        new_status=TaskStatus.READY_TO_SHIP.value,
        actor=actor,
        lane=lane,
        reason=reason,
    )


def ship_task(
    *,
    root: Path,
    task_id: str,
    actor: str,
    lane: str,
    final_outcome: str,
) -> dict:
    task = load_task(root, task_id)
    from runtime.core.artifact_store import select_task_artifact

    artifact = select_task_artifact(
        task_id=task_id,
        root=root,
        preferred_artifact_ids=[task.promoted_artifact_id] if task.promoted_artifact_id else None,
        allowed_states={"promoted"},
    )
    if artifact is None:
        raise ValueError(f"Task {task_id} has no promoted artifact and cannot be shipped.")

    if task.review_required:
        from runtime.core.review_store import latest_review_for_task

        latest_review = latest_review_for_task(task_id, root=root)
        if latest_review is None or latest_review.status != "approved":
            raise ValueError(f"Task {task_id} requires an approved review before shipping.")

    if task.approval_required:
        from runtime.core.approval_store import latest_approval_for_task

        latest_approval = latest_approval_for_task(task_id, root=root)
        if latest_approval is None or latest_approval.status != "approved":
            raise ValueError(f"Task {task_id} requires an approved approval before shipping.")

    if task.status not in {
        TaskStatus.READY_TO_SHIP.value,
        TaskStatus.COMPLETED.value,
    }:
        raise ValueError(
            f"Task {task_id} must be ready_to_ship or completed before shipping; current status is {task.status}"
        )

    return set_task_status(
        root=root,
        task_id=task_id,
        new_status=TaskStatus.SHIPPED.value,
        actor=actor,
        lane=lane,
        reason="Task shipped.",
        final_outcome=final_outcome,
    )
def checkpoint_task(
    *,
    root: Path,
    task_id: str,
    actor: str,
    lane: str,
    checkpoint_summary: str,
) -> dict:
    return record_checkpoint(
        root=root,
        task_id=task_id,
        actor=actor,
        lane=lane,
        checkpoint_summary=checkpoint_summary,
    )
