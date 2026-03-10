#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.gateway.acknowledgements import memory_decision_ack
from runtime.memory.governance import (
    promote_memory_candidate,
    reject_memory_candidate,
    supersede_memory_candidate,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway wrapper for memory candidate governance.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--action", required=True, choices=["promote", "reject", "supersede"], help="Decision action")
    parser.add_argument("--memory-candidate-id", required=True, help="Memory candidate id")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="memory", help="Lane name")
    parser.add_argument("--reason", default="", help="Decision reason")
    parser.add_argument("--confidence-score", type=float, default=None, help="Optional confidence score for promote")
    parser.add_argument(
        "--superseded-by-memory-candidate-id",
        default="",
        help="Superseding memory candidate id for supersede action",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if args.action == "promote":
        record = promote_memory_candidate(
            memory_candidate_id=args.memory_candidate_id,
            actor=args.actor,
            lane=args.lane,
            root=root,
            reason=args.reason,
            confidence_score=args.confidence_score,
        )
    elif args.action == "reject":
        record = reject_memory_candidate(
            memory_candidate_id=args.memory_candidate_id,
            actor=args.actor,
            lane=args.lane,
            root=root,
            reason=args.reason,
        )
    else:
        record = supersede_memory_candidate(
            memory_candidate_id=args.memory_candidate_id,
            actor=args.actor,
            lane=args.lane,
            root=root,
            reason=args.reason,
            superseded_by_memory_candidate_id=args.superseded_by_memory_candidate_id or None,
        )

    result = {
        "action": args.action,
        "memory_candidate": record.to_dict(),
    }
    print(json.dumps({"result": result, "ack": memory_decision_ack(args.action, result["memory_candidate"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
