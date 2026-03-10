#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_json(cmd: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Command did not return JSON: {' '.join(cmd)}\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        ) from exc


def _step_payload(name: str, command: list[str], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "step": name,
        "ok": True,
        "command": command,
        "payload": payload,
    }


def _failure_payload(name: str, command: list[str], error: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": False,
        "failed_step": name,
        "error": error,
        "steps": steps,
    }


def _assert_gateway_step(step: str, payload: dict[str, Any]) -> None:
    if step == "hermes_execute":
        status = payload["result"]["result"]["status"]
        if status != "completed":
            raise RuntimeError(f"Hermes execution ended with status `{status}`.")
    elif step == "replay_eval":
        if not payload["result"]["eval_result"]["passed"]:
            raise RuntimeError("Replay eval did not pass.")
    elif step == "autoresearch_campaign":
        status = payload["result"]["campaign"]["status"]
        if status != "completed":
            raise RuntimeError(f"Autoresearch campaign ended with status `{status}`.")
    elif step == "ralph_consolidate":
        status = payload["result"]["consolidation_run"]["status"]
        if status != "completed":
            raise RuntimeError(f"Ralph consolidation ended with status `{status}`.")


def _hermes_chain(args: argparse.Namespace, py: str, repo_root: Path, run_root: Path) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    current_step = "hermes_execute"
    current_command: list[str] = []

    hermes_command = [
        py,
        str(repo_root / "runtime" / "gateway" / "hermes_execute.py"),
        "--root",
        str(run_root),
        "--task-id",
        args.task_id,
        "--actor",
        args.actor,
        "--lane",
        args.hermes_lane,
        "--timeout-seconds",
        str(args.timeout_seconds),
    ]
    if args.hermes_response_json:
        hermes_command.extend(["--response-json", args.hermes_response_json])
    elif args.hermes_response_file:
        hermes_command.extend(["--response-file", args.hermes_response_file])

    try:
        current_command = hermes_command
        hermes = _run_json(hermes_command)
        _assert_gateway_step("hermes_execute", hermes)
        steps.append(_step_payload("hermes_execute", hermes_command, hermes))
        trace_id = hermes["result"]["result"]["trace_id"]

        replay_command = [
            py,
            str(repo_root / "runtime" / "gateway" / "replay_eval.py"),
            "--root",
            str(run_root),
            "--trace-id",
            trace_id,
            "--actor",
            args.actor,
            "--lane",
            args.eval_lane,
            "--evaluator-kind",
            args.evaluator_kind,
            "--objective",
            args.eval_objective,
        ]
        if args.eval_criteria_json:
            replay_command.extend(["--criteria-json", args.eval_criteria_json])
        current_step = "replay_eval"
        current_command = replay_command
        replay_eval = _run_json(replay_command)
        _assert_gateway_step("replay_eval", replay_eval)
        steps.append(_step_payload("replay_eval", replay_command, replay_eval))

        ralph_command = [
            py,
            str(repo_root / "runtime" / "gateway" / "ralph_consolidate.py"),
            "--root",
            str(run_root),
            "--task-id",
            args.task_id,
            "--actor",
            args.actor,
            "--lane",
            args.ralph_lane,
        ]
        current_step = "ralph_consolidate"
        current_command = ralph_command
        ralph = _run_json(ralph_command)
        _assert_gateway_step("ralph_consolidate", ralph)
        steps.append(_step_payload("ralph_consolidate", ralph_command, ralph))

        retrieve_command = [
            py,
            str(repo_root / "runtime" / "gateway" / "memory_retrieve.py"),
            "--root",
            str(run_root),
            "--actor",
            args.actor,
            "--lane",
            args.memory_lane,
            "--task-id",
            args.task_id,
        ]
        if args.memory_type:
            retrieve_command.extend(["--memory-type", args.memory_type])
        if args.include_candidate_memory:
            retrieve_command.append("--include-candidate")
        current_step = "memory_retrieve"
        current_command = retrieve_command
        retrieval = _run_json(retrieve_command)
        steps.append(_step_payload("memory_retrieve", retrieve_command, retrieval))
    except Exception as exc:
        return _failure_payload(current_step, current_command, str(exc), steps)

    return {
        "ok": True,
        "flow": "hermes_eval_ralph_memory",
        "task_id": args.task_id,
        "steps": steps,
        "summary": {
            "trace_id": trace_id,
            "eval_result_id": replay_eval["result"]["eval_result"]["eval_result_id"],
            "digest_artifact_id": ralph["result"]["digest_artifact_id"],
            "memory_retrieval_id": retrieval["result"]["retrieval"]["memory_retrieval_id"],
            "retrieved_memory_candidate_ids": retrieval["result"]["retrieval"]["returned_memory_candidate_ids"],
        },
    }


