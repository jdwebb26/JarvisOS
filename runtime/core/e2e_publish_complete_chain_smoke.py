#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.approval_store import latest_approval_for_task, record_approval_decision
from runtime.core.artifact_store import write_text_artifact
from runtime.core.intake import create_task_from_message
from runtime.core.review_store import latest_review_for_task, record_review_verdict
from runtime.core.task_runtime import load_task, save_task, ship_task


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
    temp_root = Path(tempfile.mkdtemp(prefix="e2e_publish_complete_chain_", dir=ROOT)).resolve()
    try:
        _mkdirs(temp_root)

        intake_result = create_task_from_message(
            text="task: deploy live production service restart e2e publish-complete smoke",
            user="smoke",
            lane="jarvis",
            channel="jarvis",
            message_id="smoke-msg",
            root=temp_root,
        )
        task_id = intake_result["task_id"]

        task_after_intake = load_task(temp_root, task_id)
        candidate_artifact = write_text_artifact(
            task_id=task_id,
            artifact_type="report",
            title="E2E approval candidate",
            summary="Candidate artifact for approval-backed ready_to_ship",
            content="This candidate artifact is promoted during approval resume before shipping.",
            actor="smoke",
            lane="artifacts",
            root=temp_root,
            producer_kind="backend",
            execution_backend=task_after_intake.execution_backend if task_after_intake else None,
        )
        task_after_candidate = load_task(temp_root, task_id)
        if task_after_candidate is None:
            raise AssertionError("Expected task to exist after candidate artifact creation.")
        task_after_candidate.final_outcome = "candidate_ready_for_live_apply"
        save_task(temp_root, task_after_candidate)
        review = latest_review_for_task(task_id, root=temp_root)
        if review is None:
            raise AssertionError("Expected intake routing to create a pending review.")

        review_result = record_review_verdict(
            review_id=review.review_id,
            verdict="approved",
            actor="anton",
            lane="review",
            reason="e2e smoke review approved",
            root=temp_root,
        )

        approval = latest_approval_for_task(task_id, root=temp_root)
        if approval is None:
            raise AssertionError("Expected review approval to create a pending approval.")

        approval_result = record_approval_decision(
            approval_id=approval.approval_id,
            decision="approved",
            actor="anton",
            lane="review",
            reason="e2e smoke approval approved",
            root=temp_root,
        )
        task_after_approval = load_task(temp_root, task_id)
        if task_after_approval.status != "ready_to_ship":
            raise AssertionError(
                f"Expected approval handoff to land in ready_to_ship, got {task_after_approval.status!r}"
            )

        artifact = write_text_artifact(
            task_id=task_id,
            artifact_type="report",
            title="E2E Publish Complete Smoke",
            summary="Disposable end-to-end publish_complete smoke artifact",
            content="This artifact proves the shipped-to-completed path through the gateway wrapper.",
            actor="smoke",
            lane="artifacts",
            root=temp_root,
        )

        ship_result = ship_task(
            root=temp_root,
            task_id=task_id,
            actor="smoke",
            lane="ship",
            final_outcome="e2e smoke shipped artifact",
        )

        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "runtime" / "gateway" / "complete_from_artifact.py"),
                "--root",
                str(temp_root),
                "--task-id",
                task_id,
                "--artifact-id",
                artifact["artifact_id"],
                "--actor",
                "smoke",
                "--lane",
                "outputs",
            ],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        )
        gateway_payload = json.loads(proc.stdout)

        task_after = load_task(temp_root, task_id)
        output_files = sorted((temp_root / "workspace" / "out").glob("*.json"))
        if task_after is None:
            raise AssertionError("Expected task to exist after gateway completion.")
        if task_after.status != "completed":
            raise AssertionError(f"Expected final task status completed, got {task_after.status!r}")
        if not output_files:
            raise AssertionError("Expected at least one output JSON record.")

        result = {
            "ok": True,
            "temp_root": str(temp_root),
            "task_id": task_id,
            "artifact_id": artifact["artifact_id"],
            "intake_result": intake_result,
            "status_after_intake": task_after_intake.status if task_after_intake else None,
            "review_id": review.review_id,
            "review_result": review_result.to_dict(),
            "approval_id": approval.approval_id,
            "approval_result": approval_result.to_dict(),
            "candidate_artifact_id": candidate_artifact["artifact_id"],
            "status_after_approval": task_after_approval.status,
            "ship_result": ship_result,
            "gateway_ack": gateway_payload["ack"],
            "complete_result": gateway_payload["result"]["complete_result"],
            "final_task_status": task_after.status,
            "output_record_count": len(output_files),
            "output_record": json.loads(output_files[0].read_text(encoding="utf-8")),
        }
        print(json.dumps(result, indent=2))
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
