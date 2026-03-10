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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gateway wrapper for publish-and-complete operator action."
    )
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--artifact-id", required=True, help="Artifact id")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="outputs", help="Lane name")
    parser.add_argument("--final-outcome", default="", help="Final outcome text for the task")
    args = parser.parse_args()

    result = publish_and_complete(
        task_id=args.task_id,
        artifact_id=args.artifact_id,
        actor=args.actor,
        lane=args.lane,
        final_outcome=args.final_outcome,
        root=Path(args.root).resolve(),
    )

    publish_result = result["publish_result"]
    complete_result = result["complete_result"]

    if publish_result.get("already_published") and complete_result.get("already_completed"):
        ack = {
            "kind": "publish_complete_noop_ack",
            "reply": (
                f"No new output created and no task change needed. Existing output "
                f"`{publish_result['output_id']}` already covers artifact "
                f"`{publish_result['artifact_id']}`, and task "
                f"`{complete_result['task_id']}` is already `completed`."
            ),
            "output_id": publish_result["output_id"],
            "task_id": complete_result["task_id"],
            "artifact_id": publish_result["artifact_id"],
            "task_status_after": complete_result["status"],
        }
    elif publish_result.get("already_published"):
        ack = {
            "kind": "publish_complete_reused_output_ack",
            "reply": (
                f"Reused existing output `{publish_result['output_id']}` for artifact "
                f"`{publish_result['artifact_id']}` and marked task "
                f"`{complete_result['task_id']}` as `completed`."
            ),
            "output_id": publish_result["output_id"],
            "task_id": complete_result["task_id"],
            "artifact_id": publish_result["artifact_id"],
            "task_status_after": complete_result["status"],
        }
    else:
        ack = {
            "kind": "publish_complete_ack",
            "reply": (
                f"Published output `{publish_result['output_id']}` from artifact "
                f"`{publish_result['artifact_id']}` and marked task "
                f"`{complete_result['task_id']}` as `completed`."
            ),
            "output_id": publish_result["output_id"],
            "task_id": complete_result["task_id"],
            "artifact_id": publish_result["artifact_id"],
            "task_status_after": complete_result["status"],
        }

    print(json.dumps({"result": result, "ack": ack}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
