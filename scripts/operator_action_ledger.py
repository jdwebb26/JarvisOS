#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def operator_action_executions_dir(root: Path) -> Path:
    path = root / "state" / "operator_action_executions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_execution_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_action_executions_dir(root) / f"{record['execution_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def load_execution_record(root: Path, execution_id: str) -> Optional[dict[str, Any]]:
    path = operator_action_executions_dir(root) / f"{execution_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _sort_recent(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (str(row.get("completed_at", "")), str(row.get("started_at", ""))),
        reverse=True,
    )


def list_operator_action_executions(
    root: Path,
    *,
    task_id: str | None = None,
    category: str | None = None,
    success: bool | None = None,
    dry_run: bool | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in operator_action_executions_dir(root).glob("*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        selected_action = row.get("selected_action") or {}
        if task_id and selected_action.get("task_id") != task_id:
            continue
        if category and selected_action.get("category") != category:
            continue
        if success is not None and bool(row.get("success", False)) != success:
            continue
        if dry_run is not None and bool(row.get("dry_run", False)) != dry_run:
            continue
        rows.append(row)
    return _sort_recent(rows)


def latest_action_for_task(root: Path, task_id: str) -> Optional[dict[str, Any]]:
    rows = list_operator_action_executions(root, task_id=task_id)
    return rows[0] if rows else None


def latest_successful_action_for_task(root: Path, task_id: str) -> Optional[dict[str, Any]]:
    rows = list_operator_action_executions(root, task_id=task_id, success=True)
    return rows[0] if rows else None


def latest_failed_action_for_task(root: Path, task_id: str) -> Optional[dict[str, Any]]:
    rows = list_operator_action_executions(root, task_id=task_id, success=False)
    return rows[0] if rows else None


def latest_action_by_category(root: Path, category: str) -> Optional[dict[str, Any]]:
    rows = list_operator_action_executions(root, category=category)
    return rows[0] if rows else None
