#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.dashboard.status_names import normalize_status_name


def _load_jsons(folder: Path) -> list[dict]:
    rows: list[dict] = []
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return rows


def _load_flowstate_source_records(folder: Path) -> list[dict]:
    rows: list[dict] = []
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "source_id" not in row:
            continue
        rows.append(row)
    return rows


def build_state_export(root: Path) -> dict:
    tasks = _load_jsons(root / "state" / "tasks")
    reviews = _load_jsons(root / "state" / "reviews")
    approvals = _load_jsons(root / "state" / "approvals")
    approval_checkpoints = _load_jsons(root / "state" / "approval_checkpoints")
    artifacts = _load_jsons(root / "state" / "artifacts")
    outputs = _load_jsons(root / "workspace" / "out")
    flowstate_sources = _load_flowstate_source_records(root / "state" / "flowstate_sources")
    controls = _load_jsons(root / "state" / "controls")
    control_actions = _load_jsons(root / "state" / "control_actions")
    hermes_requests = _load_jsons(root / "state" / "hermes_requests")
    hermes_results = _load_jsons(root / "state" / "hermes_results")
    research_campaigns = _load_jsons(root / "state" / "research_campaigns")
    experiment_runs = _load_jsons(root / "state" / "experiment_runs")
    metric_results = _load_jsons(root / "state" / "metric_results")
    research_recommendations = _load_jsons(root / "state" / "research_recommendations")

    summary = {
        "counts": {
            "tasks": len(tasks),
            "reviews": len(reviews),
            "approvals": len(approvals),
            "approval_checkpoints": len(approval_checkpoints),
            "artifacts": len(artifacts),
            "outputs": len(outputs),
            "flowstate_sources": len(flowstate_sources),
            "controls": len(controls),
            "control_actions": len(control_actions),
            "hermes_requests": len(hermes_requests),
            "hermes_results": len(hermes_results),
            "research_campaigns": len(research_campaigns),
            "experiment_runs": len(experiment_runs),
            "metric_results": len(metric_results),
            "research_recommendations": len(research_recommendations),
        },
        "task_status_counts": {},
        "task_lifecycle_counts": {},
        "review_status_counts": {},
        "approval_status_counts": {},
        "artifact_lifecycle_counts": {},
        "output_status_counts": {},
        "flowstate_processing_counts": {},
        "control_run_state_counts": {},
        "control_safety_mode_counts": {},
        "hermes_result_status_counts": {},
        "research_campaign_status_counts": {},
        "experiment_run_status_counts": {},
        "research_recommendation_action_counts": {},
    }

    for task in tasks:
        status = normalize_status_name(task.get("status", "unknown"))
        lifecycle_state = task.get("lifecycle_state", "unknown")
        summary["task_status_counts"][status] = summary["task_status_counts"].get(status, 0) + 1
        summary["task_lifecycle_counts"][lifecycle_state] = summary["task_lifecycle_counts"].get(lifecycle_state, 0) + 1

    for review in reviews:
        status = review.get("status", "unknown")
        summary["review_status_counts"][status] = summary["review_status_counts"].get(status, 0) + 1

    for approval in approvals:
        status = approval.get("status", "unknown")
        summary["approval_status_counts"][status] = summary["approval_status_counts"].get(status, 0) + 1

    for artifact in artifacts:
        lifecycle_state = artifact.get("lifecycle_state", "unknown")
        summary["artifact_lifecycle_counts"][lifecycle_state] = (
            summary["artifact_lifecycle_counts"].get(lifecycle_state, 0) + 1
        )

    for output in outputs:
        status = output.get("status", "unknown")
        summary["output_status_counts"][status] = summary["output_status_counts"].get(status, 0) + 1

    for source in flowstate_sources:
        status = source.get("processing_status", "unknown")
        summary["flowstate_processing_counts"][status] = summary["flowstate_processing_counts"].get(status, 0) + 1

    for control in controls:
        run_state = control.get("run_state", "unknown")
        safety_mode = control.get("safety_mode", "unknown")
        summary["control_run_state_counts"][run_state] = summary["control_run_state_counts"].get(run_state, 0) + 1
        summary["control_safety_mode_counts"][safety_mode] = summary["control_safety_mode_counts"].get(safety_mode, 0) + 1

    for result in hermes_results:
        status = result.get("status", "unknown")
        summary["hermes_result_status_counts"][status] = summary["hermes_result_status_counts"].get(status, 0) + 1

    for campaign in research_campaigns:
        status = campaign.get("status", "unknown")
        summary["research_campaign_status_counts"][status] = summary["research_campaign_status_counts"].get(status, 0) + 1

    for run in experiment_runs:
        status = run.get("status", "unknown")
        summary["experiment_run_status_counts"][status] = summary["experiment_run_status_counts"].get(status, 0) + 1

    for recommendation in research_recommendations:
        action = recommendation.get("action", "unknown")
        summary["research_recommendation_action_counts"][action] = summary["research_recommendation_action_counts"].get(action, 0) + 1

    out_path = root / "state" / "logs" / "state_export.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a compact state summary for operator handoff/debug.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    summary = build_state_export(root)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
