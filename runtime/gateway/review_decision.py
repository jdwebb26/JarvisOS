#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.review_store import record_review_verdict
from runtime.core.task_store import load_task
from runtime.gateway.acknowledgements import review_recorded_ack


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway wrapper for recording a review verdict.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--review-id", required=True, help="Review id")
    parser.add_argument(
        "--verdict",
        required=True,
        choices=["approved", "changes_requested", "rejected"],
        help="Review verdict",
    )
    parser.add_argument("--actor", default="reviewer", help="Actor recording the verdict")
    parser.add_argument("--lane", default="review", help="Lane")
    parser.add_argument("--reason", default="", help="Reason text")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    record = record_review_verdict(
        review_id=args.review_id,
        verdict=args.verdict,
        actor=args.actor,
        lane=args.lane,
        reason=args.reason,
        root=root,
    )

    task = load_task(record.task_id, root=root)
    task_status_after = task.status if task else "unknown"

    result = record.to_dict()
    ack = review_recorded_ack(result, task_status_after)

    print(json.dumps({"result": result, "ack": ack}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
