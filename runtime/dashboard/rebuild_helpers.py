#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.dashboard.event_board import build_event_board
from runtime.dashboard.heartbeat_report import build_heartbeat_report
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.status_names import normalize_status_name
from runtime.dashboard.task_board import build_task_board
from runtime.dashboard.output_board import build_output_board
from runtime.dashboard.state_export import _load_jsons, _load_flowstate_source_records, build_state_export
from runtime.flowstate.index_builder import build_flowstate_index
from runtime.gateway.review_inbox import build_review_inbox


def rebuild_all_outputs(root: Path) -> None:
    (root / "state" / "logs").mkdir(parents=True, exist_ok=True)
    build_flowstate_index(root)
    build_operator_snapshot(root)
    build_task_board(root)
    build_event_board(root)
    build_output_board(root=root)
    build_review_inbox(root)
    build_heartbeat_report(root)

    state_export = build_state_export(root)
    tasks = _load_jsons(root / "state" / "tasks")
    reviews = _load_jsons(root / "state" / "reviews")
    approvals = _load_jsons(root / "state" / "approvals")
    artifacts = _load_jsons(root / "state" / "artifacts")
    outputs = _load_jsons(root / "workspace" / "out")
    flowstate_sources = _load_flowstate_source_records(root / "state" / "flowstate_sources")

    summary = {
        "counts": {
            "tasks": len(tasks),
            "reviews": len(reviews),
            "approvals": len(approvals),
            "artifacts": len(artifacts),
            "outputs": len(outputs),
            "flowstate_sources": len(flowstate_sources),
        },
        "task_status_counts": {},
        "task_lifecycle_counts": state_export.get("task_lifecycle_counts", {}),
        "review_status_counts": {},
        "approval_status_counts": {},
        "artifact_lifecycle_counts": state_export.get("artifact_lifecycle_counts", {}),
        "output_status_counts": state_export.get("output_status_counts", {}),
        "flowstate_processing_counts": {},
    }

    for task in tasks:
        status = normalize_status_name(task.get("status", "unknown"))
        summary["task_status_counts"][status] = summary["task_status_counts"].get(status, 0) + 1

    for review in reviews:
        status = review.get("status", "unknown")
        summary["review_status_counts"][status] = summary["review_status_counts"].get(status, 0) + 1

    for approval in approvals:
        status = approval.get("status", "unknown")
        summary["approval_status_counts"][status] = summary["approval_status_counts"].get(status, 0) + 1

    for source in flowstate_sources:
        status = source.get("processing_status", "unknown")
        summary["flowstate_processing_counts"][status] = summary["flowstate_processing_counts"].get(status, 0) + 1

    (root / "state" / "logs" / "state_export.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
