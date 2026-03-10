#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.gateway.acknowledgements import hermes_execute_ack
from runtime.integrations.hermes_adapter import (
    HermesTaskRequest,
    HermesTransportUnreachableError,
    execute_hermes_task,
)


def _build_transport(args: argparse.Namespace):
    if args.simulate_timeout:
        def timeout_transport(_: HermesTaskRequest) -> dict:
            raise TimeoutError("Hermes request exceeded timeout budget.")

        return timeout_transport

    if args.simulate_unreachable:
        def unreachable_transport(_: HermesTaskRequest) -> dict:
            raise HermesTransportUnreachableError("Hermes backend is unreachable.")

        return unreachable_transport

    if args.simulate_malformed:
        def malformed_transport(_: HermesTaskRequest) -> dict:
            return {"summary": "missing title/content"}

        return malformed_transport

    if args.response_json:
        payload = json.loads(args.response_json)

        def json_transport(_: HermesTaskRequest) -> dict:
            return dict(payload)

        return json_transport

    if args.response_file:
        payload = json.loads(Path(args.response_file).read_text(encoding="utf-8"))

        def file_transport(_: HermesTaskRequest) -> dict:
            return dict(payload)

        return file_transport

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway wrapper for a bounded Hermes execution.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="hermes", help="Lane name")
    parser.add_argument("--timeout-seconds", type=int, default=30, help="Hermes timeout budget")
    parser.add_argument("--response-json", default="", help="Inline mock Hermes JSON payload")
    parser.add_argument("--response-file", default="", help="Path to a mock Hermes JSON payload")
    parser.add_argument("--simulate-timeout", action="store_true", help="Simulate a Hermes timeout")
    parser.add_argument("--simulate-unreachable", action="store_true", help="Simulate an unreachable Hermes backend")
    parser.add_argument("--simulate-malformed", action="store_true", help="Simulate a malformed Hermes response")
    args = parser.parse_args()

    result = execute_hermes_task(
        task_id=args.task_id,
        actor=args.actor,
        lane=args.lane,
        root=Path(args.root).resolve(),
        timeout_seconds=args.timeout_seconds,
        transport=_build_transport(args),
    )
    print(json.dumps({"result": result, "ack": hermes_execute_ack(result)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
