#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.gateway.acknowledgements import ralph_consolidation_ack
from runtime.ralph.consolidator import execute_consolidation


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway wrapper for Ralph consolidation.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="ralph", help="Lane name")
    parser.add_argument("--max-artifacts", type=int, default=5, help="Maximum source artifacts")
    parser.add_argument("--max-traces", type=int, default=5, help="Maximum source traces")
    parser.add_argument("--max-eval-results", type=int, default=5, help="Maximum source eval results")
    args = parser.parse_args()

    result = execute_consolidation(
        task_id=args.task_id,
        actor=args.actor,
        lane=args.lane,
        root=Path(args.root).resolve(),
        max_artifacts=args.max_artifacts,
        max_traces=args.max_traces,
        max_eval_results=args.max_eval_results,
    )
    print(json.dumps({"result": result, "ack": ralph_consolidation_ack(result)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
