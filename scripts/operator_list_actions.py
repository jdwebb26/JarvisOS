#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import list_actions_view


def main() -> int:
    parser = argparse.ArgumentParser(description="List action candidates from the newest valid operator action pack.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--category", default="", help="Filter by action category")
    parser.add_argument("--task-id", default="", help="Filter by task id")
    parser.add_argument("--prefix", default="", help="Filter by stable action-id prefix")
    parser.add_argument("--limit", type=int, default=20, help="Maximum rows")
    parser.add_argument("--only-safe", action="store_true", help="Only include actions that appear safe to run now")
    parser.add_argument("--only-blocked", action="store_true", help="Only include blocked actions")
    parser.add_argument("--only-missing-from-newest-pack", action="store_true", help="Only include actions missing from the newest pack")
    parser.add_argument("--only-repeated-problems", action="store_true", help="Only include actions touched by repeated problems")
    args = parser.parse_args()

    payload = list_actions_view(
        Path(args.root).resolve(),
        category=args.category or None,
        task_id=args.task_id or None,
        prefix=args.prefix or None,
        limit=args.limit,
        only_safe=args.only_safe,
        only_blocked=args.only_blocked,
        only_missing_from_newest_pack=args.only_missing_from_newest_pack,
        only_repeated_problems=args.only_repeated_problems,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
