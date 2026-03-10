#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path("/home/rollan/.openclaw/workspace/jarvis-v5")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.intake import create_task_from_message
from runtime.core.decision_router import route_task_for_decision
from runtime.core.review_store import record_review_verdict
from runtime.core.task_store import load_task
from runtime.core.approval_store import latest_approval_for_task


def run_deploy_case() -> dict:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    text = f"task: deploy live production service restart smoke {stamp}"

    created = create_task_from_message(
        text=text,
        user="handoff_smoke",
        lane="handoff_smoke",
        channel="handoff_smoke",
        message_id=f"deploy_{stamp}",
        root=ROOT,
    )

    task_id = created.get("task_id")
    if not task_id:
        return {
            "ok": False,
            "stage": "create_task_from_message",
            "created": created,
            "error": "task was not created",
        }

    before_route = load_task(task_id, root=ROOT)

    routed = route_task_for_decision(
        task_id=task_id,
        actor="handoff_smoke",
        lane="handoff_smoke",
        root=ROOT,
    )

    after_route = load_task(task_id, root=ROOT)

    review_id = routed.get("review_id")
    if not review_id:
        return {
            "ok": False,
            "stage": "route_task_for_decision",
            "created": created,
            "before_route_status": None if before_route is None else before_route.status,
            "route_result": routed,
            "after_route_status": None if after_route is None else after_route.status,
            "error": "no review_id returned",
        }

    review_record = record_review_verdict(
        review_id=review_id,
        verdict="approved",
        actor="handoff_smoke",
        lane="handoff_smoke",
        reason="smoke test review approval",
        root=ROOT,
    )

    after_review = load_task(task_id, root=ROOT)
    latest_approval = latest_approval_for_task(task_id, root=ROOT)

    return {
        "ok": True,
        "input": text,
        "task_id": task_id,
        "created_kind": created.get("kind"),
        "pre_route_status": None if before_route is None else before_route.status,
        "route_result": routed,
        "post_route_status": None if after_route is None else after_route.status,
        "review_verdict_status": review_record.status,
        "post_review_status": None if after_review is None else after_review.status,
        "approval_exists": latest_approval is not None,
        "approval_id": None if latest_approval is None else latest_approval.approval_id,
        "approval_status": None if latest_approval is None else latest_approval.status,
        "approval_requested_reviewer": None if latest_approval is None else latest_approval.requested_reviewer,
    }


def main() -> int:
    result = run_deploy_case()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
