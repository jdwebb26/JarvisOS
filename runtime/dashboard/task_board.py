#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.controls.control_store import get_effective_control_state
from runtime.core.task_store import list_tasks
from runtime.dashboard.status_names import normalize_status_name


def build_task_board(root: Path) -> dict:
    tasks = list_tasks(root=root, limit=500)

    rows = []
    for t in tasks:
        control_state = get_effective_control_state(
            root=root,
            task_id=t.task_id,
            subsystem=t.execution_backend if t.execution_backend != "unassigned" else t.source_lane,
        )
        rows.append(
            {
                "task_id": t.task_id,
                "summary": t.normalized_request,
                "task_type": t.task_type,
                "status": normalize_status_name(t.status),
                "lifecycle_state": t.lifecycle_state,
                "priority": t.priority,
                "risk_level": t.risk_level,
                "execution_backend": t.execution_backend,
                "producer_backend": t.execution_backend,
                "assigned_model": t.assigned_model,
                "producer_metadata": {
                    "assigned_model": t.assigned_model,
                    "backend_run_id": getattr(t, "backend_run_id", None),
                    "source_lane": t.source_lane,
                    "future_reroute_ready": bool((getattr(t, "backend_metadata", {}) or {}).get("routing")),
                },
                "evidence_metadata": {
                    "candidate_artifact_count": len(t.candidate_artifact_ids or []),
                    "promoted_artifact_present": bool(t.promoted_artifact_id),
                    "impacted_output_count": len(t.impacted_output_ids or []),
                },
                "provenance_metadata": {
                    "review_link_count": len(t.related_review_ids or []),
                    "approval_link_count": len(t.related_approval_ids or []),
                },
                "review_required": t.review_required,
                "approval_required": t.approval_required,
                "promoted_artifact_id": t.promoted_artifact_id,
                "candidate_artifact_ids": t.candidate_artifact_ids,
                "demoted_artifact_ids": t.demoted_artifact_ids,
                "revoked_artifact_ids": t.revoked_artifact_ids,
                "impacted_output_ids": t.impacted_output_ids,
                "checkpoint_summary": t.checkpoint_summary,
                "last_error": t.last_error,
                "related_review_ids": t.related_review_ids,
                "related_approval_ids": t.related_approval_ids,
                "control_status": control_state["effective_status"],
                "control_run_state": control_state["effective_run_state"],
                "control_safety_mode": control_state["effective_safety_mode"],
                "control_reasons": control_state["active_reasons"],
                "updated_at": t.updated_at,
            }
        )

    board = {
        "rows": rows,
        "total": len(rows),
    }

    out_path = root / "state" / "logs" / "task_board.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8")
    return board


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a dashboard-friendly task board.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    board = build_task_board(root)
    print(json.dumps(board, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
