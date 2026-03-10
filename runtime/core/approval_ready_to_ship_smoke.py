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
from runtime.core.review_store import latest_review_for_task, record_review_verdict
from runtime.core.approval_store import latest_approval_for_task, record_approval_decision
from runtime.core.task_store import load_task, save_task


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
    temp_root = Path(tempfile.mkdtemp(prefix="approval_ready_to_ship_", dir=ROOT)).resolve()
    try:
        _mkdirs(temp_root)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        text = f"task: deploy live production service restart ready-to-ship smoke {stamp}"

        created = create_task_from_message(
            text=text,
            user="ready_to_ship_smoke",
            lane="ready_to_ship_smoke",
            channel="ready_to_ship_smoke",
            message_id=f"ready_to_ship_smoke_{stamp}",
            root=temp_root,
        )

        task_id = created.get("task_id") or created.get("existing_task_id")
        if not task_id:
            raise RuntimeError("No task id returned.")

        after_create = load_task(task_id, root=temp_root)
        if after_create is None:
            raise RuntimeError("Task missing after create.")

        review = latest_review_for_task(task_id, root=temp_root)
        if review is None:
            raise RuntimeError("No review found after create.")

        record_review_verdict(
            review_id=review.review_id,
            verdict="approved",
            actor="ready_to_ship_smoke",
            lane="ready_to_ship_smoke",
            reason="ready_to_ship smoke review approval",
            root=temp_root,
        )

        after_review = load_task(task_id, root=temp_root)
        if after_review is None:
            raise RuntimeError("Task missing after review approval.")

        approval = latest_approval_for_task(task_id, root=temp_root)
        if approval is None:
            raise RuntimeError("No approval found after approved review.")

        after_review.final_outcome = "candidate_ready_for_live_apply"
        save_task(after_review, root=temp_root)

        record_approval_decision(
            approval_id=approval.approval_id,
            decision="approved",
            actor="ready_to_ship_smoke",
            lane="ready_to_ship_smoke",
            reason="ready_to_ship smoke approval approval",
            root=temp_root,
        )

        final_task = load_task(task_id, root=temp_root)
        if final_task is None:
            raise RuntimeError("Task missing after approval decision.")

        payload = {
            "ok": True,
            "input": text,
            "task_id": task_id,
            "created_kind": created.get("kind"),
            "created_route_kind": (created.get("route_result") or {}).get("kind"),
            "status_after_create": after_create.status,
            "review_id": review.review_id,
            "status_after_review_approved": after_review.status,
            "approval_id": approval.approval_id,
            "approval_status_after_decision": "approved",
            "final_outcome_before_approval_decision": "candidate_ready_for_live_apply",
            "final_task_status": final_task.status,
        }

        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
