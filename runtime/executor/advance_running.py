#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.task_runtime import block_task, checkpoint_task, complete_task, fail_task
from runtime.executor.running_task import pick_oldest_running_task


def main() -> int:
    parser = argparse.ArgumentParser(description="Advance one currently running task.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", help="Running task id. If omitted, uses oldest running task.")
    parser.add_argument("--actor", default="executor", help="Actor name")
    parser.add_argument("--lane", default="executor", help="Lane name")
    parser.add_argument(
        "--action",
        required=True,
        choices=["checkpoint", "complete", "fail", "block"],
        help="Advance action to apply",
    )
    parser.add_argument("--checkpoint-summary", default="", help="Checkpoint summary text")
    parser.add_argument("--final-outcome", default="", help="Final outcome text")
    parser.add_argument("--reason", default="", help="Reason text")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    task_id = args.task_id

    if not task_id:
        task = pick_oldest_running_task(root=root)
        if not task:
            print(json.dumps({"kind": "no_running_task", "message": "No running task available."}, indent=2))
            return 0
        task_id = task["task_id"]

    if args.action == "checkpoint":
        summary = args.checkpoint_summary or args.reason or "Checkpoint recorded."
        result = checkpoint_task(
            task_id=task_id,
            actor=args.actor,
            lane=args.lane,
            checkpoint_summary=summary,
            root=root,
        )
    elif args.action == "complete":
        outcome = args.final_outcome or args.reason or "Task completed by running-task helper."
        result = complete_task(
            task_id=task_id,
            actor=args.actor,
            lane=args.lane,
            final_outcome=outcome,
            root=root,
        )
    elif args.action == "fail":
        reason = args.reason or "Task failed."
        outcome = args.final_outcome or reason
        result = fail_task(
            task_id=task_id,
            actor=args.actor,
            lane=args.lane,
            reason=reason,
            final_outcome=outcome,
            root=root,
        )
    elif args.action == "block":
        reason = args.reason or "Task blocked."
        result = block_task(
            task_id=task_id,
            actor=args.actor,
            lane=args.lane,
            reason=reason,
            root=root,
        )
    else:
        raise ValueError(f"Unsupported action: {args.action}")

    print(json.dumps({"kind": "running_task_advanced", "result": result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
