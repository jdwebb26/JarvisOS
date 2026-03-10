#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.approval_store import record_approval_decision
from runtime.core.task_store import load_task
from runtime.gateway.acknowledgements import approval_recorded_ack


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway wrapper for recording an approval decision.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--approval-id", required=True, help="Approval id")
    parser.add_argument(
        "--decision",
        required=True,
        choices=["approved", "rejected", "cancelled"],
        help="Approval decision",
    )
    parser.add_argument("--actor", default="reviewer", help="Actor recording the decision")
    parser.add_argument("--lane", default="review", help="Lane")
    parser.add_argument("--reason", default="", help="Reason text")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    record = record_approval_decision(
        approval_id=args.approval_id,
        decision=args.decision,
        actor=args.actor,
        lane=args.lane,
        reason=args.reason,
        root=root,
    )

    task = load_task(record.task_id, root=root)
    task_status_after = task.status if task else "unknown"

    result = record.to_dict()
    ack = approval_recorded_ack(result, task_status_after)

    print(json.dumps({"result": result, "ack": ack}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
