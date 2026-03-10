#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.gateway.acknowledgements import autoresearch_campaign_ack
from runtime.integrations.autoresearch_adapter import LabRunRequest, execute_research_campaign


def _parse_metric_directions(pairs: list[str]) -> dict[str, str]:
    directions: dict[str, str] = {}
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep or not name.strip() or not value.strip():
            raise ValueError(f"Invalid metric direction `{pair}`. Expected metric=direction.")
        directions[name.strip()] = value.strip()
    return directions


def _build_runner(args: argparse.Namespace):
    if args.response_json:
        payloads = json.loads(args.response_json)
        if not isinstance(payloads, list):
            payloads = [payloads]
        responses = [dict(item) for item in payloads]

        def response_runner(request: LabRunRequest) -> dict:
            index = max(0, request.pass_index - 1)
            if index >= len(responses):
                return dict(responses[-1])
            return dict(responses[index])

        return response_runner

    if args.response_file:
        payloads = json.loads(Path(args.response_file).read_text(encoding="utf-8"))
        if not isinstance(payloads, list):
            payloads = [payloads]
        responses = [dict(item) for item in payloads]

        def file_runner(request: LabRunRequest) -> dict:
            index = max(0, request.pass_index - 1)
            if index >= len(responses):
                return dict(responses[-1])
            return dict(responses[index])

        return file_runner

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway wrapper for a bounded autoresearch campaign.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="research", help="Lane name")
    parser.add_argument("--objective", required=True, help="Research objective")
    parser.add_argument("--objective-metric", action="append", dest="objective_metrics", required=True, help="Objective metric name")
    parser.add_argument("--metric-direction", action="append", default=[], help="Metric direction pair in metric=direction form")
    parser.add_argument("--primary-metric", default="", help="Primary metric name")
    parser.add_argument("--max-passes", type=int, default=2, help="Maximum experiment passes")
    parser.add_argument("--max-budget-units", type=int, default=2, help="Maximum total experiment budget units")
    parser.add_argument("--stop-conditions-json", default="", help="Inline JSON stop conditions object")
    parser.add_argument("--baseline-ref", default="", help="Optional baseline reference")
    parser.add_argument("--benchmark-slice-ref", default="", help="Optional benchmark slice reference")
    parser.add_argument("--response-json", default="", help="Inline mock JSON result or list of results")
    parser.add_argument("--response-file", default="", help="Path to mock JSON result or list of results")
    args = parser.parse_args()

    result = execute_research_campaign(
        task_id=args.task_id,
        actor=args.actor,
        lane=args.lane,
        objective=args.objective,
        objective_metrics=args.objective_metrics,
        metric_directions=_parse_metric_directions(args.metric_direction),
        primary_metric=args.primary_metric or None,
        max_passes=args.max_passes,
        max_budget_units=args.max_budget_units,
        stop_conditions=json.loads(args.stop_conditions_json) if args.stop_conditions_json else None,
        baseline_ref=args.baseline_ref or None,
        benchmark_slice_ref=args.benchmark_slice_ref or None,
        root=Path(args.root).resolve(),
        runner=_build_runner(args),
    )
    print(json.dumps({"result": result, "ack": autoresearch_campaign_ack(result)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
