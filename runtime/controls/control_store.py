#!/usr/bin/env python3
from __future__ import annotations

import json
import argparse
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import (
    ControlAction,
    ControlActionRecord,
    ControlBlockedActionRecord,
    ControlEventRecord,
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
    "task_create": "task creation",
    "route_selection": "routing selection",
    "task_progress": "task progress",
    "browser_action": "browser action",
    "desktop_action": "desktop action",
    "voice_command": "voice command",
    "approval_decision": "approval decision",
    "approval_resume": "approval resume",
    "promote_artifact": "artifact promotion",
    "promote_memory": "memory promotion",
    "memory_write": "memory write",
    "ready_to_ship": "ready-to-ship transition",
    "ship": "ship transition",
    "publish_output": "output publish",
    "rollback_execute": "rollback execution",
    "recovery_execute": "recovery execution",
}


def controls_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "controls"
    path.mkdir(parents=True, exist_ok=True)
    return path


def control_actions_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "control_actions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def control_events_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "control_events"
    path.mkdir(parents=True, exist_ok=True)
    return path


def blocked_actions_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "control_blocked_actions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_scope_key(scope_id: str) -> str:
    return scope_id.replace("/", "__")


def control_path(*, scope_type: str, scope_id: str, root: Optional[Path] = None) -> Path:
    filename = f"{scope_type}__{_safe_scope_key(scope_id)}.json"
    return controls_dir(root) / filename


def control_action_path(action_id: str, *, root: Optional[Path] = None) -> Path:
    return control_actions_dir(root) / f"{action_id}.json"


def control_event_path(control_event_id: str, *, root: Optional[Path] = None) -> Path:
    return control_events_dir(root) / f"{control_event_id}.json"


def blocked_action_path(blocked_action_id: str, *, root: Optional[Path] = None) -> Path:
    return blocked_actions_dir(root) / f"{blocked_action_id}.json"


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


