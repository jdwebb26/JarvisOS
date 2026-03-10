#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.task_store import list_tasks


ACTIVE_STATUSES = {
    "queued",
    "running",
    "blocked",
    "waiting_review",
    "waiting_approval",
}


def normalize_request(text: str) -> str:
    return " ".join(text.strip().lower().split())


def find_active_duplicate_task(*, normalized_request: str, root: Path) -> Optional[dict]:
    target = normalize_request(normalized_request)
    tasks = list_tasks(root=root, limit=1000)

    matches = []
    for task in tasks:
        if task.status not in ACTIVE_STATUSES:
            continue
        if normalize_request(task.normalized_request) != target:
            continue

        matches.append(
            {
                "task_id": task.task_id,
                "summary": task.normalized_request,
                "status": task.status,
                "priority": task.priority,
                "task_type": task.task_type,
                "risk_level": task.risk_level,
                "assigned_model": task.assigned_model,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            }
        )

    if not matches:
        return None

    matches.sort(key=lambda row: row["created_at"])
    return matches[0]
