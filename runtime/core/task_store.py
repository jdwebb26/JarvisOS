#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import RecordLifecycleState, TaskRecord, TaskStatus, now_iso
from runtime.core.task_events import append_event, make_event
from runtime.core.workspace_registry import ensure_home_runtime_workspace
from runtime.controls.control_store import assert_control_allows


VALID_TRANSITIONS: dict[str, set[str]] = {
    TaskStatus.QUEUED.value: {
        TaskStatus.RUNNING.value,
        TaskStatus.WAITING_REVIEW.value,
        TaskStatus.WAITING_APPROVAL.value,
        TaskStatus.BLOCKED.value,
        TaskStatus.READY_TO_SHIP.value,
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    },
    TaskStatus.RUNNING.value: {
        TaskStatus.QUEUED.value,
        TaskStatus.WAITING_REVIEW.value,
        TaskStatus.WAITING_APPROVAL.value,
        TaskStatus.BLOCKED.value,
        TaskStatus.READY_TO_SHIP.value,
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    },
    TaskStatus.WAITING_REVIEW.value: {
        TaskStatus.RUNNING.value,
        TaskStatus.WAITING_APPROVAL.value,
        TaskStatus.QUEUED.value,
        TaskStatus.BLOCKED.value,
        TaskStatus.READY_TO_SHIP.value,
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    },
    TaskStatus.WAITING_APPROVAL.value: {
        TaskStatus.RUNNING.value,
        TaskStatus.QUEUED.value,
        TaskStatus.BLOCKED.value,
        TaskStatus.READY_TO_SHIP.value,
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    },
    TaskStatus.BLOCKED.value: {
        TaskStatus.RUNNING.value,
        TaskStatus.QUEUED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    },
    TaskStatus.FAILED.value: {
        TaskStatus.RUNNING.value,
        TaskStatus.QUEUED.value,
        TaskStatus.CANCELLED.value,
    },
    TaskStatus.COMPLETED.value: {
        TaskStatus.WAITING_REVIEW.value,
        TaskStatus.WAITING_APPROVAL.value,
        TaskStatus.READY_TO_SHIP.value,
        TaskStatus.SHIPPED.value,
    },
    TaskStatus.READY_TO_SHIP.value: {
        TaskStatus.SHIPPED.value,
        TaskStatus.COMPLETED.value,
        TaskStatus.CANCELLED.value,
        TaskStatus.BLOCKED.value,
    },
      TaskStatus.SHIPPED.value: {
        TaskStatus.COMPLETED.value,
        TaskStatus.BLOCKED.value,
    }
}


def project_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def tasks_dir(root: Optional[Path] = None) -> Path:
    base = root or project_root_from_here()
    path = base / "state" / "tasks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def task_path(task_id: str, root: Optional[Path] = None) -> Path:
    return tasks_dir(root) / f"{task_id}.json"


def save_task(record: TaskRecord, root: Optional[Path] = None) -> TaskRecord:
    record.updated_at = now_iso()
    path = task_path(record.task_id, root)
    path.write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return record


def load_task(task_id: str, root: Optional[Path] = None) -> Optional[TaskRecord]:
    path = task_path(task_id, root)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return TaskRecord.from_dict(data)


def create_task(record: TaskRecord, root: Optional[Path] = None) -> TaskRecord:
    home_workspace = ensure_home_runtime_workspace(root=root)
    if not record.home_runtime_workspace:
        record.home_runtime_workspace = home_workspace.workspace_id
    if not record.target_workspace_id:
        record.target_workspace_id = record.home_runtime_workspace
    if not record.allowed_workspace_ids:
        record.allowed_workspace_ids = [record.home_runtime_workspace]
        if record.target_workspace_id != record.home_runtime_workspace:
            record.allowed_workspace_ids.append(record.target_workspace_id)
    if not record.touched_workspace_ids:
        record.touched_workspace_ids = sorted({record.home_runtime_workspace, record.target_workspace_id})
    save_task(record, root=root)
    append_event(
        make_event(
            task_id=record.task_id,
            event_type="task_created",
            actor=record.source_user,
            lane=record.source_lane,
            summary=f"Task created: {record.normalized_request}",
            from_status=None,
            to_status=record.status,
            from_lifecycle_state=None,
            to_lifecycle_state=record.lifecycle_state,
            execution_backend=record.execution_backend,
            backend_run_id=record.backend_run_id,
        ),
        root=root,
    )
    recompute_task_readiness(
        task_id=record.task_id,
        actor=record.source_user,
        lane=record.source_lane,
        root=root,
        reason="Initial task readiness and dependency blocking computed",
    )
    return record


