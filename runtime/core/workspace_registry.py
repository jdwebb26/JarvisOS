#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import TaskRecord, WorkspaceRecord, now_iso

HOME_WORKSPACE_ID = "jarvis_v5_runtime"
READ_ONLY_OPERATIONS = {"read", "inspect", "list"}


def workspaces_dir(root: Optional[Path] = None) -> Path:
    base = Path(root or ROOT).resolve()
    path = base / "state" / "workspaces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_path(workspace_id: str, *, root: Optional[Path] = None) -> Path:
    return workspaces_dir(root=root) / f"{workspace_id}.json"


def save_workspace(record: WorkspaceRecord, *, root: Optional[Path] = None) -> WorkspaceRecord:
    record.updated_at = now_iso()
    workspace_path(record.workspace_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def ensure_home_runtime_workspace(*, root: Optional[Path] = None) -> WorkspaceRecord:
    existing = get_workspace(HOME_WORKSPACE_ID, root=root)
    if existing is not None:
        return existing
    root_path = Path(root or ROOT).resolve()
    return save_workspace(
        WorkspaceRecord(
            workspace_id=HOME_WORKSPACE_ID,
            label="Jarvis v5 Runtime Home",
            absolute_path=str(root_path),
            role="home_runtime",
            purpose="central_runtime_control_truth",
            access_mode="home",
            allowed_operations=["read", "write", "artifact_write", "publish_output"],
            sensitivity="high",
            default_read_only=False,
            tags=["home", "runtime", "authoritative"],
            owner="jarvis",
            runtime_notes="Central runtime/control truth remains in jarvis-v5.",
            approved_agents=["jarvis"],
            approved_lanes=["jarvis", "scout", "tests"],
            operator_approved=True,
            enabled=True,
        ),
        root=root_path,
    )


def register_workspace(
    *,
    workspace_id: str,
    label: str,
    absolute_path: str,
    role: str = "registered",
    purpose: str,
    access_mode: str = "scoped",
    allowed_operations: list[str],
    sensitivity: str,
    default_read_only: bool,
    tags: list[str] | None = None,
    owner: Optional[str] = None,
    runtime_notes: str = "",
    approved_agents: list[str] | None = None,
    approved_lanes: list[str] | None = None,
    operator_approved: bool = False,
    enabled: bool = True,
    root: Optional[Path] = None,
) -> WorkspaceRecord:
    ensure_home_runtime_workspace(root=root)
    record = WorkspaceRecord(
        workspace_id=workspace_id,
        label=label,
        absolute_path=str(Path(absolute_path).expanduser().resolve()),
        role=role,
        purpose=purpose,
        access_mode=access_mode,
        allowed_operations=sorted({str(item) for item in allowed_operations if str(item).strip()}),
        sensitivity=sensitivity,
        default_read_only=default_read_only,
        tags=sorted({str(item) for item in (tags or []) if str(item).strip()}),
        owner=owner,
        runtime_notes=runtime_notes,
        approved_agents=sorted({str(item) for item in (approved_agents or []) if str(item).strip()}),
        approved_lanes=sorted({str(item) for item in (approved_lanes or []) if str(item).strip()}),
        operator_approved=bool(operator_approved),
        enabled=bool(enabled),
    )
    return save_workspace(record, root=root)


def update_workspace(
    workspace_id: str,
    *,
    root: Optional[Path] = None,
    **updates: Any,
) -> WorkspaceRecord:
    record = get_workspace(workspace_id, root=root)
    if record is None:
        raise ValueError(f"Workspace not found: {workspace_id}")
    mutable = record.to_dict()
    for key, value in updates.items():
        if key == "absolute_path" and value is not None:
            mutable[key] = str(Path(value).expanduser().resolve())
        elif key in {"allowed_operations", "tags", "approved_agents", "approved_lanes"} and value is not None:
            mutable[key] = sorted({str(item) for item in value if str(item).strip()})
        elif value is not None:
            mutable[key] = value
    return save_workspace(WorkspaceRecord.from_dict(mutable), root=root)


def grant_workspace_access(
    workspace_id: str,
    *,
    agent_id: Optional[str] = None,
    lane: Optional[str] = None,
    operator_approved: bool = True,
    enabled: Optional[bool] = None,
    root: Optional[Path] = None,
) -> WorkspaceRecord:
    record = get_workspace(workspace_id, root=root)
    if record is None:
        raise ValueError(f"Workspace not found: {workspace_id}")
    approved_agents = set(record.approved_agents or [])
    approved_lanes = set(record.approved_lanes or [])
    if agent_id:
        approved_agents.add(str(agent_id))
    if lane:
        approved_lanes.add(str(lane))
    return update_workspace(
        workspace_id,
        root=root,
        approved_agents=sorted(approved_agents),
        approved_lanes=sorted(approved_lanes),
        operator_approved=bool(operator_approved),
        enabled=record.enabled if enabled is None else bool(enabled),
    )


def revoke_workspace_access(
    workspace_id: str,
    *,
    agent_id: Optional[str] = None,
    lane: Optional[str] = None,
    root: Optional[Path] = None,
) -> WorkspaceRecord:
    record = get_workspace(workspace_id, root=root)
    if record is None:
        raise ValueError(f"Workspace not found: {workspace_id}")
    approved_agents = set(record.approved_agents or [])
    approved_lanes = set(record.approved_lanes or [])
    if agent_id:
        approved_agents.discard(str(agent_id))
    if lane:
        approved_lanes.discard(str(lane))
    return update_workspace(
        workspace_id,
        root=root,
        approved_agents=sorted(approved_agents),
        approved_lanes=sorted(approved_lanes),
    )


def list_workspaces(*, root: Optional[Path] = None) -> list[WorkspaceRecord]:
    ensure_home_runtime_workspace(root=root)
    rows: list[WorkspaceRecord] = []
    for path in sorted(workspaces_dir(root=root).glob("*.json")):
        try:
            rows.append(WorkspaceRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: (row.workspace_id != HOME_WORKSPACE_ID, row.label.lower(), row.workspace_id))
    return rows


def get_workspace(workspace_id: str, *, root: Optional[Path] = None) -> Optional[WorkspaceRecord]:
    path = workspace_path(workspace_id, root=root)
    if not path.exists():
        return None
    try:
        return WorkspaceRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def resolve_workspace_for_task(
    task: TaskRecord | dict[str, Any],
    *,
    root: Optional[Path] = None,
    requested_workspace_id: Optional[str] = None,
    operation: str = "read",
    agent_id: Optional[str] = None,
    lane: Optional[str] = None,
) -> WorkspaceRecord:
    ensure_home_runtime_workspace(root=root)
    payload = task.to_dict() if isinstance(task, TaskRecord) else dict(task)
    home_workspace_id = str(payload.get("home_runtime_workspace") or HOME_WORKSPACE_ID)
    target_workspace_id = str(
        requested_workspace_id
        or payload.get("target_workspace_id")
        or home_workspace_id
    )
    allowed_workspace_ids = list(payload.get("allowed_workspace_ids") or [home_workspace_id, target_workspace_id])
    if target_workspace_id not in allowed_workspace_ids:
        raise ValueError(f"Workspace `{target_workspace_id}` is outside this task's allowed workspace scope.")
    record = get_workspace(target_workspace_id, root=root)
    if record is None:
        raise ValueError(f"Workspace not found: {target_workspace_id}")
    if not record.enabled:
        raise ValueError(f"Workspace `{target_workspace_id}` is disabled.")
    if target_workspace_id != HOME_WORKSPACE_ID:
        effective_lane = str(lane or payload.get("source_lane") or "").strip()
        effective_agent = str(agent_id or payload.get("source_user") or "").strip()
        if not record.operator_approved:
            raise ValueError(f"Workspace `{target_workspace_id}` is not operator-approved.")
        lane_allowed = effective_lane and effective_lane in set(record.approved_lanes or [])
        agent_allowed = effective_agent and effective_agent in set(record.approved_agents or [])
        if not lane_allowed and not agent_allowed:
            raise ValueError(
                f"Workspace `{target_workspace_id}` is not approved for lane `{effective_lane or 'unknown'}` or agent `{effective_agent or 'unknown'}`."
            )
    if operation and operation not in set(record.allowed_operations):
        raise ValueError(f"Workspace `{target_workspace_id}` does not allow operation `{operation}`.")
    if record.default_read_only and operation not in READ_ONLY_OPERATIONS:
        raise ValueError(f"Workspace `{target_workspace_id}` is read-only for operation `{operation}`.")
    return record


def summarize_workspace_registry(
    *,
    root: Optional[Path] = None,
    tasks: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = [row.to_dict() for row in list_workspaces(root=root)]
    home = next((row for row in rows if row["workspace_id"] == HOME_WORKSPACE_ID), None)

    def _recent_scope(items: list[dict[str, Any]], key: str, label_key: str) -> list[dict[str, Any]]:
        scoped: list[dict[str, Any]] = []
        for row in items[:10]:
            touched = list(row.get("touched_workspace_ids") or [])
            if not touched and not row.get("target_workspace_id"):
                continue
            scoped.append(
                {
                    key: row.get(key),
                    label_key: row.get(label_key),
                    "home_runtime_workspace": row.get("home_runtime_workspace"),
                    "target_workspace_id": row.get("target_workspace_id"),
                    "allowed_workspace_ids": list(row.get("allowed_workspace_ids") or []),
                    "touched_workspace_ids": touched,
                }
            )
        return scoped

    task_rows = sorted(list(tasks or []), key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    artifact_rows = sorted(list(artifacts or []), key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    output_rows = sorted(list(outputs or []), key=lambda row: str(row.get("published_at") or ""), reverse=True)

    return {
        "workspace_count": len(rows),
        "default_home_workspace_id": home.get("workspace_id") if home else HOME_WORKSPACE_ID,
        "default_home_workspace": home,
        "registered_workspaces": rows[:20],
        "operator_approved_workspace_count": sum(1 for row in rows if row.get("operator_approved")),
        "enabled_workspace_count": sum(1 for row in rows if row.get("enabled")),
        "workspace_access_mode_counts": {
            key: sum(1 for row in rows if row.get("access_mode") == key)
            for key in sorted({str(row.get("access_mode") or "scoped") for row in rows})
        },
        "read_only_workspace_count": sum(1 for row in rows if row.get("default_read_only")),
        "writable_workspace_count": sum(1 for row in rows if not row.get("default_read_only")),
        "recent_task_workspace_rows": _recent_scope(task_rows, "task_id", "summary"),
        "recent_artifact_workspace_rows": _recent_scope(artifact_rows, "artifact_id", "title"),
        "recent_output_workspace_rows": _recent_scope(output_rows, "output_id", "title"),
    }
