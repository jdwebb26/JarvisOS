#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import (
    ControlAction,
    ControlActionRecord,
    ControlRecord,
    ControlRunState,
    ControlSafetyMode,
    ControlScopeType,
    new_id,
    now_iso,
)


RUN_STATE_SEVERITY = {
    ControlRunState.ACTIVE.value: 0,
    ControlRunState.PAUSED.value: 1,
    ControlRunState.STOPPED.value: 2,
}

SAFETY_MODE_SEVERITY = {
    ControlSafetyMode.NORMAL.value: 0,
    ControlSafetyMode.DEGRADED.value: 1,
    ControlSafetyMode.REVOKED.value: 2,
}

ACTION_LABELS = {
    "task_progress": "task progress",
    "approval_resume": "approval resume",
    "promote_artifact": "artifact promotion",
    "ready_to_ship": "ready-to-ship transition",
    "ship": "ship transition",
    "publish_output": "output publish",
}


def controls_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "controls"
    path.mkdir(parents=True, exist_ok=True)
    return path


def control_actions_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "control_actions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_scope_key(scope_id: str) -> str:
    return scope_id.replace("/", "__")


def control_path(*, scope_type: str, scope_id: str, root: Optional[Path] = None) -> Path:
    filename = f"{scope_type}__{_safe_scope_key(scope_id)}.json"
    return controls_dir(root) / filename


def control_action_path(action_id: str, *, root: Optional[Path] = None) -> Path:
    return control_actions_dir(root) / f"{action_id}.json"


