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


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway wrapper for explicit output publication.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--artifact-id", required=True, help="Artifact id")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="outputs", help="Lane name")
    parser.add_argument("--allow-duplicate", action="store_true", help="Allow duplicate output records")
    args = parser.parse_args()

    result = publish_artifact(
        task_id=args.task_id,
        artifact_id=args.artifact_id,
        actor=args.actor,
        lane=args.lane,
        root=Path(args.root).resolve(),
        allow_duplicate=args.allow_duplicate,
    )

    if result.get("already_published"):
        ack = {
            "kind": "output_existing_ack",
            "reply": (
                f"No new output created. Existing output `{result['output_id']}` already "
                f"covers artifact `{result['artifact_id']}` for task `{result['task_id']}`."
            ),
            "output_id": result["output_id"],
            "task_id": result["task_id"],
            "artifact_id": result["artifact_id"],
        }
    else:
        ack = {
            "kind": "output_published_ack",
            "reply": (
                f"Published output `{result['output_id']}` from artifact "
                f"`{result['artifact_id']}` for task `{result['task_id']}`."
            ),
            "output_id": result["output_id"],
            "task_id": result["task_id"],
            "artifact_id": result["artifact_id"],
        }

    print(json.dumps({"result": result, "ack": ack}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
