#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.evals.trace_store import replay_trace_to_eval
from runtime.gateway.acknowledgements import replay_eval_ack


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway wrapper for replaying a stored trace into eval.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--trace-id", required=True, help="Run trace id")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="eval", help="Lane name")
    parser.add_argument("--evaluator-kind", default="replay_check", help="Evaluator kind")
    parser.add_argument("--objective", required=True, help="Eval objective")
    parser.add_argument("--criteria-json", default="", help="Inline JSON criteria object")
    parser.add_argument("--no-report-artifact", action="store_true", help="Skip candidate report artifact emission")
    args = parser.parse_args()

    result = replay_trace_to_eval(
        trace_id=args.trace_id,
        actor=args.actor,
        lane=args.lane,
        evaluator_kind=args.evaluator_kind,
        objective=args.objective,
        criteria=json.loads(args.criteria_json) if args.criteria_json else None,
        root=Path(args.root).resolve(),
        emit_report_artifact=not args.no_report_artifact,
    )
    print(json.dumps({"result": result, "ack": replay_eval_ack(result)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
