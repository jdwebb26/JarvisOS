#!/usr/bin/env python3
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path("/home/rollan/.openclaw/workspace/jarvis-v5")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.intake import create_task_from_message
from runtime.core.decision_router import route_task_for_decision
from runtime.core.review_store import latest_review_for_task, record_review_verdict
from runtime.core.approval_store import latest_approval_for_task, record_approval_decision
from runtime.core.task_store import load_task


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    text = f"task: deploy live production service restart task-store transition smoke {stamp}"

    created = create_task_from_message(
        text=text,
        user="task_store_smoke",
        lane="task_store_smoke",
        channel="task_store_smoke",
        message_id=f"task_store_smoke_{stamp}",
        root=ROOT,
    )

    task_id = created.get("task_id") or created.get("existing_task_id")
    if not task_id:
        raise RuntimeError("No task id returned.")

    after_create = load_task(task_id, root=ROOT)

    routed_again = route_task_for_decision(
        task_id=task_id,
        actor="task_store_smoke",
        lane="task_store_smoke",
        root=ROOT,
    )

    review = latest_review_for_task(task_id, root=ROOT)
    if review is None:
        raise RuntimeError("No review found.")

    record_review_verdict(
        review_id=review.review_id,
        verdict="approved",
        actor="task_store_smoke",
        lane="task_store_smoke",
        reason="task store transition smoke review approval",
        root=ROOT,
    )

    after_review = load_task(task_id, root=ROOT)

    approval = latest_approval_for_task(task_id, root=ROOT)
    if approval is None:
        raise RuntimeError("No approval found after approved review.")

    record_approval_decision(
        approval_id=approval.approval_id,
        decision="approved",
        actor="task_store_smoke",
        lane="task_store_smoke",
        reason="task store transition smoke approval approval",
        root=ROOT,
    )

    after_approval = load_task(task_id, root=ROOT)

    payload = {
        "ok": True,
        "input": text,
        "task_id": task_id,
        "created_kind": created.get("kind"),
        "created_route_kind": (created.get("route_result") or {}).get("kind"),
        "status_after_create": None if after_create is None else after_create.status,
        "routed_again_kind": routed_again.get("kind") if routed_again else None,
        "review_id": review.review_id,
        "status_after_review_approved": None if after_review is None else after_review.status,
        "approval_id": approval.approval_id,
        "approval_status_after_decision": "approved",
        "final_task_status": None if after_approval is None else after_approval.status,
    }

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
