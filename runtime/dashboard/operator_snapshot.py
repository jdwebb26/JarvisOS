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


def _task_row(task: dict) -> dict:
    return {
        "task_id": task.get("task_id"),
        "summary": task.get("normalized_request", ""),
        "status": task.get("status", "unknown"),
        "priority": task.get("priority", "normal"),
    }


def _with_raw_task_fallback(status: dict, tasks: list[dict]) -> dict:
    counts = status.get("counts", {})
    if counts.get("total_tasks", 0) > 0 or not tasks:
        return status

    queued_now = [_task_row(task) for task in tasks if task.get("status") == "queued"]
    running_now = [_task_row(task) for task in tasks if task.get("status") == "running"]
    blocked = [_task_row(task) for task in tasks if task.get("status") == "blocked"]
    waiting_review = [_task_row(task) for task in tasks if task.get("status") == "waiting_review"]
    waiting_approval = [_task_row(task) for task in tasks if task.get("status") == "waiting_approval"]
    finished_recently = [
        _task_row(task)
        for task in tasks
        if task.get("status") in {"completed", "shipped", "failed", "cancelled", "archived"}
    ][:10]

    if waiting_review:
        next_move = "Review tasks waiting on reviewer verdicts."
    elif waiting_approval:
        next_move = "Review approval-gated tasks first."
    elif running_now:
        next_move = "Let current in-progress work continue or inspect the top active task."
    elif queued_now:
        next_move = "Start the highest-priority queued task or inspect queued work."
    else:
        next_move = "No active work is currently queued or running."

    return {
        "queued_now": queued_now,
        "running_now": running_now,
        "blocked": blocked,
        "waiting_review": waiting_review,
        "waiting_approval": waiting_approval,
        "finished_recently": finished_recently,
        "counts": {
            "total_tasks": len(tasks),
            "queued": len(queued_now),
            "running": len(running_now),
            "blocked": len(blocked),
            "waiting_review": len(waiting_review),
            "waiting_approval": len(waiting_approval),
            "finished_recently": len(finished_recently),
        },
        "next_recommended_move": next_move,
    }


def build_operator_snapshot(root: Path) -> dict:
    tasks = _load_json_files(root / "state" / "tasks")
    status = _with_raw_task_fallback(
        normalize_status_summary(summarize_status(root=root)),
        tasks,
    )
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
            "summary": task["normalized_request"],
            "assigned_model": task.get("assigned_model"),
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
        for task in tasks
        if task.get("final_outcome") == "candidate_ready_for_live_apply"
        and task.get("status") in {"ready_to_ship", "shipped"}
    ]

    if pending_reviews:
        operator_focus = "Clear pending reviews first."
    elif pending_approvals:
        operator_focus = "Clear pending approvals next."
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
        },
    }

    out_path = root / "state" / "logs" / "operator_snapshot.json"
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