def save_control(record: ControlRecord, *, root: Optional[Path] = None) -> ControlRecord:
    record.updated_at = now_iso()
    control_path(scope_type=record.scope_type, scope_id=record.scope_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_control(*, scope_type: str, scope_id: str, root: Optional[Path] = None) -> Optional[ControlRecord]:
    path = control_path(scope_type=scope_type, scope_id=scope_id, root=root)
    if not path.exists():
        return None
    return ControlRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_control_action(record: ControlActionRecord, *, root: Optional[Path] = None) -> ControlActionRecord:
    control_action_path(record.action_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def list_control_records(*, root: Optional[Path] = None) -> list[ControlRecord]:
    items: list[ControlRecord] = []
    for path in controls_dir(root).glob("*.json"):
        try:
            items.append(ControlRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    items.sort(key=lambda item: item.updated_at, reverse=True)
    return items


def get_control_record(
    *,
    scope_type: str,
    scope_id: str,
    root: Optional[Path] = None,
) -> ControlRecord:
    existing = load_control(scope_type=scope_type, scope_id=scope_id, root=root)
    if existing is not None:
        return existing
    return ControlRecord(
        control_id=new_id("ctl"),
        scope_type=scope_type,
        scope_id=scope_id,
        created_at=now_iso(),
        updated_at=now_iso(),
    )


def apply_control_action(
    *,
    action: str,
    actor: str,
    lane: str,
    scope_type: str = ControlScopeType.GLOBAL.value,
    scope_id: str = "global",
    reason: str = "",
    metadata: Optional[dict] = None,
    root: Optional[Path] = None,
) -> ControlRecord:
    record = get_control_record(scope_type=scope_type, scope_id=scope_id, root=root)
    previous_run_state = record.run_state
    previous_safety_mode = record.safety_mode

    if action == ControlAction.PAUSE.value:
        record.run_state = ControlRunState.PAUSED.value
    elif action == ControlAction.RESUME.value:
        record.run_state = ControlRunState.ACTIVE.value
        record.safety_mode = ControlSafetyMode.NORMAL.value
    elif action == ControlAction.STOP.value:
        record.run_state = ControlRunState.STOPPED.value
    elif action == ControlAction.REVOKE.value:
        record.safety_mode = ControlSafetyMode.REVOKED.value
    elif action == ControlAction.DEGRADE.value:
        record.safety_mode = ControlSafetyMode.DEGRADED.value
    else:
        raise ValueError(f"Unsupported control action: {action}")

    record.last_action = action
    record.last_actor = actor
    record.lane = lane
    record.reason = reason
    if metadata:
        record.metadata = dict(metadata)
    save_control(record, root=root)

    action_record = ControlActionRecord(
        action_id=new_id("ctlact"),
        control_id=record.control_id,
        scope_type=scope_type,
        scope_id=scope_id,
        action=action,
        actor=actor,
        lane=lane,
        created_at=now_iso(),
        reason=reason,
        previous_run_state=previous_run_state,
        previous_safety_mode=previous_safety_mode,
        new_run_state=record.run_state,
        new_safety_mode=record.safety_mode,
        metadata=dict(metadata or {}),
    )
    save_control_action(action_record, root=root)
    return record


def _effective_status(run_state: str, safety_mode: str) -> str:
    if run_state == ControlRunState.STOPPED.value:
        return ControlRunState.STOPPED.value
    if run_state == ControlRunState.PAUSED.value:
        return ControlRunState.PAUSED.value
    if safety_mode == ControlSafetyMode.REVOKED.value:
        return ControlSafetyMode.REVOKED.value
    if safety_mode == ControlSafetyMode.DEGRADED.value:
        return ControlSafetyMode.DEGRADED.value
    return ControlRunState.ACTIVE.value


def get_effective_control_state(
    *,
    root: Optional[Path] = None,
    task_id: Optional[str] = None,
    subsystem: Optional[str] = None,
) -> dict:
    records: list[ControlRecord] = []

    global_record = load_control(
        scope_type=ControlScopeType.GLOBAL.value,
        scope_id="global",
        root=root,
    )
    if global_record is not None:
        records.append(global_record)

    if subsystem:
        subsystem_record = load_control(
            scope_type=ControlScopeType.SUBSYSTEM.value,
            scope_id=subsystem,
            root=root,
        )
        if subsystem_record is not None:
            records.append(subsystem_record)

    if task_id:
        task_record = load_control(
            scope_type=ControlScopeType.TASK.value,
            scope_id=task_id,
            root=root,
        )
        if task_record is not None:
            records.append(task_record)

    effective_run_state = ControlRunState.ACTIVE.value
    effective_safety_mode = ControlSafetyMode.NORMAL.value

    for record in records:
        if RUN_STATE_SEVERITY[record.run_state] > RUN_STATE_SEVERITY[effective_run_state]:
            effective_run_state = record.run_state
        if SAFETY_MODE_SEVERITY[record.safety_mode] > SAFETY_MODE_SEVERITY[effective_safety_mode]:
            effective_safety_mode = record.safety_mode

    reasons = []
    for record in records:
        if (
            record.run_state == ControlRunState.ACTIVE.value
            and record.safety_mode == ControlSafetyMode.NORMAL.value
        ):
            continue
        label = f"{record.scope_type}:{record.scope_id}"
        detail = record.reason or record.last_action
        reasons.append(f"{label}={record.run_state}/{record.safety_mode}: {detail}".strip())

    return {
        "effective_status": _effective_status(effective_run_state, effective_safety_mode),
        "effective_run_state": effective_run_state,
        "effective_safety_mode": effective_safety_mode,
        "records": [record.to_dict() for record in records],
        "active_reasons": reasons,
        "has_active_controls": bool(reasons),
    }


def control_blocks_action(
    *,
    action: str,
    root: Optional[Path] = None,
    task_id: Optional[str] = None,
    subsystem: Optional[str] = None,
) -> tuple[bool, str, dict]:
    state = get_effective_control_state(root=root, task_id=task_id, subsystem=subsystem)
    run_state = state["effective_run_state"]
    safety_mode = state["effective_safety_mode"]

    blocked = False
    if action in {"task_progress"}:
        blocked = (
            run_state in {ControlRunState.PAUSED.value, ControlRunState.STOPPED.value}
            or safety_mode == ControlSafetyMode.REVOKED.value
        )
    elif action in {"approval_resume", "promote_artifact", "ready_to_ship", "ship", "publish_output"}:
        blocked = (
            run_state != ControlRunState.ACTIVE.value
            or safety_mode in {ControlSafetyMode.DEGRADED.value, ControlSafetyMode.REVOKED.value}
        )
    else:
        raise ValueError(f"Unsupported control check action: {action}")

    if not blocked:
        return False, "", state

    label = ACTION_LABELS.get(action, action.replace("_", " "))
    reasons = "; ".join(state["active_reasons"]) or state["effective_status"]
    message = (
        f"Control state forbids {label}: "
        f"run_state={run_state}, safety_mode={safety_mode}. {reasons}"
    )
    return True, message, state


def assert_control_allows(
    *,
    action: str,
    root: Optional[Path] = None,
    task_id: Optional[str] = None,
    subsystem: Optional[str] = None,
) -> dict:
    blocked, message, state = control_blocks_action(
        action=action,
        root=root,
        task_id=task_id,
        subsystem=subsystem,
    )
    if blocked:
        raise ValueError(message)
    return state
