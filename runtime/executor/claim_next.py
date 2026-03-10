#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.task_queue import list_running_tasks, pick_next_queued_task
from runtime.core.task_runtime import checkpoint_task, start_task


def main() -> int:
    parser = argparse.ArgumentParser(description="Claim the next queued task without completing it.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--actor", default="executor", help="Actor name")
    parser.add_argument("--lane", default="executor", help="Lane name")
    parser.add_argument("--allow-parallel", action="store_true", help="Allow claiming new work even if a task is already running")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    running = list_running_tasks(root=root)

    if running and not args.allow_parallel:
        print(
            json.dumps(
                {
                    "kind": "running_task_present",
                    "message": "Executor did not claim new queued work because a task is already running.",
                    "running_tasks": running,
                },
                indent=2,
            )
        )
        return 0

    task = pick_next_queued_task(root=root)
    if not task:
        print(json.dumps({"kind": "no_task", "message": "No queued task available."}, indent=2))
        return 0

    start_result = start_task(
        task_id=task["task_id"],
        actor=args.actor,
        lane=args.lane,
        reason="Executor claimed queued task.",
        root=root,
    )

    checkpoint_result = checkpoint_task(
        task_id=task["task_id"],
        actor=args.actor,
        lane=args.lane,
        checkpoint_summary=f"Executor claimed task: {task['summary']}",
        root=root,
    )

    print(
        json.dumps(
            {
                "kind": "task_claimed",
                "picked_task": task,
                "start_result": start_result,
                "checkpoint_result": checkpoint_result,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
