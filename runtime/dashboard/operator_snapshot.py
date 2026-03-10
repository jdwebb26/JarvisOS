#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.status import summarize_status
from runtime.dashboard.status_names import normalize_status_summary


def _load_json_files(folder: Path) -> list[dict]:
    items: list[dict] = []
    if not folder.exists():
        return items
    for path in sorted(folder.glob("*.json")):
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return items


def _load_flowstate_index(root: Path) -> dict:
    path = root / "state" / "flowstate_sources" / "index.json"
    if not path.exists():
        return {"counts": {}, "items": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"counts": {}, "items": []}


def build_operator_snapshot(root: Path) -> dict:
    status = normalize_status_summary(summarize_status(root=root))
    reviews = _load_json_files(root / "state" / "reviews")
    approvals = _load_json_files(root / "state" / "approvals")
    flowstate_index = _load_flowstate_index(root)

    pending_reviews = [
        {
            "review_id": r["review_id"],
            "task_id": r["task_id"],
            "reviewer_role": r["reviewer_role"],
            "status": r["status"],
            "summary": r["summary"],
            "linked_artifact_ids": r.get("linked_artifact_ids", []),
        }
        for r in reviews
        if r.get("status") == "pending"
    ]

    pending_approvals = [
        {
            "approval_id": a["approval_id"],
            "task_id": a["task_id"],
            "requested_reviewer": a["requested_reviewer"],
            "status": a["status"],
            "summary": a["summary"],
            "linked_artifact_ids": a.get("linked_artifact_ids", []),
        }
        for a in approvals
        if a.get("status") == "pending"
    ]

    flowstate_waiting = [
        {
            "source_id": item["source_id"],
            "title": item["title"],
            "processing_status": item["processing_status"],
            "promotion_request_ids": item.get("promotion_request_ids", []),
            "extraction_artifact_present": item.get("extraction_artifact_present", False),
            "distillation_artifact_present": item.get("distillation_artifact_present", False),
            "candidate_action_count": item.get("candidate_action_count", 0),
        }
        for item in flowstate_index.get("items", [])
        if item.get("processing_status") == "awaiting_promotion_approval"
    ]

    candidate_apply_ready = [
        {
            "task_id": task["task_id"],
            "status": task["status"],
            "summary": task["summary"],
            "execution_backend": task.get("execution_backend"),
            "promoted_artifact_id": task.get("promoted_artifact_id"),
            "handoff": (
                "Approved and ready for live apply."
                if task.get("status") == "ready_to_ship"
                else "Already shipped; publish completion or final verification may be next."
            ),
            "next_action": (
                "Run Qwen candidate apply. Use --dry-run first if you want a no-write verification pass."
                if task.get("status") == "ready_to_ship"
                else "Confirm the linked artifact, then run publish-complete."
            ),
        }
        for task in status.get("ready_to_ship", []) + status.get("shipped", [])
        if task.get("promoted_artifact_id")
    ]

    if status.get("blocked"):
        operator_focus = "Clear blocked tasks and inspect the linked reasons first."
    elif pending_reviews:
        operator_focus = "Clear pending reviews first."
    elif pending_approvals:
        operator_focus = "Clear pending approvals next."
    elif status.get("revoked_outputs") or status.get("revoked_artifacts"):
        operator_focus = "Inspect revoked artifacts and outputs before continuing downstream work."
    elif status.get("impacted_outputs") or status.get("impacted_artifacts"):
        operator_focus = "Inspect impacted artifacts and outputs before shipping more work."
    elif candidate_apply_ready:
        operator_focus = "Apply or publish candidate-ready tasks."
    else:
        operator_focus = status.get("next_recommended_move", "")

    snapshot = {
        "status": status,
        "pending_reviews": pending_reviews,
        "pending_approvals": pending_approvals,
        "candidate_apply_ready": candidate_apply_ready,
        "flowstate_waiting_promotion": flowstate_waiting,
        "operator_focus": operator_focus,
        "counts": {
            "pending_reviews": len(pending_reviews),
            "pending_approvals": len(pending_approvals),
            "candidate_apply_ready": len(candidate_apply_ready),
            "flowstate_waiting_promotion": len(flowstate_waiting),
            "blocked": len(status.get("blocked", [])),
            "ready_to_ship": len(status.get("ready_to_ship", [])),
            "shipped": len(status.get("shipped", [])),
            "impacted_outputs": len(status.get("impacted_outputs", [])),
            "revoked_outputs": len(status.get("revoked_outputs", [])),
            "revoked_artifacts": len(status.get("revoked_artifacts", [])),
        },
    }

    out_path = root / "state" / "logs" / "operator_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an operator-facing dashboard snapshot.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    snapshot = build_operator_snapshot(root)
    print(json.dumps(snapshot, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