def _research_chain(args: argparse.Namespace, py: str, repo_root: Path, run_root: Path) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    current_step = "autoresearch_campaign"
    current_command: list[str] = []
    research_command = [
        py,
        str(repo_root / "runtime" / "gateway" / "autoresearch_campaign.py"),
        "--root",
        str(run_root),
        "--task-id",
        args.task_id,
        "--actor",
        args.actor,
        "--lane",
        args.research_lane,
        "--objective",
        args.research_objective,
        "--max-passes",
        str(args.max_passes),
        "--max-budget-units",
        str(args.max_budget_units),
    ]
    for metric in args.objective_metrics:
        research_command.extend(["--objective-metric", metric])
    if args.primary_metric:
        research_command.extend(["--primary-metric", args.primary_metric])
    if args.research_response_json:
        research_command.extend(["--response-json", args.research_response_json])
    elif args.research_response_file:
        research_command.extend(["--response-file", args.research_response_file])

    try:
        current_command = research_command
        research = _run_json(research_command)
        _assert_gateway_step("autoresearch_campaign", research)
        steps.append(_step_payload("autoresearch_campaign", research_command, research))

        ralph_command = [
            py,
            str(repo_root / "runtime" / "gateway" / "ralph_consolidate.py"),
            "--root",
            str(run_root),
            "--task-id",
            args.task_id,
            "--actor",
            args.actor,
            "--lane",
            args.ralph_lane,
        ]
        current_step = "ralph_consolidate"
        current_command = ralph_command
        ralph = _run_json(ralph_command)
        _assert_gateway_step("ralph_consolidate", ralph)
        steps.append(_step_payload("ralph_consolidate", ralph_command, ralph))

        retrieve_command = [
            py,
            str(repo_root / "runtime" / "gateway" / "memory_retrieve.py"),
            "--root",
            str(run_root),
            "--actor",
            args.actor,
            "--lane",
            args.memory_lane,
            "--task-id",
            args.task_id,
        ]
        if args.memory_type:
            retrieve_command.extend(["--memory-type", args.memory_type])
        if args.include_candidate_memory:
            retrieve_command.append("--include-candidate")
        current_step = "memory_retrieve"
        current_command = retrieve_command
        retrieval = _run_json(retrieve_command)
        steps.append(_step_payload("memory_retrieve", retrieve_command, retrieval))
    except Exception as exc:
        return _failure_payload(current_step, current_command, str(exc), steps)

    return {
        "ok": True,
        "flow": "autoresearch_ralph_memory",
        "task_id": args.task_id,
        "steps": steps,
        "summary": {
            "campaign_id": research["result"]["campaign"]["campaign_id"],
            "recommendation_id": research["result"]["recommendation"]["recommendation_id"],
            "digest_artifact_id": ralph["result"]["digest_artifact_id"],
            "memory_retrieval_id": retrieval["result"]["retrieval"]["memory_retrieval_id"],
            "retrieved_memory_candidate_ids": retrieval["result"]["retrieval"]["returned_memory_candidate_ids"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Thin overnight orchestration wrapper over the v5.1 operator gateways.")
    parser.add_argument("--root", default=str(REPO_ROOT), help="State/project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--flow", required=True, choices=["hermes", "research"], help="Bounded overnight flow to run")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--memory-type", default="", help="Optional retrieval filter")
    parser.add_argument("--include-candidate-memory", action="store_true", help="Include candidate memory in final retrieval")

    parser.add_argument("--hermes-lane", default="hermes", help="Lane for Hermes execution")
    parser.add_argument("--eval-lane", default="eval", help="Lane for replay eval")
    parser.add_argument("--ralph-lane", default="ralph", help="Lane for Ralph consolidation")
    parser.add_argument("--memory-lane", default="memory", help="Lane for memory retrieval")
    parser.add_argument("--timeout-seconds", type=int, default=30, help="Hermes timeout budget")
    parser.add_argument("--hermes-response-json", default="", help="Inline Hermes response JSON")
    parser.add_argument("--hermes-response-file", default="", help="Path to mock Hermes response JSON")
    parser.add_argument("--evaluator-kind", default="replay_check", help="Replay evaluator kind")
    parser.add_argument("--eval-objective", default="Confirm the latest Hermes run is replayable.", help="Replay eval objective")
    parser.add_argument("--eval-criteria-json", default="", help="Inline replay eval criteria JSON")

    parser.add_argument("--research-lane", default="research", help="Lane for autoresearch campaign")
    parser.add_argument("--research-objective", default="Run a bounded overnight research pass.", help="Research objective")
    parser.add_argument("--objective-metric", action="append", dest="objective_metrics", default=[], help="Objective metric name")
    parser.add_argument("--primary-metric", default="", help="Primary research metric")
    parser.add_argument("--max-passes", type=int, default=2, help="Maximum research passes")
    parser.add_argument("--max-budget-units", type=int, default=2, help="Maximum research budget units")
    parser.add_argument("--research-response-json", default="", help="Inline research response JSON or list")
    parser.add_argument("--research-response-file", default="", help="Path to mock research response JSON or list")
    args = parser.parse_args()

    run_root = Path(args.root).resolve()
    repo_root = REPO_ROOT
    py = sys.executable

    if args.flow == "hermes":
        payload = _hermes_chain(args, py, repo_root, run_root)
    else:
        if not args.objective_metrics:
            parser.error("--objective-metric is required for --flow research")
        payload = _research_chain(args, py, repo_root, run_root)

    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
