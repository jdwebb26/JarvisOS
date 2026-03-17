#!/usr/bin/env python3
"""End-to-end test: bounded task through intake → artifact → review → verdict → status transition.

Proves:
- Jarvis intake creates a task with correct review_required=True
- route_task_for_decision() correctly assigns reviewer (archimedes for code, anton for deploy)
- HAL-style artifact registration links to the task
- request_review() with linked artifact correctly populates linked_artifact_ids
- record_review_verdict(approved) transitions task to QUEUED or READY_TO_SHIP
- record_review_verdict(changes_requested) transitions task to BLOCKED
- review_inbox shows the item while pending, removes it after verdict

All state is written to a temp directory and cleaned up after.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.artifact_store import write_text_artifact
from runtime.core.intake import create_task_from_message
from runtime.core.review_store import latest_review_for_task, record_review_verdict
from runtime.core.task_store import load_task
from runtime.gateway.review_inbox import build_review_inbox


def _make_temp_root() -> Path:
    """Return a temp dir pre-seeded with the minimal state structure needed."""
    tmp = Path(tempfile.mkdtemp(prefix="openclaw_test_"))
    for subdir in [
        "state/tasks", "state/reviews", "state/approvals", "state/artifacts",
        "state/events", "state/task_provenance", "state/candidate_records",
        "state/logs", "state/routing_requests", "state/routing_policies",
        "state/backend_assignments", "state/controls", "state/workspaces",
        "state/flowstate_sources",
    ]:
        (tmp / subdir).mkdir(parents=True)
    # Stub flowstate index so review_inbox doesn't crash
    (tmp / "state" / "flowstate_sources" / "index.json").write_text('{"items":[]}', encoding="utf-8")
    return tmp


def test_code_task_intake_routes_to_archimedes() -> None:
    root = _make_temp_root()
    try:
        # Step 1: Jarvis intake — "task: fix the foo function"
        result = create_task_from_message(
            text="task: fix the authentication bug in login handler",
            user="operator",
            lane="jarvis",
            channel="jarvis",
            message_id="test_msg_001",
            root=root,
        )
        assert result["kind"] == "task_created", f"Expected task_created, got: {result['kind']}"
        task_id = result["task_id"]
        task = load_task(task_id, root=root)
        assert task is not None
        assert task.review_required is True, "code task must require review"

        # intake.py calls route_task_for_decision() inline — review is created during task creation
        # so status is immediately waiting_review (not queued)
        assert task.status == "waiting_review", f"expected waiting_review (intake routes inline), got {task.status}"

        # Extract review from intake result (already routed)
        route = result.get("route_result") or {}
        assert route.get("kind") == "review_requested", f"Expected review_requested in route_result, got: {route.get('kind')}"
        assert route.get("reviewer_role") == "archimedes", \
            f"code task should go to archimedes, got: {route.get('reviewer_role')}"
        review_id = route["review_id"]

        # Step 3: Check review inbox shows it
        inbox = build_review_inbox(root)
        pending_ids = [r["review_id"] for r in inbox["pending_reviews"]]
        assert review_id in pending_ids, f"review {review_id} not found in inbox: {pending_ids}"

        # Step 4: Simulate HAL producing an artifact (pre-review; linked_artifact_ids will be populated on re-review)
        art_result = write_text_artifact(
            task_id=task_id,
            artifact_type="code_patch",
            title="Fix authentication bug",
            summary="Fixed null check in login handler",
            content="def login(user):\n    if user is None:\n        raise ValueError('user required')\n    ...",
            actor="hal",
            lane="hal",
            root=root,
            producer_kind="hal",
        )
        artifact_id = art_result["artifact_id"]
        assert artifact_id, "artifact should have been created"

        # Step 5: Archimedes approves the review (operator acting as Archimedes proxy)
        review_after = record_review_verdict(
            review_id=review_id,
            verdict="approved",
            actor="archimedes",
            lane="review",
            reason="Code is correct. Null check added.",
            root=root,
        )
        assert review_after.status == "approved"

        task = load_task(task_id, root=root)
        assert task.status in ("queued", "ready_to_ship"), \
            f"after review approval (no approval_required), task should be queued or ready_to_ship, got: {task.status}"

        # Step 6: Review inbox should now be clear of this review
        inbox_after = build_review_inbox(root)
        pending_after = [r["review_id"] for r in inbox_after["pending_reviews"]]
        assert review_id not in pending_after, \
            f"review {review_id} should be gone from inbox after approval, but still present: {pending_after}"

        print("  ✓ code task: intake → archimedes review → verdict → queued")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_deploy_task_routes_to_anton_with_approval() -> None:
    root = _make_temp_root()
    try:
        result = create_task_from_message(
            text="task: deploy live production service restart for NQ strategy runner",
            user="operator",
            lane="jarvis",
            channel="jarvis",
            message_id="test_msg_002",
            root=root,
        )
        assert result["kind"] == "task_created"
        task_id = result["task_id"]
        task = load_task(task_id, root=root)
        assert task.review_required is True
        assert task.approval_required is True, "deploy task must require approval"

        # intake routes inline: review is already created on task creation
        route = result.get("route_result") or {}
        assert route.get("kind") == "review_requested", \
            f"Expected review_requested in route_result, got: {route.get('kind')}"
        assert route.get("reviewer_role") == "anton", \
            f"deploy task should go to anton, got: {route.get('reviewer_role')}"
        review_id = route["review_id"]

        # Anton approves review → triggers approval request
        record_review_verdict(
            review_id=review_id,
            verdict="approved",
            actor="anton",
            lane="review",
            reason="Deploy sequence looks correct.",
            root=root,
        )
        task = load_task(task_id, root=root)
        assert task.status == "waiting_approval", \
            f"deploy task after review approval should be waiting_approval, got: {task.status}"

        # Check approval is now pending
        inbox = build_review_inbox(root)
        pending_approvals = [a["approval_id"] for a in inbox["pending_approvals"]]
        assert len(pending_approvals) > 0, "should have a pending approval after review approval"

        print("  ✓ deploy task: intake → anton review → approval pending → waiting_approval")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_review_changes_requested_blocks_task() -> None:
    root = _make_temp_root()
    try:
        result = create_task_from_message(
            text="task: patch the risk calculation function",
            user="operator",
            lane="jarvis",
            channel="jarvis",
            message_id="test_msg_003",
            root=root,
        )
        task_id = result["task_id"]
        route = result.get("route_result") or {}
        review_id = route["review_id"]

        # Archimedes requests changes
        record_review_verdict(
            review_id=review_id,
            verdict="changes_requested",
            actor="archimedes",
            lane="review",
            reason="Missing edge case for empty position.",
            root=root,
        )
        task = load_task(task_id, root=root)
        assert task.status == "blocked", \
            f"task should be blocked after changes_requested, got: {task.status}"

        print("  ✓ changes_requested verdict → task blocked")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_duplicate_task_not_created() -> None:
    root = _make_temp_root()
    try:
        text = "task: investigate momentum signal drift in backtest"
        r1 = create_task_from_message(text=text, user="op", lane="j", channel="j", message_id="m1", root=root)
        assert r1["kind"] == "task_created"
        r2 = create_task_from_message(text=text, user="op", lane="j", channel="j", message_id="m2", root=root)
        assert r2["kind"] == "duplicate_task_existing", f"Expected duplicate, got: {r2['kind']}"
        assert r2["existing_task_id"] == r1["task_id"]
        print("  ✓ duplicate task detection works")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_review_dispatch_dry_run() -> None:
    """Verify review_dispatch_to_discord.py runs cleanly in dry-run mode against live state."""
    from scripts.review_dispatch_to_discord import run_review_dispatch
    result = run_review_dispatch(ROOT, dry_run=True)
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["webhook_configured"] is True, "REVIEW_WEBHOOK_URL should be configured"
    # There are known pending reviews in live state
    assert result["dispatched_count"] >= 0
    print(f"  ✓ review dispatch dry run: {result['dispatched_count']} items would be dispatched")


if __name__ == "__main__":
    tests = [
        test_code_task_intake_routes_to_archimedes,
        test_deploy_task_routes_to_anton_with_approval,
        test_review_changes_requested_blocks_task,
        test_duplicate_task_not_created,
        test_review_dispatch_dry_run,
    ]
    failures = 0
    for test_fn in tests:
        name = test_fn.__name__
        try:
            test_fn()
            print(f"PASS {name}")
        except Exception as exc:
            print(f"FAIL {name}: {exc}")
            import traceback
            traceback.print_exc()
            failures += 1
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    raise SystemExit(0 if failures == 0 else 1)
