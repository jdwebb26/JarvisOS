#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.decision_router import route_task_for_decision
from runtime.gateway.acknowledgements import review_requested_ack, approval_requested_ack


def _canonical_kind(kind: str) -> str:
    if kind == "waiting_on_review":
        return "waiting_review"
    if kind == "waiting_on_approval":
        return "waiting_approval"
    return kind


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway follow-up bridge for review/approval routing.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--actor", default="operator", help="Requester")
    parser.add_argument("--lane", default="review", help="Lane")
    args = parser.parse_args()

    result = route_task_for_decision(
        task_id=args.task_id,
        actor=args.actor,
        lane=args.lane,
        root=Path(args.root).resolve(),
    )
    result_kind = _canonical_kind(result["kind"])

    if result_kind == "review_requested":
        ack = review_requested_ack(result)
    elif result_kind == "approval_requested":
        ack = approval_requested_ack(result)
    elif result_kind == "waiting_review":
        ack = {
            "kind": "waiting_review_ack",
            "reply": (
                f"Task `{result['task_id']}` is still waiting on review "
                f"`{result['review_id']}` from {result['reviewer_role']}."
            ),
        }
    elif result_kind == "waiting_approval":
        ack = {
            "kind": "waiting_approval_ack",
            "reply": (
                f"Task `{result['task_id']}` is still waiting on approval "
                f"`{result['approval_id']}` from {result['requested_reviewer']}."
            ),
        }
    elif result_kind == "blocked_by_review":
        ack = {
            "kind": "blocked_by_review_ack",
            "reply": result["message"],
        }
    elif result_kind == "blocked_by_approval":
        ack = {
            "kind": "blocked_by_approval_ack",
            "reply": result["message"],
        }
    else:
        ack = {
            "kind": "no_action_ack",
            "reply": result["message"],
        }

    print(json.dumps({"result": {**result, "kind": result_kind}, "ack": ack}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
