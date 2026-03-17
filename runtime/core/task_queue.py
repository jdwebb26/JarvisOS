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

from runtime.core.task_store import list_tasks


PRIORITY_RANK = {
    "critical": 0,
    "high": 1,
    "normal": 2,
    "low": 3,
}


def priority_rank(value: str) -> int:
    return PRIORITY_RANK.get(value, 99)


def _task_row(task) -> dict:
    return {
        "task_id": task.task_id,
        "summary": task.normalized_request,
        "normalized_request": task.normalized_request,
        "task_type": task.task_type,
        "priority": task.priority,
        "risk_level": task.risk_level,
        "assigned_model": task.assigned_model,
        "execution_backend": getattr(task, "execution_backend", ""),
        "backend_metadata": getattr(task, "backend_metadata", None) or {},
        "status": task.status,
        "updated_at": task.updated_at,
        "created_at": task.created_at,
    }


def list_queued_tasks(*, root: Path) -> list[dict]:
    tasks = list_tasks(root=root, limit=1000)
    queued = [_task_row(task) for task in tasks if task.status == "queued"]
    queued.sort(key=lambda row: (priority_rank(row["priority"]), row["updated_at"]))
    return queued


def list_running_tasks(*, root: Path) -> list[dict]:
    tasks = list_tasks(root=root, limit=1000)
    running = [_task_row(task) for task in tasks if task.status == "running"]
    running.sort(key=lambda row: row["updated_at"])
    return running


def pick_next_queued_task(*, root: Path) -> Optional[dict]:
    queued = list_queued_tasks(root=root)
    return queued[0] if queued else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect queued and running task lists.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--pick", action="store_true", help="Return only the next queued task")
    parser.add_argument("--running", action="store_true", help="Return running tasks only")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    if args.pick:
        result = pick_next_queued_task(root=root)
    elif args.running:
        result = {"running": list_running_tasks(root=root)}
    else:
        result = {
            "queued": list_queued_tasks(root=root),
            "running": list_running_tasks(root=root),
        }

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