def save_control_event(record: ControlEventRecord, *, root: Optional[Path] = None) -> ControlEventRecord:
    control_event_path(record.control_event_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def save_blocked_action(record: ControlBlockedActionRecord, *, root: Optional[Path] = None) -> ControlBlockedActionRecord:
    blocked_action_path(record.blocked_action_id, root=root).write_text(
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


def list_control_events(*, root: Optional[Path] = None) -> list[ControlEventRecord]:
    items: list[ControlEventRecord] = []
    for path in control_events_dir(root).glob("*.json"):
        try:
            items.append(ControlEventRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    items.sort(key=lambda item: item.created_at, reverse=True)
    return items


def list_blocked_actions(*, root: Optional[Path] = None) -> list[ControlBlockedActionRecord]:
    items: list[ControlBlockedActionRecord] = []
    for path in blocked_actions_dir(root).glob("*.json"):
        try:
            items.append(ControlBlockedActionRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    items.sort(key=lambda item: item.created_at, reverse=True)
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


def set_emergency_control(
    *,
    control_kind: str,
    enabled: bool,
    actor: str,
    lane: str,
    scope_type: str = ControlScopeType.GLOBAL.value,
    scope_id: str = "global",
    reason: str = "",
    target_provider_id: Optional[str] = None,
    target_execution_backend: Optional[str] = None,
    metadata: Optional[dict] = None,
    root: Optional[Path] = None,
) -> ControlRecord:
    record = get_control_record(scope_type=scope_type, scope_id=scope_id, root=root)

    if control_kind == "execution_freeze":
        record.execution_freeze = enabled
    elif control_kind == "promotion_freeze":
        record.promotion_freeze = enabled
    elif control_kind == "approval_freeze":
        record.approval_freeze = enabled
    elif control_kind == "memory_freeze":
        record.memory_freeze = enabled
    elif control_kind == "recovery_only_mode":
        record.recovery_only_mode = enabled
    elif control_kind == "operator_only_mode":
        record.operator_only_mode = enabled
    elif control_kind == "provider_disable":
        provider_id = (target_provider_id or "").strip()
        if not provider_id:
            raise ValueError("provider_disable requires target_provider_id.")
        disabled = set(record.disabled_provider_ids)
        if enabled:
            disabled.add(provider_id)
        else:
            disabled.discard(provider_id)
        record.disabled_provider_ids = sorted(disabled)
    elif control_kind == "execution_backend_disable":
        execution_backend = (target_execution_backend or "").strip()
        if not execution_backend:
            raise ValueError("execution_backend_disable requires target_execution_backend.")
        disabled = set(record.disabled_execution_backends)
        if enabled:
            disabled.add(execution_backend)
        else:
            disabled.discard(execution_backend)
        record.disabled_execution_backends = sorted(disabled)
    else:
        raise ValueError(f"Unsupported emergency control kind: {control_kind}")

    record.last_action = f"{'enable' if enabled else 'disable'}:{control_kind}"
    record.last_actor = actor
    record.lane = lane
    record.reason = reason
    if metadata:
        record.metadata = dict(metadata)

    control_event = save_control_event(
        ControlEventRecord(
            control_event_id=new_id("ctlev"),
            control_id=record.control_id,
            scope_type=scope_type,
            scope_id=scope_id,
            created_at=now_iso(),
            actor=actor,
            lane=lane,
            control_kind=control_kind,
            enabled=enabled,
            reason=reason,
            target_provider_id=target_provider_id,
            target_execution_backend=target_execution_backend,
            metadata=dict(metadata or {}),
        ),
        root=root,
    )
    record.latest_control_event_id = control_event.control_event_id
    save_control(record, root=root)
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
    emergency_flags = {
        "execution_freeze": False,
        "promotion_freeze": False,
        "approval_freeze": False,
        "memory_freeze": False,
        "recovery_only_mode": False,
        "operator_only_mode": False,
    }
    disabled_provider_ids: set[str] = set()
    disabled_execution_backends: set[str] = set()

    for record in records:
        if RUN_STATE_SEVERITY[record.run_state] > RUN_STATE_SEVERITY[effective_run_state]:
            effective_run_state = record.run_state
        if SAFETY_MODE_SEVERITY[record.safety_mode] > SAFETY_MODE_SEVERITY[effective_safety_mode]:
            effective_safety_mode = record.safety_mode
        for key in emergency_flags:
            emergency_flags[key] = emergency_flags[key] or bool(getattr(record, key, False))
        disabled_provider_ids.update(getattr(record, "disabled_provider_ids", []) or [])
        disabled_execution_backends.update(getattr(record, "disabled_execution_backends", []) or [])

    reasons = []
    for record in records:
        if (
            record.run_state == ControlRunState.ACTIVE.value
            and record.safety_mode == ControlSafetyMode.NORMAL.value
            and not any(
                bool(getattr(record, key, False))
                for key in emergency_flags
            )
            and not getattr(record, "disabled_provider_ids", [])
            and not getattr(record, "disabled_execution_backends", [])
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
        "has_active_controls": bool(reasons) or any(emergency_flags.values()) or bool(disabled_provider_ids) or bool(disabled_execution_backends),
        "emergency_flags": emergency_flags,
        "disabled_provider_ids": sorted(disabled_provider_ids),
        "disabled_execution_backends": sorted(disabled_execution_backends),
    }


def build_control_summary(*, root: Optional[Path] = None) -> dict:
    state = get_effective_control_state(root=root)
    records = list_control_records(root=root)
    events = list_control_events(root=root)
    blocked = list_blocked_actions(root=root)
    return {
        "effective": state,
        "control_count": len(records),
        "control_event_count": len(events),
        "blocked_action_count": len(blocked),
        "latest_control_record": records[0].to_dict() if records else None,
        "latest_control_event": events[0].to_dict() if events else None,
        "latest_blocked_action": blocked[0].to_dict() if blocked else None,
    }


def _actor_is_operator(actor: Optional[str], lane: Optional[str]) -> bool:
    actor_label = (actor or "").lower()
    lane_label = (lane or "").lower()
    return actor_label in {"operator", "tester", "anton", "archimedes"} or lane_label in {
        "review",
        "approval",
        "memory",
        "controls",
        "operator",
    }


def control_blocks_action(
    *,
    action: str,
    root: Optional[Path] = None,
    task_id: Optional[str] = None,
    subsystem: Optional[str] = None,
    provider_id: Optional[str] = None,
    actor: Optional[str] = None,
    lane: Optional[str] = None,
) -> tuple[bool, str, dict]:
    state = get_effective_control_state(root=root, task_id=task_id, subsystem=subsystem)
    run_state = state["effective_run_state"]
    safety_mode = state["effective_safety_mode"]
    emergency_flags = state.get("emergency_flags", {})

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
    elif action in {"task_create", "route_selection", "approval_decision", "promote_memory", "memory_write", "browser_action", "desktop_action", "voice_command"}:
        blocked = (
            run_state == ControlRunState.STOPPED.value
            or safety_mode in {ControlSafetyMode.DEGRADED.value, ControlSafetyMode.REVOKED.value}
        )
    elif action in {"rollback_execute", "recovery_execute"}:
        blocked = False
    else:
        raise ValueError(f"Unsupported control check action: {action}")

    if action in {"task_create", "route_selection", "task_progress", "approval_resume", "approval_decision", "promote_artifact", "promote_memory", "memory_write", "ready_to_ship", "ship", "publish_output", "browser_action", "desktop_action", "voice_command"}:
        if emergency_flags.get("execution_freeze"):
            blocked = True
        if emergency_flags.get("recovery_only_mode") and action not in {"rollback_execute", "recovery_execute"}:
            blocked = True

    if action in {"promote_artifact", "ready_to_ship", "ship", "publish_output"} and emergency_flags.get("promotion_freeze"):
        blocked = True
    if action in {"approval_resume", "approval_decision"} and emergency_flags.get("approval_freeze"):
        blocked = True
    if action in {"promote_memory", "memory_write"} and emergency_flags.get("memory_freeze"):
        blocked = True
    if emergency_flags.get("operator_only_mode") and action not in {"rollback_execute", "recovery_execute"} and not _actor_is_operator(actor, lane):
        blocked = True
    if provider_id and provider_id in state.get("disabled_provider_ids", []):
        blocked = True
    if subsystem and subsystem in state.get("disabled_execution_backends", []):
        blocked = True

    if not blocked:
        return False, "", state

    label = ACTION_LABELS.get(action, action.replace("_", " "))
    reasons = "; ".join(state["active_reasons"]) or state["effective_status"]
    if emergency_flags.get("execution_freeze"):
        reasons = f"{reasons}; execution_freeze".strip("; ")
    if emergency_flags.get("promotion_freeze") and action in {"promote_artifact", "ready_to_ship", "ship", "publish_output"}:
        reasons = f"{reasons}; promotion_freeze".strip("; ")
    if emergency_flags.get("approval_freeze") and action in {"approval_resume", "approval_decision"}:
        reasons = f"{reasons}; approval_freeze".strip("; ")
    if emergency_flags.get("memory_freeze") and action in {"promote_memory", "memory_write"}:
        reasons = f"{reasons}; memory_freeze".strip("; ")
    if emergency_flags.get("recovery_only_mode") and action not in {"rollback_execute", "recovery_execute"}:
        reasons = f"{reasons}; recovery_only_mode".strip("; ")
    if emergency_flags.get("operator_only_mode") and not _actor_is_operator(actor, lane):
        reasons = f"{reasons}; operator_only_mode".strip("; ")
    if provider_id and provider_id in state.get("disabled_provider_ids", []):
        reasons = f"{reasons}; provider_disabled:{provider_id}".strip("; ")
    if subsystem and subsystem in state.get("disabled_execution_backends", []):
        reasons = f"{reasons}; execution_backend_disabled:{subsystem}".strip("; ")
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
    provider_id: Optional[str] = None,
    actor: Optional[str] = None,
    lane: Optional[str] = None,
) -> dict:
    blocked, message, state = control_blocks_action(
        action=action,
        root=root,
        task_id=task_id,
        subsystem=subsystem,
        provider_id=provider_id,
        actor=actor,
        lane=lane,
    )
    if blocked:
        save_blocked_action(
            ControlBlockedActionRecord(
                blocked_action_id=new_id("ctlblk"),
                created_at=now_iso(),
                action=action,
                task_id=task_id,
                subsystem=subsystem,
                provider_id=provider_id,
                actor=actor or "system",
                lane=lane or "controls",
                effective_status=state.get("effective_status", ControlRunState.ACTIVE.value),
                reason=message,
                control_scope_refs=[
                    f"{row.get('scope_type')}:{row.get('scope_id')}"
                    for row in state.get("records", [])
                ],
                metadata={
                    "effective_run_state": state.get("effective_run_state"),
                    "effective_safety_mode": state.get("effective_safety_mode"),
                    "emergency_flags": dict(state.get("emergency_flags", {})),
                    "disabled_provider_ids": list(state.get("disabled_provider_ids", [])),
                    "disabled_execution_backends": list(state.get("disabled_execution_backends", [])),
                },
            ),
            root=root,
        )
        raise ValueError(message)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current emergency control summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_control_summary(root=Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
