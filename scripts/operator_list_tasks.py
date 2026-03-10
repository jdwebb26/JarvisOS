#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import list_tasks_view


def main() -> int:
    parser = argparse.ArgumentParser(description="List task-centric operator control-plane summaries.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--needs-review", action="store_true")
    parser.add_argument("--needs-approval", action="store_true")
    parser.add_argument("--needs-memory-decision", action="store_true")
    parser.add_argument("--has-queue-failure", action="store_true")
    parser.add_argument("--has-bulk-failure", action="store_true")
    parser.add_argument("--has-repeated-problems", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    payload = list_tasks_view(
        Path(args.root).resolve(),
        needs_review=args.needs_review,
        needs_approval=args.needs_approval,
        needs_memory_decision=args.needs_memory_decision,
        has_queue_failure=args.has_queue_failure,
        has_bulk_failure=args.has_bulk_failure,
        has_repeated_problems=args.has_repeated_problems,
        limit=args.limit,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
