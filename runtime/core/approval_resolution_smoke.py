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
from runtime.core.approval_store import latest_approval_for_task, record_approval_decision
from runtime.core.task_store import load_task


def run_case() -> dict:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    text = f"task: deploy live production service restart approval smoke {stamp}"

    created = create_task_from_message(
        text=text,
        user="approval_smoke",
        lane="approval_smoke",
        channel="approval_smoke",
        message_id=f"approval_{stamp}",
        root=ROOT,
    )

    task_id = created.get("task_id")
    if not task_id:
        return {
            "ok": False,
            "stage": "create",
            "created": created,
            "error": "task not created",
        }

    before_route = load_task(task_id, root=ROOT)

    routed = route_task_for_decision(
        task_id=task_id,
        actor="approval_smoke",
        lane="approval_smoke",
        root=ROOT,
    )

    review_id = routed.get("review_id")
    if not review_id:
        return {
            "ok": False,
            "stage": "route",
            "task_id": task_id,
            "route_result": routed,
            "error": "review_id missing",
        }

    review_record = record_review_verdict(
        review_id=review_id,
        verdict="approved",
        actor="approval_smoke",
        lane="approval_smoke",
        reason="approval smoke review pass",
        root=ROOT,
    )

    before_approval = load_task(task_id, root=ROOT)
    approval = latest_approval_for_task(task_id, root=ROOT)

    if approval is None:
        return {
            "ok": False,
            "stage": "approval_creation",
            "task_id": task_id,
            "post_review_status": None if before_approval is None else before_approval.status,
            "error": "approval was not created",
        }

    approval_record = record_approval_decision(
        approval_id=approval.approval_id,
        decision="approved",
        actor="approval_smoke",
        lane="approval_smoke",
        reason="approval smoke final approval",
        root=ROOT,
    )

    after_approval = load_task(task_id, root=ROOT)

    return {
        "ok": True,
        "input": text,
        "task_id": task_id,
        "created_kind": created.get("kind"),
        "pre_route_status": None if before_route is None else before_route.status,
        "route_result": routed,
        "review_verdict_status": review_record.status,
        "post_review_status": None if before_approval is None else before_approval.status,
        "approval_id": approval.approval_id,
        "approval_status_after_decision": approval_record.status,
        "final_task_status": None if after_approval is None else after_approval.status,
    }


def main() -> int:
    result = run_case()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
