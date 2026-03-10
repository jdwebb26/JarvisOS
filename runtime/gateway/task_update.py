#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.task_runtime import (
    block_task,
    complete_task,
    fail_task,
    ready_to_ship_task,
    record_checkpoint,
    ship_task,
    start_task,
)


def build_ack(action: str, result: dict) -> dict:
    task_id = result["task_id"]
    status = result.get("status", "")

    if action == "checkpoint":
        return {
            "kind": "task_update_ack",
            "reply": f"Checkpoint recorded for task `{task_id}`.",
            "task_id": task_id,
            "status": status,
        }

    return {
        "kind": "task_update_ack",
        "reply": f"Task `{task_id}` is now `{status}`.",
        "task_id": task_id,
        "status": status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Update task lifecycle state.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task ID")
    parser.add_argument(
        "--action",
        required=True,
        choices=["start", "checkpoint", "block", "complete", "fail", "ready", "ship"],
        help="Lifecycle action",
    )
    parser.add_argument("--actor", required=True, help="Actor name")
    parser.add_argument("--lane", required=True, help="Lane name")
    parser.add_argument("--reason", default="", help="Reason for status change")
    parser.add_argument("--checkpoint-summary", default="", help="Checkpoint summary")
    parser.add_argument("--final-outcome", default="", help="Final outcome text")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    if args.action == "start":
        result = start_task(
            root=root,
            task_id=args.task_id,
            actor=args.actor,
            lane=args.lane,
            reason=args.reason or "Task started.",
        )
    elif args.action == "checkpoint":
        if not args.checkpoint_summary:
            raise ValueError("--checkpoint-summary is required for checkpoint action")
        result = record_checkpoint(
            root=root,
            task_id=args.task_id,
            actor=args.actor,
            lane=args.lane,
            checkpoint_summary=args.checkpoint_summary,
        )
    elif args.action == "block":
        result = block_task(
            root=root,
            task_id=args.task_id,
            actor=args.actor,
            lane=args.lane,
            reason=args.reason or "Task blocked.",
        )
    elif args.action == "complete":
        result = complete_task(
            root=root,
            task_id=args.task_id,
            actor=args.actor,
            lane=args.lane,
            final_outcome=args.final_outcome,
        )
    elif args.action == "fail":
        result = fail_task(
            root=root,
            task_id=args.task_id,
            actor=args.actor,
            lane=args.lane,
            reason=args.reason or "Task failed.",
        )
    elif args.action == "ready":
        result = ready_to_ship_task(
            root=root,
            task_id=args.task_id,
            actor=args.actor,
            lane=args.lane,
            reason=args.reason or "Task is ready to ship.",
        )
    else:
        result = ship_task(
            root=root,
            task_id=args.task_id,
            actor=args.actor,
            lane=args.lane,
            final_outcome=args.final_outcome,
        )

    payload = {
        "result": result,
        "ack": build_ack(args.action, result),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
