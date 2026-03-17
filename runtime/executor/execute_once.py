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

from runtime.core.task_queue import list_running_tasks, pick_next_queued_task, pick_queued_task_by_id
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


def _write_browser_result_artifact(
    *,
    task_id: str,
    dispatch_result: dict,
    actor: str,
    lane: str,
    root: Path,
) -> Optional[dict]:
    """Write a promoted text artifact from a successful browser_backend result.

    Returns the artifact record dict on success, or None if writing fails
    (non-fatal — the task still completes).
    """
    try:
        from runtime.core.artifact_store import write_text_artifact

        br = dispatch_result.get("browser_action_result") or {}
        br_result = br.get("result") or {}
        br_request = br.get("request") or {}

        outcome_summary = br_result.get("outcome_summary") or dispatch_result.get("content", "")
        action_type = br_request.get("action_type", "browse")
        target_url = br_request.get("target_url", "")
        result_id = br_result.get("result_id", "")

        # Build human-readable content that is easy to inspect
        content_parts = [
            f"action_type: {action_type}",
            f"target_url:  {target_url}",
            f"status:      {br_result.get('status', 'unknown')}",
            "",
            "outcome_summary:",
            outcome_summary,
        ]
        error = br_result.get("error")
        if error:
            content_parts += ["", f"error: {error}"]

        # Include snapshot nodes preview if present in the trace
        trace_steps = (br.get("trace") or {}).get("steps") or []
        for step in trace_steps:
            if step.get("step") == "backend_execute" and step.get("outcome_summary"):
                break

        return write_text_artifact(
            task_id=task_id,
            artifact_type="browser_result",
            title=f"Browser {action_type}: {target_url}",
            summary=outcome_summary[:400],
            content="\n".join(content_parts),
            actor=actor,
            lane=lane,
            producer_kind="backend",
            lifecycle_state="promoted",
            execution_backend="browser_backend",
            backend_run_id=result_id or None,
            root=root,
        )
    except Exception:
        return None


def execute_once(
    *,
    root: Path,
    actor: str,
    lane: str,
    allow_parallel: bool,
    task_id: Optional[str] = None,
) -> dict:
    """Run one executor pass.

    If task_id is given, target that specific queued task (bypasses queue
    ordering — useful for direct browser invocations and proofs).
    """
    running = list_running_tasks(root=root)

    if running and not allow_parallel:
        return {
            "kind": "running_task_present",
            "message": "Executor did not claim new queued work because a task is already running.",
            "running_tasks": running,
        }

    if task_id:
        task = pick_queued_task_by_id(task_id, root=root)
        if not task:
            return {
                "kind": "task_not_found_or_not_queued",
                "task_id": task_id,
                "message": f"Task {task_id!r} is not queued (may not exist, may already be running/completed).",
            }
    else:
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
    # adapter (e.g. browser_backend, nvidia_executor), dispatch to it directly.
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

        artifact_result: Optional[dict] = None

        if dispatch_result.get("status") == "completed":
            # For browser_backend: extract the full outcome and write an artifact
            # so the result is inspectable without digging through raw state.
            content = dispatch_result.get("content", "")
            if execution_backend == "browser_backend":
                artifact_result = _write_browser_result_artifact(
                    task_id=task["task_id"],
                    dispatch_result=dispatch_result,
                    actor=actor,
                    lane=lane,
                    root=root,
                )
                br_result = (dispatch_result.get("browser_action_result") or {}).get("result") or {}
                outcome_summary = br_result.get("outcome_summary") or content
                final_outcome = f"Browser result: {outcome_summary}"
                if artifact_result:
                    final_outcome += f" [artifact: {artifact_result['artifact_id']}]"
            else:
                final_outcome = f"Backend {execution_backend} completed: {content[:200]}"

            finish_result = complete_task(
                task_id=task["task_id"],
                actor=actor,
                lane=lane,
                final_outcome=final_outcome,
                root=root,
            )
            if artifact_result:
                finish_result["artifact_id"] = artifact_result["artifact_id"]
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
            "artifact_result": artifact_result,
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
    parser.add_argument("--task-id", default="", help="Target a specific queued task by id (bypasses queue ordering)")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    try:
        result = execute_once(
            root=root,
            actor=args.actor,
            lane=args.lane,
            allow_parallel=args.allow_parallel,
            task_id=args.task_id or None,
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
