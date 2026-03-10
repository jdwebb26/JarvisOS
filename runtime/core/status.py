#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import TaskRecord, TaskStatus


def _load_tasks(root: Path) -> list[TaskRecord]:
    folder = root / "state" / "tasks"
    rows: list[TaskRecord] = []
    if not folder.exists():
        return rows

    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(TaskRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return rows


def _sort_key(task: TaskRecord) -> tuple[str, str]:
    created_at = getattr(task, "created_at", "") or ""
    updated_at = getattr(task, "updated_at", "") or ""
    return (updated_at, created_at)


def _task_summary(task: TaskRecord) -> dict:
    return {
        "task_id": task.task_id,
        "summary": task.normalized_request,
        "status": task.status,
        "priority": task.priority,
    }


def build_status(root: Path) -> dict:
    tasks = _load_tasks(root)
    tasks_sorted = sorted(tasks, key=_sort_key, reverse=True)

    queued_now = [_task_summary(t) for t in tasks_sorted if t.status == TaskStatus.QUEUED.value]
    running_now = [_task_summary(t) for t in tasks_sorted if t.status == TaskStatus.RUNNING.value]
    blocked = [_task_summary(t) for t in tasks_sorted if t.status == TaskStatus.BLOCKED.value]
    waiting_approval = [
        _task_summary(t) for t in tasks_sorted if t.status == TaskStatus.WAITING_APPROVAL.value
    ]
    waiting_review = [
        _task_summary(t) for t in tasks_sorted if t.status == TaskStatus.WAITING_REVIEW.value
    ]
    finished_recently = [
        _task_summary(t)
        for t in tasks_sorted
        if t.status in {
            TaskStatus.COMPLETED.value,
            TaskStatus.SHIPPED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
            TaskStatus.ARCHIVED.value,
        }
    ][:10]

    counts = {
        "total_tasks": len(tasks_sorted),
        "queued": len(queued_now),
        "running": len(running_now),
        "blocked": len(blocked),
        "waiting_approval": len(waiting_approval),
        "waiting_review": len(waiting_review),
        "finished_recently": len(finished_recently),
    }

    if waiting_review:
        next_move = "Review tasks waiting on reviewer verdicts."
    elif waiting_approval:
        next_move = "Review approval-gated tasks first."
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
        "waiting_approval": waiting_approval,
        "waiting_review": waiting_review,
        "finished_recently": finished_recently,
        "counts": counts,
        "next_recommended_move": next_move,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build task status summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    result = build_status(Path(args.root).resolve())
    print(json.dumps(result, indent=2))
    return 0
    
def summarize_status(root: Path) -> dict:
    return build_status(root)

if __name__ == "__main__":
    raise SystemExit(main())
