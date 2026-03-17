#!/usr/bin/env python3
"""Post pending review/approval items to Discord via REVIEW_WEBHOOK_URL.

Reviews for archimedes are sent to ARCHIMEDES_WEBHOOK_URL if configured,
otherwise fall back to REVIEW_WEBHOOK_URL (#review operator-proxy channel).
Approvals always go to REVIEW_WEBHOOK_URL.

Idempotent: will not re-post items that were already dispatched
(tracked in state/logs/review_dispatch_sent.json).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import now_iso
from runtime.gateway.review_inbox import build_review_inbox
from scripts.dispatch_utils import load_sent, load_webhook_url, post_webhook, save_sent


SENT_LOG = ROOT / "state" / "logs" / "review_dispatch_sent.json"


def _format_review_message(r: dict[str, Any]) -> str:
    review_id = r["review_id"]
    task_id = r["task_id"]
    reviewer = r["reviewer_role"]
    summary = (r.get("summary") or "")[:200]
    approve_cmd = (
        f'python3 runtime/gateway/review_decision.py '
        f'--review-id {review_id} --verdict approved --actor {reviewer} --lane review --reason "Approved"'
    )
    changes_cmd = (
        f'python3 runtime/gateway/review_decision.py '
        f'--review-id {review_id} --verdict changes_requested --actor {reviewer} --lane review --reason "Needs changes"'
    )
    return (
        f"**REVIEW PENDING** `{review_id}`\n"
        f"Task: `{task_id}` | Reviewer: **{reviewer}**\n"
        f"> {summary}\n"
        f"✅ Approve: `{approve_cmd}`\n"
        f"🔄 Changes: `{changes_cmd}`"
    )


def _format_approval_message(a: dict[str, Any]) -> str:
    approval_id = a["approval_id"]
    task_id = a["task_id"]
    reviewer = a["requested_reviewer"]
    summary = (a.get("summary") or "")[:200]
    approve_cmd = (
        f'python3 runtime/gateway/approval_decision.py '
        f'--approval-id {approval_id} --decision approved --actor {reviewer} --lane review --reason "Approved"'
    )
    reject_cmd = (
        f'python3 runtime/gateway/approval_decision.py '
        f'--approval-id {approval_id} --decision rejected --actor {reviewer} --lane review --reason "Rejected"'
    )
    return (
        f"**APPROVAL PENDING** `{approval_id}`\n"
        f"Task: `{task_id}` | Reviewer: **{reviewer}**\n"
        f"> {summary}\n"
        f"✅ Approve: `{approve_cmd}`\n"
        f"❌ Reject: `{reject_cmd}`"
    )


def run_review_dispatch(root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    inbox = build_review_inbox(root)
    review_webhook = load_webhook_url("REVIEW_WEBHOOK_URL", root)
    archimedes_webhook = load_webhook_url("ARCHIMEDES_WEBHOOK_URL", root)

    sent = load_sent(SENT_LOG)
    dispatched: list[dict[str, Any]] = []
    skipped: list[str] = []

    for r in inbox.get("pending_reviews", []):
        item_id = r["review_id"]
        if item_id in sent:
            skipped.append(item_id)
            continue
        msg = _format_review_message(r)
        # Route archimedes reviews to dedicated webhook if available
        reviewer = r.get("reviewer_role", "")
        if reviewer == "archimedes" and archimedes_webhook:
            webhook = archimedes_webhook
        else:
            webhook = review_webhook
        if dry_run:
            result: dict[str, Any] = {"ok": True, "dry_run": True}
        else:
            result = post_webhook(webhook, msg)
        dispatched.append({"id": item_id, "kind": "review", "reviewer": reviewer, "result": result})
        if result["ok"]:
            sent.add(item_id)

    for a in inbox.get("pending_approvals", []):
        item_id = a["approval_id"]
        if item_id in sent:
            skipped.append(item_id)
            continue
        msg = _format_approval_message(a)
        if dry_run:
            result = {"ok": True, "dry_run": True}
        else:
            result = post_webhook(review_webhook, msg)
        dispatched.append({"id": item_id, "kind": "approval", "result": result})
        if result["ok"]:
            sent.add(item_id)

    if not dry_run:
        save_sent(SENT_LOG, sent)

    return {
        "ok": True,
        "dispatched_count": len(dispatched),
        "skipped_count": len(skipped),
        "webhook_configured": bool(review_webhook),
        "archimedes_webhook_configured": bool(archimedes_webhook),
        "dry_run": dry_run,
        "dispatched": dispatched,
        "skipped": skipped,
        "generated_at": now_iso(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Post pending review/approval items to Discord #review channel."
    )
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--dry-run", action="store_true", help="Build messages but do not post to Discord")
    args = parser.parse_args()

    result = run_review_dispatch(Path(args.root).resolve(), dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
