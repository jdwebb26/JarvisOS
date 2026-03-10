#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.publish_complete import publish_and_complete
from runtime.core.task_runtime import complete_task


def _load_task(task_id: str, *, root: Path) -> dict:
    path = root / "state" / "tasks" / f"{task_id}.json"
    if not path.exists():
        raise ValueError(f"Task not found: {task_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def complete_once(
    *,
    task_id: str,
    actor: str,
    lane: str,
    final_outcome: str,
    root: Path,
    artifact_id: str = "",
) -> dict:
    root = root.resolve()
    task = _load_task(task_id, root=root)

    if task.get("status") != "running":
        return {
            "kind": "task_not_running",
            "task_id": task_id,
            "status": task.get("status"),
            "message": "Task is not currently running, so executor completion was skipped.",
        }

    if artifact_id.strip():
        result = publish_and_complete(
            task_id=task_id,
            artifact_id=artifact_id.strip(),
            actor=actor,
            lane=lane,
            final_outcome=final_outcome,
            root=root,
        )
        return {
            "kind": "completed_from_artifact",
            "task_id": task_id,
            "result": result,
        }

    complete_result = complete_task(
        task_id=task_id,
        actor=actor,
        lane=lane,
        final_outcome=final_outcome.strip() or f"Executor completed task: {task.get('normalized_request', task_id)}",
        root=root,
    )

    rebuild_result = None
    try:
        from runtime.dashboard.rebuild_all import rebuild_all
        rebuild_result = rebuild_all(root=root)
    except Exception as exc:
        rebuild_result = {
            "ok": False,
            "error": str(exc),
        }

    return {
        "kind": "completed_running_task",
        "task_id": task_id,
        "complete_result": complete_result,
        "rebuild_result": rebuild_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Complete one currently running task.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--actor", default="executor", help="Actor name")
    parser.add_argument("--lane", default="executor", help="Lane name")
    parser.add_argument("--final-outcome", default="", help="Final outcome text")
    parser.add_argument("--artifact-id", default="", help="Optional artifact id for publish+complete flow")
    args = parser.parse_args()

    result = complete_once(
        task_id=args.task_id,
        actor=args.actor,
        lane=args.lane,
        final_outcome=args.final_outcome,
        root=Path(args.root).resolve(),
        artifact_id=args.artifact_id,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
