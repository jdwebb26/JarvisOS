#!/usr/bin/env python3
"""Gateway wrapper for a bounded NVIDIA executor invocation.

Usage:
    python3 runtime/gateway/nvidia_execute.py --task-id <id>
    python3 runtime/gateway/nvidia_execute.py --task-id <id> --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.task_runtime import load_task, complete_task, fail_task, checkpoint_task
from runtime.executor.backend_dispatch import dispatch_to_backend


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway wrapper for a bounded NVIDIA executor invocation.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="kitt", help="Lane name")
    parser.add_argument("--message", default="", help="Override message content (default: use task normalized_request)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be dispatched without calling the API")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    try:
        task = load_task(root, args.task_id)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1

    execution_backend = task.execution_backend or ""
    if execution_backend != "nvidia_executor":
        print(json.dumps({
            "ok": False,
            "error": f"Task {args.task_id} has execution_backend='{execution_backend}', expected 'nvidia_executor'.",
        }, indent=2))
        return 1

    message_content = args.message.strip() or task.normalized_request or ""
    if not message_content:
        print(json.dumps({"ok": False, "error": "No message content available for dispatch."}, indent=2))
        return 1

    routing_meta = (task.backend_metadata or {}).get("routing") or {}

    if args.dry_run:
        print(json.dumps({
            "ok": True,
            "dry_run": True,
            "task_id": task.task_id,
            "execution_backend": execution_backend,
            "routing_decision_id": routing_meta.get("routing_decision_id"),
            "message_preview": message_content[:200],
            "model": routing_meta.get("model_name", "moonshotai/kimi-k2.5"),
            "provider": routing_meta.get("provider_id", "nvidia"),
        }, indent=2))
        return 0

    checkpoint_task(
        root=root,
        task_id=task.task_id,
        actor=args.actor,
        lane=args.lane,
        checkpoint_summary=f"Dispatching to nvidia_executor via gateway.",
    )

    result = dispatch_to_backend(
        task_id=task.task_id,
        actor=args.actor,
        lane=args.lane,
        execution_backend="nvidia_executor",
        messages=[{"role": "user", "content": message_content}],
        routing_decision_id=routing_meta.get("routing_decision_id"),
        root=root,
    )

    if result.get("status") == "completed":
        complete_task(
            root=root,
            task_id=task.task_id,
            actor=args.actor,
            lane=args.lane,
            final_outcome=f"nvidia_executor completed: {result.get('content', '')[:200]}",
        )

    print(json.dumps({"ok": True, "dispatch_result": result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
