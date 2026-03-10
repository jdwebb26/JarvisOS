#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


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


def _load_flowstate_index(root: Path) -> dict:
    path = root / "state" / "flowstate_sources" / "index.json"
    if not path.exists():
        return {"items": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"items": []}


def build_review_inbox(root: Path) -> dict:
    reviews = _load_jsons(root / "state" / "reviews")
    approvals = _load_jsons(root / "state" / "approvals")
    flowstate_index = _load_flowstate_index(root)

    pending_reviews = [
        {
            "review_id": r["review_id"],
            "task_id": r["task_id"],
            "reviewer_role": r["reviewer_role"],
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
            "summary": a["summary"],
        }
        for a in approvals
        if a.get("status") == "pending"
    ]

    flowstate_waiting = [
        {
            "source_id": item["source_id"],
            "title": item["title"],
            "promotion_request_ids": item.get("promotion_request_ids", []),
            "candidate_action_count": item.get("candidate_action_count", 0),
        }
        for item in flowstate_index.get("items", [])
        if item.get("processing_status") == "awaiting_promotion_approval"
    ]

    reply_parts = []

    if pending_reviews:
        reply_parts.append(
            "Pending reviews: " + "; ".join(
                f"{x['review_id']} for {x['task_id']} ({x['reviewer_role']})"
                for x in pending_reviews
            )
        )

    if pending_approvals:
        reply_parts.append(
            "Pending approvals: " + "; ".join(
                f"{x['approval_id']} for {x['task_id']} ({x['requested_reviewer']})"
                for x in pending_approvals
            )
        )

    if flowstate_waiting:
        reply_parts.append(
            "Flowstate waiting promotion: " + "; ".join(
                f"{x['source_id']} ({x['title']}, actions={x['candidate_action_count']})"
                for x in flowstate_waiting
            )
        )

    if not reply_parts:
        reply_parts.append("Review inbox is clear.")

    result = {
        "pending_reviews": pending_reviews,
        "pending_approvals": pending_approvals,
        "flowstate_waiting_promotion": flowstate_waiting,
        "reply": " | ".join(reply_parts),
    }

    out_path = root / "state" / "logs" / "review_inbox.json"
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a #review-friendly inbox summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    result = build_review_inbox(Path(args.root).resolve())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
