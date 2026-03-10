#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.output_store import publish_artifact
from runtime.core.task_runtime import complete_task


def _load_task(task_id: str, *, root: Path) -> dict:
    path = root / "state" / "tasks" / f"{task_id}.json"
    if not path.exists():
        raise ValueError(f"Task not found: {task_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def publish_and_complete(
        *,
        task_id: str,
        artifact_id: str,
        actor: str,
        lane: str,
        final_outcome: str,
        root: Path,
    ) -> dict:
        task_before = _load_task(task_id, root=root)
    
        if task_before.get("status") not in {"running", "completed", "shipped"}:
            raise ValueError(
                f"Task {task_id} is {task_before.get('status')}, so publish+complete requires a running, completed, or shipped task."
            )
    
        publish_result = publish_artifact(
            task_id=task_id,
            artifact_id=artifact_id,
            actor=actor,
            lane=lane,
            root=root,
        )
    
        if task_before.get("status") == "completed":
            complete_result = {
                "task_id": task_id,
                "previous_status": task_before.get("status"),
                "status": task_before.get("status"),
                "reason": f"Task already {task_before.get('status')}.",
                "final_outcome": task_before.get("final_outcome", ""),
                "event_id": None,
                "already_completed": True,
            }
        else:
            outcome = final_outcome.strip()
            if not outcome:
                if publish_result.get("already_published"):
                    outcome = (
                        f"Used existing published output {publish_result['output_id']} "
                        f"from artifact {artifact_id}."
                    )
                else:
                    outcome = (
                        f"Published output {publish_result['output_id']} "
                        f"from artifact {artifact_id}."
                    )
    
            complete_result = complete_task(
                task_id=task_id,
                actor=actor,
                lane=lane,
                final_outcome=outcome,
                root=root,
            )
            complete_result["already_completed"] = False
    
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
            "publish_result": publish_result,
            "complete_result": complete_result,
            "rebuild_result": rebuild_result,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a linked artifact and complete its task.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--artifact-id", required=True, help="Artifact id")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="outputs", help="Lane name")
    parser.add_argument("--final-outcome", default="", help="Final outcome text for the task")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = publish_and_complete(
        task_id=args.task_id,
        artifact_id=args.artifact_id,
        actor=args.actor,
        lane=args.lane,
        final_outcome=args.final_outcome,
        root=Path(args.root).resolve(),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
