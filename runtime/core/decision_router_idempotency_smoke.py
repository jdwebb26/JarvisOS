#!/usr/bin/env python3
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.intake import create_task_from_message
from runtime.core.decision_router import route_task_for_decision
from runtime.core.review_store import latest_review_for_task, list_reviews_for_task, record_review_verdict
from runtime.core.approval_store import latest_approval_for_task, list_approvals_for_task
from runtime.core.task_store import load_task


def _mkdirs(root: Path) -> None:
    for rel in [
        "state/tasks",
        "state/events",
        "state/reviews",
        "state/approvals",
        "state/artifacts",
        "state/logs",
        "state/flowstate_sources",
        "workspace/out",
    ]:
        (root / rel).mkdir(parents=True, exist_ok=True)


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="decision_router_idempotency_", dir=ROOT)).resolve()
    try:
        _mkdirs(temp_root)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        text = f"task: deploy live production service restart router idempotency smoke {stamp}"

        created = create_task_from_message(
            text=text,
            user="router_smoke",
            lane="router_smoke",
            channel="router_smoke",
            message_id=f"router_smoke_{stamp}",
            root=temp_root,
        )

        task_id = created.get("task_id") or created.get("existing_task_id")
        if not task_id:
            raise RuntimeError("No task_id returned from intake.")

        task_after_create = load_task(task_id, root=temp_root)
        reviews_after_create = list_reviews_for_task(task_id, root=temp_root)
        approvals_after_create = list_approvals_for_task(task_id, root=temp_root)

        second_route = route_task_for_decision(
            task_id=task_id,
            actor="router_smoke",
            lane="router_smoke",
            root=temp_root,
        )

        reviews_after_second_route = list_reviews_for_task(task_id, root=temp_root)
        approvals_after_second_route = list_approvals_for_task(task_id, root=temp_root)

        latest_review = latest_review_for_task(task_id, root=temp_root)
        if latest_review is None:
            raise RuntimeError("Expected a review to exist after intake/route.")

        record_review_verdict(
            review_id=latest_review.review_id,
            verdict="approved",
            actor="router_smoke",
            lane="router_smoke",
            reason="router idempotency smoke approval of review",
            root=temp_root,
        )

        task_after_review_approval = load_task(task_id, root=temp_root)
        latest_approval = latest_approval_for_task(task_id, root=temp_root)
        approvals_after_review = list_approvals_for_task(task_id, root=temp_root)

        third_route = route_task_for_decision(
            task_id=task_id,
            actor="router_smoke",
            lane="router_smoke",
            root=temp_root,
        )

        approvals_after_third_route = list_approvals_for_task(task_id, root=temp_root)
        final_task = load_task(task_id, root=temp_root)

        payload = {
            "ok": True,
            "input": text,
            "task_id": task_id,
            "created_kind": created.get("kind"),
            "created_route_kind": (created.get("route_result") or {}).get("kind"),
            "status_after_create": None if task_after_create is None else task_after_create.status,
            "review_count_after_create": len(reviews_after_create),
            "approval_count_after_create": len(approvals_after_create),
            "second_route": second_route,
            "review_count_after_second_route": len(reviews_after_second_route),
            "approval_count_after_second_route": len(approvals_after_second_route),
            "latest_review_id": latest_review.review_id,
            "latest_review_status_after_verdict": "approved",
            "status_after_review_approval": None if task_after_review_approval is None else task_after_review_approval.status,
            "approval_exists_after_review": latest_approval is not None,
            "latest_approval_id": None if latest_approval is None else latest_approval.approval_id,
            "latest_approval_status": None if latest_approval is None else latest_approval.status,
            "approval_count_after_review": len(approvals_after_review),
            "third_route": third_route,
            "approval_count_after_third_route": len(approvals_after_third_route),
            "final_task_status": None if final_task is None else final_task.status,
        }

        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
