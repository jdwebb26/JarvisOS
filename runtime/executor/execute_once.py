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
from runtime.core.task_runtime import checkpoint_task, complete_task, fail_task, start_task
from runtime.executor.backend_dispatch import dispatch_to_backend, has_backend_adapter


AUTO_COMPLETE_TYPES = {"general", "docs"}
CLAIM_ONLY_TYPES = {"code", "deploy", "quant"}


def _decide_executor_action(task: dict) -> tuple[str, str]:
    task_type = task.get("task_type", "general")
    summary = task.get("summary", "")
    risk_level = task.get("risk_level", "normal")

    if task_type in CLAIM_ONLY_TYPES:
        return (
            "checkpoint_only",
            f"Executor claimed {task_type} task for bounded/manual handling: {summary}",
        )

    if risk_level == "high_stakes":
        return (
            "checkpoint_only",
            f"Executor claimed high-stakes task for bounded/manual handling: {summary}",
        )

    if task_type in AUTO_COMPLETE_TYPES:
        return (
            "completed",
            f"Executor completed {task_type} task: {summary}",
        )

    return (
        "checkpoint_only",
        f"Executor claimed task for manual/model-specific handling: {summary}",
    )


def execute_once(*, root: Path, actor: str, lane: str, allow_parallel: bool) -> dict:
    running = list_running_tasks(root=root)

    if running and not allow_parallel:
        return {
            "kind": "running_task_present",
            "message": "Executor did not claim new queued work because a task is already running.",
            "running_tasks": running,
        }

    task = pick_next_queued_task(root=root)
    if not task:
        return {
            "kind": "no_task",
            "message": "No queued task available.",
        }

    start_result = start_task(
        task_id=task["task_id"],
        actor=actor,
        lane=lane,
        reason="Executor claimed queued task.",
        root=root,
    )

    checkpoint_result = checkpoint_task(
        task_id=task["task_id"],
        actor=actor,
        lane=lane,
        checkpoint_summary=f"Executor started work on: {task['summary']}",
        root=root,
    )

    # --- Backend-aware dispatch: if the task's execution_backend has a wired
    # adapter (e.g. nvidia_executor), dispatch to it directly instead of
    # falling through to the generic type-based decision logic.
    execution_backend = task.get("execution_backend", "")
    if execution_backend and has_backend_adapter(execution_backend):
        routing_meta = (task.get("backend_metadata") or {}).get("routing") or {}
        dispatch_result = dispatch_to_backend(
            task_id=task["task_id"],
            actor=actor,
            lane=lane,
            execution_backend=execution_backend,
            messages=[{"role": "user", "content": task.get("normalized_request", "")}],
            routing_decision_id=routing_meta.get("routing_decision_id"),
            root=root,
        )
        if dispatch_result.get("status") == "completed":
            finish_result = complete_task(
                task_id=task["task_id"],
                actor=actor,
                lane=lane,
                final_outcome=f"Backend {execution_backend} completed: {dispatch_result.get('content', '')[:200]}",
                root=root,
            )
        else:
            error_msg = dispatch_result.get("error", "Unknown backend error")
            finish_result = fail_task(
                task_id=task["task_id"],
                actor=actor,
                lane=lane,
                reason=f"Backend {execution_backend} failed: {error_msg}",
                root=root,
            )
        return {
            "kind": "backend_dispatch",
            "picked_task": task,
            "start_result": start_result,
            "checkpoint_result": checkpoint_result,
            "dispatch_result": dispatch_result,
            "finish_result": finish_result,
        }

    # --- Generic type-based decision for tasks without a wired backend adapter.
    action, message = _decide_executor_action(task)

    if action == "completed":
        finish_result = complete_task(
            task_id=task["task_id"],
            actor=actor,
            lane=lane,
            final_outcome=message,
            root=root,
        )
    elif action == "failed":
        finish_result = fail_task(
            task_id=task["task_id"],
            actor=actor,
            lane=lane,
            reason=message,
            final_outcome=message,
            root=root,
        )
    else:
        finish_result = {
            "task_id": task["task_id"],
            "status": "running",
            "final_outcome": "",
            "message": message,
        }

    return {
        "kind": "executor_run",
        "picked_task": task,
        "start_result": start_result,
        "checkpoint_result": checkpoint_result,
        "finish_result": finish_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded executor pass.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--actor", default="executor", help="Actor name")
    parser.add_argument("--lane", default="executor", help="Lane name")
    parser.add_argument("--allow-parallel", action="store_true", help="Allow claiming new work even if a task is already running")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    try:
        result = execute_once(
            root=root,
            actor=args.actor,
            lane=args.lane,
            allow_parallel=args.allow_parallel,
        )
    except Exception as exc:
        result = {
            "kind": "executor_error",
            "error": str(exc),
        }

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
