#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import list_runs_view


def main() -> int:
    parser = argparse.ArgumentParser(description="List compact recent operator wrapper runs.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--kind", required=True, choices=["execution", "queue", "bulk", "intervention", "autofix"])
    parser.add_argument("--failed-only", action="store_true")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--action-id", default="")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    payload = list_runs_view(
        Path(args.root).resolve(),
        kind=args.kind,
        failed_only=args.failed_only,
        task_id=args.task_id or None,
        action_id=args.action_id or None,
        limit=args.limit,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