def list_tasks(root: Optional[Path] = None, limit: int = 100) -> list[TaskRecord]:
    items: list[TaskRecord] = []
    for path in tasks_dir(root).glob("*.json"):
        if path.name.endswith(".events.jsonl"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append(TaskRecord.from_dict(data))
        except Exception:
            continue

    items.sort(key=lambda x: x.updated_at, reverse=True)
    return items[:limit]


def list_dependent_tasks(parent_task_id: str, root: Optional[Path] = None) -> list[TaskRecord]:
    return [task for task in list_tasks(root=root, limit=10000) if task.parent_task_id == parent_task_id]


def _dependency_state(record: TaskRecord, *, root: Optional[Path] = None) -> dict[str, object]:
    refs: list[str] = []
    reason = ""
    parent_status = None
    pending_approval_id = None
    parent_task = None
    if not record.parent_task_id:
        return {
            "refs": refs,
            "reason": reason,
            "hard_block": False,
            "speculative_only": False,
            "parent_task": None,
            "parent_status": None,
            "pending_approval_id": None,
        }

    parent_task = load_task(record.parent_task_id, root=root)
    if parent_task is None:
        refs.append(f"parent_missing:{record.parent_task_id}")
        reason = f"Parent task {record.parent_task_id} is missing."
        return {
            "refs": refs,
            "reason": reason,
            "hard_block": True,
            "speculative_only": False,
            "parent_task": None,
            "parent_status": None,
            "pending_approval_id": None,
        }

    parent_status = parent_task.status
    try:
        from runtime.core.approval_store import latest_approval_for_task

        pending = latest_approval_for_task(record.parent_task_id, root=root)
        if pending is not None and pending.status == "pending":
            pending_approval_id = pending.approval_id
    except Exception:
        pending_approval_id = None

    approval_wall = parent_status == TaskStatus.WAITING_APPROVAL.value or pending_approval_id is not None
    if approval_wall:
        if record.speculative_downstream:
            refs.append(f"speculative_parent_approval:{record.parent_task_id}")
            reason = (
                f"Speculative downstream task depends on parent approval for {record.parent_task_id}; "
                "candidate-only work may proceed but promotion/publish remains blocked."
            )
            return {
                "refs": refs,
                "reason": reason,
                "hard_block": False,
                "speculative_only": True,
                "parent_task": parent_task,
                "parent_status": parent_status,
                "pending_approval_id": pending_approval_id,
            }
        refs.append(f"parent_approval_blocked:{record.parent_task_id}")
        reason = f"Parent task {record.parent_task_id} is blocked on approval."
        return {
            "refs": refs,
            "reason": reason,
            "hard_block": True,
            "speculative_only": False,
            "parent_task": parent_task,
            "parent_status": parent_status,
            "pending_approval_id": pending_approval_id,
        }

    return {
        "refs": refs,
        "reason": reason,
        "hard_block": False,
        "speculative_only": False,
        "parent_task": parent_task,
        "parent_status": parent_status,
        "pending_approval_id": pending_approval_id,
    }


def task_dependency_summary(task_id: str, *, root: Optional[Path] = None) -> dict[str, object]:
    record = load_task(task_id, root=root)
    if record is None:
        raise ValueError(f"Task not found: {task_id}")
    return _dependency_state(record, root=root)


def recompute_dependent_tasks(
    parent_task_id: str,
    *,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    reason: str = "",
) -> None:
    for child in list_dependent_tasks(parent_task_id, root=root):
        recompute_task_readiness(
            task_id=child.task_id,
            actor=actor,
            lane=lane,
            root=root,
            reason=reason or f"Dependency recompute after parent task update: {parent_task_id}",
        )


def transition_task(
    task_id: str,
    to_status: str,
    actor: str,
    lane: str,
    summary: str,
    root: Optional[Path] = None,
    details: str = "",
    approval_id: Optional[str] = None,
    error: str = "",
) -> TaskRecord:
    record = load_task(task_id, root=root)
    if record is None:
        raise ValueError(f"Task not found: {task_id}")

    from_status = record.status
    allowed = VALID_TRANSITIONS.get(from_status, set())
    if to_status != from_status and to_status not in allowed:
        raise ValueError(f"Invalid transition: {from_status} -> {to_status}")

    subsystem = record.execution_backend if record.execution_backend != "unassigned" else lane
    if to_status in {
        TaskStatus.QUEUED.value,
        TaskStatus.RUNNING.value,
    }:
        assert_control_allows(
            action="task_progress",
            root=root,
            task_id=record.task_id,
            subsystem=subsystem,
            actor=actor,
            lane=lane,
        )
    elif to_status == TaskStatus.READY_TO_SHIP.value:
        assert_control_allows(
            action="ready_to_ship",
            root=root,
            task_id=record.task_id,
            subsystem=subsystem,
            actor=actor,
            lane=lane,
        )
    elif to_status == TaskStatus.SHIPPED.value:
        assert_control_allows(
            action="ship",
            root=root,
            task_id=record.task_id,
            subsystem=subsystem,
            actor=actor,
            lane=lane,
        )
    dependency_state = _dependency_state(record, root=root)
    if to_status in {
        TaskStatus.QUEUED.value,
        TaskStatus.RUNNING.value,
        TaskStatus.READY_TO_SHIP.value,
        TaskStatus.SHIPPED.value,
    }:
        if dependency_state["hard_block"]:
            recompute_task_readiness(
                task_id=record.task_id,
                actor=actor,
                lane=lane,
                root=root,
                reason=str(dependency_state["reason"]),
            )
            raise ValueError(str(dependency_state["reason"]))
        if dependency_state["speculative_only"] and to_status in {
            TaskStatus.READY_TO_SHIP.value,
            TaskStatus.SHIPPED.value,
        }:
            recompute_task_readiness(
                task_id=record.task_id,
                actor=actor,
                lane=lane,
                root=root,
                reason=str(dependency_state["reason"]),
            )
            raise ValueError(str(dependency_state["reason"]))

    record.status = to_status
    if error:
        record.error_count += 1
        record.last_error = error
    if to_status == TaskStatus.COMPLETED.value and not record.final_outcome:
        record.final_outcome = "completed"
    if to_status == TaskStatus.FAILED.value and not record.final_outcome:
        record.final_outcome = "failed"

    save_task(record, root=root)

    append_event(
        make_event(
            task_id=record.task_id,
            event_type="status_transition",
            actor=actor,
            lane=lane,
            summary=summary,
            from_status=from_status,
            to_status=to_status,
            from_lifecycle_state=record.lifecycle_state,
            to_lifecycle_state=record.lifecycle_state,
            details=details,
            approval_id=approval_id,
            execution_backend=record.execution_backend,
            backend_run_id=record.backend_run_id,
            error=error,
        ),
        root=root,
    )
    recompute_dependent_tasks(
        record.task_id,
        actor=actor,
        lane=lane,
        root=root,
        reason=f"Parent task status changed to {record.status}",
    )

    return record


def add_artifact_link(task_id: str, artifact_id: str, root: Optional[Path] = None) -> TaskRecord:
    record = load_task(task_id, root=root)
    if record is None:
        raise ValueError(f"Task not found: {task_id}")

    if artifact_id not in record.related_artifact_ids:
        record.related_artifact_ids.append(artifact_id)
        save_task(record, root=root)

    return record


def add_review_link(task_id: str, review_id: str, root: Optional[Path] = None) -> TaskRecord:
    record = load_task(task_id, root=root)
    if record is None:
        raise ValueError(f"Task not found: {task_id}")

    if review_id not in record.related_review_ids:
        record.related_review_ids.append(review_id)
        save_task(record, root=root)

    return record


def add_approval_link(task_id: str, approval_id: str, root: Optional[Path] = None) -> TaskRecord:
    record = load_task(task_id, root=root)
    if record is None:
        raise ValueError(f"Task not found: {task_id}")

    if approval_id not in record.related_approval_ids:
        record.related_approval_ids.append(approval_id)
        save_task(record, root=root)

    return record


def add_checkpoint(task_id: str, checkpoint_summary: str, root: Optional[Path] = None) -> TaskRecord:
    record = load_task(task_id, root=root)
    if record is None:
        raise ValueError(f"Task not found: {task_id}")

    record.checkpoint_summary = checkpoint_summary
    save_task(record, root=root)

    append_event(
        make_event(
            task_id=record.task_id,
            event_type="checkpoint",
            actor="system",
            lane=record.source_lane,
            summary="Checkpoint updated",
            from_status=record.status,
            to_status=record.status,
            from_lifecycle_state=record.lifecycle_state,
            to_lifecycle_state=record.lifecycle_state,
            details=checkpoint_summary,
            execution_backend=record.execution_backend,
            backend_run_id=record.backend_run_id,
        ),
        root=root,
    )
    return record


def set_task_lifecycle_state(
    task_id: str,
    lifecycle_state: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    *,
    artifact_id: Optional[str] = None,
    artifact_type: Optional[str] = None,
    artifact_title: Optional[str] = None,
    execution_backend: Optional[str] = None,
    backend_run_id: Optional[str] = None,
    reason: str = "",
) -> TaskRecord:
    record = load_task(task_id, root=root)
    if record is None:
        raise ValueError(f"Task not found: {task_id}")

    previous_state = record.lifecycle_state
    if artifact_id:
        if artifact_id not in record.related_artifact_ids:
            record.related_artifact_ids.append(artifact_id)
        if lifecycle_state == RecordLifecycleState.CANDIDATE.value:
            if artifact_id not in record.candidate_artifact_ids:
                record.candidate_artifact_ids.append(artifact_id)
            if artifact_id in record.demoted_artifact_ids:
                record.demoted_artifact_ids.remove(artifact_id)
        elif lifecycle_state == RecordLifecycleState.PROMOTED.value:
            record.promoted_artifact_id = artifact_id
            record.candidate_artifact_ids = [item for item in record.candidate_artifact_ids if item != artifact_id]
            record.demoted_artifact_ids = [item for item in record.demoted_artifact_ids if item != artifact_id]
        elif lifecycle_state in {
            RecordLifecycleState.DEMOTED.value,
            RecordLifecycleState.SUPERSEDED.value,
            RecordLifecycleState.ARCHIVED.value,
        }:
            record.candidate_artifact_ids = [item for item in record.candidate_artifact_ids if item != artifact_id]
            if artifact_id not in record.demoted_artifact_ids:
                record.demoted_artifact_ids.append(artifact_id)
            if record.promoted_artifact_id == artifact_id:
                record.promoted_artifact_id = None

    if execution_backend:
        record.execution_backend = execution_backend
    if backend_run_id:
        record.backend_run_id = backend_run_id

    record.lifecycle_state = lifecycle_state
    save_task(record, root=root)

    append_event(
        make_event(
            task_id=record.task_id,
            event_type="task_lifecycle_changed",
            actor=actor,
            lane=lane,
            summary=reason or f"Task lifecycle updated: {previous_state} -> {lifecycle_state}",
            from_status=record.status,
            to_status=record.status,
            from_lifecycle_state=previous_state,
            to_lifecycle_state=lifecycle_state,
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            artifact_title=artifact_title,
            execution_backend=record.execution_backend,
            backend_run_id=record.backend_run_id,
            details=reason,
        ),
        root=root,
    )
    recompute_task_readiness(
        task_id=record.task_id,
        actor=actor,
        lane=lane,
        root=root,
        reason=reason or f"Lifecycle recompute after {lifecycle_state}",
    )
    return record


def mark_task_artifact_revoked(
    task_id: str,
    artifact_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    *,
    reason: str = "",
    impacted_output_ids: Optional[list[str]] = None,
) -> TaskRecord:
    record = load_task(task_id, root=root)
    if record is None:
        raise ValueError(f"Task not found: {task_id}")

    previous_state = record.lifecycle_state
    if artifact_id not in record.revoked_artifact_ids:
        record.revoked_artifact_ids.append(artifact_id)
    if artifact_id not in record.demoted_artifact_ids:
        record.demoted_artifact_ids.append(artifact_id)
    record.candidate_artifact_ids = [item for item in record.candidate_artifact_ids if item != artifact_id]
    if record.promoted_artifact_id == artifact_id:
        record.promoted_artifact_id = None
    for output_id in impacted_output_ids or []:
        if output_id not in record.impacted_output_ids:
            record.impacted_output_ids.append(output_id)
    record.lifecycle_state = RecordLifecycleState.DEMOTED.value
    save_task(record, root=root)

    append_event(
        make_event(
            task_id=record.task_id,
            event_type="task_artifact_revoked",
            actor=actor,
            lane=lane,
            summary=reason or f"Artifact revoked for task: {artifact_id}",
            from_status=record.status,
            to_status=record.status,
            from_lifecycle_state=previous_state,
            to_lifecycle_state=record.lifecycle_state,
            artifact_id=artifact_id,
            execution_backend=record.execution_backend,
            backend_run_id=record.backend_run_id,
            details=reason,
        ),
        root=root,
    )
    recompute_task_readiness(
        task_id=record.task_id,
        actor=actor,
        lane=lane,
        root=root,
        reason=reason or f"Artifact revoked: {artifact_id}",
    )
    return record


def mark_task_output_impacts(
    task_id: str,
    output_ids: list[str],
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    *,
    reason: str = "",
) -> TaskRecord:
    record = load_task(task_id, root=root)
    if record is None:
        raise ValueError(f"Task not found: {task_id}")

    for output_id in output_ids:
        if output_id not in record.impacted_output_ids:
            record.impacted_output_ids.append(output_id)
    save_task(record, root=root)

    append_event(
        make_event(
            task_id=record.task_id,
            event_type="task_outputs_impacted",
            actor=actor,
            lane=lane,
            summary=reason or f"Impacted outputs recorded for task: {record.task_id}",
            from_status=record.status,
            to_status=record.status,
            from_lifecycle_state=record.lifecycle_state,
            to_lifecycle_state=record.lifecycle_state,
            execution_backend=record.execution_backend,
            backend_run_id=record.backend_run_id,
            details=",".join(output_ids),
        ),
        root=root,
    )
    recompute_task_readiness(
        task_id=record.task_id,
        actor=actor,
        lane=lane,
        root=root,
        reason=reason or "Output impacts changed",
    )
    return record


def recompute_task_readiness(
    task_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    *,
    reason: str = "",
) -> TaskRecord:
    record = load_task(task_id, root=root)
    if record is None:
        raise ValueError(f"Task not found: {task_id}")

    previous_status = record.status
    previous_readiness_status = record.publish_readiness_status
    previous_readiness_reason = record.publish_readiness_reason
    previous_blocked_refs = list(record.blocked_dependency_refs)
    previous_dependency_reason = record.dependency_block_reason

    blocked_refs: list[str] = []
    dependency_state = _dependency_state(record, root=root)
    blocked_refs.extend(str(item) for item in dependency_state["refs"])
    blocked_refs.extend(f"artifact:{artifact_id}" for artifact_id in record.revoked_artifact_ids)
    blocked_refs.extend(f"output:{output_id}" for output_id in record.impacted_output_ids)
    if record.promoted_artifact_id is None and record.demoted_artifact_ids:
        blocked_refs.extend(f"demoted:{artifact_id}" for artifact_id in record.demoted_artifact_ids)
    seen: set[str] = set()
    record.blocked_dependency_refs = [item for item in blocked_refs if not (item in seen or seen.add(item))]

    readiness_status = "pending"
    readiness_reason = ""
    published_output_exists = False
    if record.promoted_artifact_id:
        try:
            from runtime.core.output_store import find_existing_output

            published_output_exists = (
                find_existing_output(task_id=record.task_id, artifact_id=record.promoted_artifact_id, root=Path(root or project_root_from_here()))
                is not None
            )
        except Exception:
            published_output_exists = False

    has_demoted_dependency = bool(record.demoted_artifact_ids) and record.promoted_artifact_id is None
    dependency_reason = str(dependency_state["reason"])

    if dependency_state["hard_block"]:
        readiness_status = "blocked_dependency"
        readiness_reason = dependency_reason
    elif dependency_state["speculative_only"] and record.promoted_artifact_id:
        readiness_status = "blocked_dependency"
        readiness_reason = dependency_reason
    elif record.impacted_output_ids or record.revoked_artifact_ids or has_demoted_dependency:
        readiness_status = "invalidated"
        if record.impacted_output_ids or record.revoked_artifact_ids:
            readiness_reason = "Downstream impacts or revoked artifacts require recomputation before publish."
        else:
            readiness_reason = "Demoted or superseded promoted artifacts require recomputation before publish."
    elif published_output_exists:
        readiness_status = "published"
        readiness_reason = "Promoted artifact already has a published output record."
    elif record.promoted_artifact_id and (record.final_outcome or "").strip() == "candidate_ready_for_live_apply":
        readiness_status = "ready"
        readiness_reason = "Promoted artifact is present and final outcome is candidate-ready."
    elif record.promoted_artifact_id:
        readiness_status = "promoted_candidate"
        readiness_reason = "Promoted artifact exists but final outcome is not candidate-ready."
    elif record.candidate_artifact_ids:
        readiness_status = "candidate_only"
        readiness_reason = (
            dependency_reason
            if dependency_state["speculative_only"]
            else "Task has candidate artifacts but no promoted artifact."
        )
    else:
        readiness_status = "pending"
        readiness_reason = dependency_reason or "No promoted artifact is currently available."

    if readiness_status in {"invalidated", "blocked_dependency"} and previous_status not in {
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
        TaskStatus.ARCHIVED.value,
    }:
        record.status = TaskStatus.BLOCKED.value
        if not record.last_error:
            record.last_error = readiness_reason
        if not record.checkpoint_summary:
            record.checkpoint_summary = readiness_reason
    if readiness_status in {"invalidated", "blocked_dependency"} and record.final_outcome == "candidate_ready_for_live_apply":
        record.final_outcome = "candidate_invalidated"

    record.publish_readiness_status = readiness_status
    record.publish_readiness_reason = readiness_reason
    record.dependency_block_reason = dependency_reason
    save_task(record, root=root)

    if (
        previous_status != record.status
        or previous_readiness_status != readiness_status
        or previous_readiness_reason != readiness_reason
        or previous_blocked_refs != record.blocked_dependency_refs
        or previous_dependency_reason != record.dependency_block_reason
    ):
        append_event(
            make_event(
                task_id=record.task_id,
                event_type="task_readiness_recomputed",
                actor=actor,
                lane=lane,
                summary=reason or f"Task readiness recomputed: {readiness_status}",
                from_status=previous_status,
                to_status=record.status,
                from_lifecycle_state=record.lifecycle_state,
                to_lifecycle_state=record.lifecycle_state,
                execution_backend=record.execution_backend,
                backend_run_id=record.backend_run_id,
                details=json.dumps(
                    {
                        "publish_readiness_status": readiness_status,
                        "publish_readiness_reason": readiness_reason,
                        "blocked_dependency_refs": record.blocked_dependency_refs,
                        "dependency_block_reason": record.dependency_block_reason,
                    },
                    sort_keys=True,
                ),
            ),
            root=root,
        )
    return record
