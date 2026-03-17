#!/usr/bin/env python3
"""Tests for task_dispatch_to_hal.py and review_dispatch_to_discord.py.

Covers:
- Queued task → HAL dispatch payload (dry-run)
- Idempotency: second dispatch skips already-sent tasks
- Deploy tasks excluded from HAL dispatch
- Review dispatch payload for archimedes review
- Archimedes webhook routing: dedicated webhook vs review fallback
- Approval dispatch payload
- Shared dispatch_utils.load_sent / save_sent round-trip
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

from runtime.core.intake import create_task_from_message
from runtime.core.review_store import record_review_verdict
from runtime.core.task_store import load_task
from scripts.dispatch_utils import load_sent, save_sent
from scripts.task_dispatch_to_hal import run_task_dispatch, _format_task_message
from scripts.review_dispatch_to_discord import run_review_dispatch, _format_review_message, _format_approval_message


def _make_temp_root() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="openclaw_dispatch_test_"))
    for subdir in [
        "state/tasks", "state/reviews", "state/approvals", "state/artifacts",
        "state/events", "state/task_provenance", "state/candidate_records",
        "state/logs", "state/routing_requests", "state/routing_policies",
        "state/backend_assignments", "state/controls", "state/workspaces",
        "state/flowstate_sources",
    ]:
        (tmp / subdir).mkdir(parents=True)
    (tmp / "state" / "flowstate_sources" / "index.json").write_text('{"items":[]}', encoding="utf-8")
    return tmp


# ---------------------------------------------------------------------------
# dispatch_utils
# ---------------------------------------------------------------------------

def test_load_save_sent_round_trip() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="openclaw_test_"))
    try:
        log_path = tmp / "sent.json"
        assert load_sent(log_path) == set()
        ids = {"abc123", "def456", "ghi789"}
        save_sent(log_path, ids)
        assert load_sent(log_path) == ids
        print("  ✓ load_sent / save_sent round-trip")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_load_sent_tolerates_corrupt_file() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="openclaw_test_"))
    try:
        log_path = tmp / "sent.json"
        log_path.write_text("not valid json!!", encoding="utf-8")
        result = load_sent(log_path)
        assert result == set(), f"Expected empty set on corrupt file, got {result}"
        print("  ✓ load_sent returns empty set on corrupt file")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# task_dispatch_to_hal
# ---------------------------------------------------------------------------

def test_hal_dispatch_queued_code_task_dry_run() -> None:
    root = _make_temp_root()
    try:
        result = create_task_from_message(
            text="task: refactor the position sizing module",
            user="operator",
            lane="jarvis",
            channel="jarvis",
            message_id="dispatch_test_001",
            root=root,
        )
        assert result["kind"] == "task_created"
        task_id = result["task_id"]

        # Task arrives as waiting_review (intake routes inline) — not queued yet.
        # Approve the review to put it in queued state.
        route = result.get("route_result") or {}
        review_id = route["review_id"]
        record_review_verdict(
            review_id=review_id,
            verdict="approved",
            actor="archimedes",
            lane="review",
            reason="Looks good",
            root=root,
        )
        task = load_task(task_id, root=root)
        assert task.status in ("queued", "ready_to_ship"), \
            f"expected queued after approval, got {task.status}"

        # Run HAL dispatch in dry-run mode
        dispatch_result = run_task_dispatch(root, dry_run=True)
        assert dispatch_result["ok"] is True
        assert dispatch_result["dry_run"] is True
        assert dispatch_result["dispatched_count"] >= 1

        dispatched_ids = [d["id"] for d in dispatch_result["dispatched"]]
        assert task_id in dispatched_ids, f"task {task_id} not in dispatched: {dispatched_ids}"

        print(f"  ✓ HAL dispatch dry-run: {dispatch_result['dispatched_count']} task(s) dispatched")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hal_dispatch_idempotent() -> None:
    root = _make_temp_root()
    try:
        result = create_task_from_message(
            text="task: fix the authentication bug in login handler v2",
            user="operator",
            lane="jarvis",
            channel="jarvis",
            message_id="dispatch_test_002",
            root=root,
        )
        task_id = result["task_id"]
        route = result.get("route_result") or {}
        review_id = route.get("review_id")
        if review_id:
            record_review_verdict(
                review_id=review_id, verdict="approved", actor="archimedes",
                lane="review", reason="ok", root=root,
            )

        # First dispatch (dry-run=False but no real webhook — will fail post, but we track in sent anyway)
        # Use custom sent_log to avoid polluting live state
        sent_log = root / "state" / "logs" / "task_dispatch_sent.json"

        # Manually seed sent log as if task was already dispatched
        save_sent(sent_log, {task_id})

        # Import and monkey-patch SENT_LOG for this test
        import scripts.task_dispatch_to_hal as hal_mod
        orig_sent_log = hal_mod.SENT_LOG
        hal_mod.SENT_LOG = sent_log
        try:
            dispatch_result = run_task_dispatch(root, dry_run=True)
            assert dispatch_result["skipped_count"] >= 1, \
                f"expected skip for already-sent task, got: {dispatch_result}"
            assert task_id not in [d["id"] for d in dispatch_result["dispatched"]], \
                f"task {task_id} should have been skipped"
            print(f"  ✓ HAL dispatch idempotency: {dispatch_result['skipped_count']} skipped")
        finally:
            hal_mod.SENT_LOG = orig_sent_log
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hal_dispatch_excludes_deploy_tasks() -> None:
    root = _make_temp_root()
    try:
        result = create_task_from_message(
            text="task: deploy live production restart NQ strategy runner",
            user="operator",
            lane="jarvis",
            channel="jarvis",
            message_id="dispatch_test_003",
            root=root,
        )
        task_id = result["task_id"]

        dispatch_result = run_task_dispatch(root, dry_run=True)
        dispatched_ids = [d["id"] for d in dispatch_result["dispatched"]]
        assert task_id not in dispatched_ids, \
            f"deploy task {task_id} should NOT be dispatched to HAL"
        print("  ✓ HAL dispatch correctly excludes deploy tasks")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hal_format_message_contains_key_fields() -> None:
    """Unit test: message format includes task_id, type, and reply commands."""
    root = _make_temp_root()
    try:
        result = create_task_from_message(
            text="task: implement the momentum signal normalizer",
            user="operator",
            lane="jarvis",
            channel="jarvis",
            message_id="dispatch_test_004",
            root=root,
        )
        task_id = result["task_id"]
        task = load_task(task_id, root=root)
        msg = _format_task_message(task)
        assert task_id in msg, "task_id missing from message"
        assert "task_update.py" in msg, "task_update.py command missing from message"
        assert "complete_from_artifact.py" in msg, "artifact command missing from message"
        assert "--action start" in msg
        assert "--action complete" in msg
        print("  ✓ HAL message format contains all required fields")
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# review_dispatch_to_discord
# ---------------------------------------------------------------------------

def test_review_dispatch_dry_run_with_pending_review() -> None:
    root = _make_temp_root()
    try:
        result = create_task_from_message(
            text="task: patch the drawdown calculation in backtest engine",
            user="operator",
            lane="jarvis",
            channel="jarvis",
            message_id="dispatch_test_005",
            root=root,
        )
        route = result.get("route_result") or {}
        review_id = route["review_id"]

        dispatch_result = run_review_dispatch(root, dry_run=True)
        assert dispatch_result["ok"] is True
        dispatched_ids = [d["id"] for d in dispatch_result["dispatched"]]
        assert review_id in dispatched_ids, \
            f"review {review_id} not in dispatched: {dispatched_ids}"
        print(f"  ✓ review dispatch dry-run: {dispatch_result['dispatched_count']} item(s)")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_review_dispatch_archimedes_routed_to_dedicated_webhook() -> None:
    """When ARCHIMEDES_WEBHOOK_URL is set, archimedes reviews should use it."""
    root = _make_temp_root()
    try:
        result = create_task_from_message(
            text="task: fix the authentication bug in session validator",
            user="operator",
            lane="jarvis",
            channel="jarvis",
            message_id="dispatch_test_006",
            root=root,
        )
        route = result.get("route_result") or {}
        review_id = route.get("review_id")
        if not review_id:
            print("  ⚠ no review created for this task type — skipping archimedes routing test")
            return
        reviewer = route.get("reviewer_role", "")
        assert reviewer == "archimedes", f"expected archimedes, got {reviewer}"

        # Inject a fake archimedes webhook via env
        import os
        import scripts.review_dispatch_to_discord as rd_mod
        from unittest.mock import patch

        posted_to: list[str] = []

        def fake_post(url: str, content: str) -> dict:
            posted_to.append(url)
            return {"ok": True, "dry_run": False, "mock": True}

        with patch("scripts.review_dispatch_to_discord.post_webhook", fake_post), \
             patch("scripts.review_dispatch_to_discord.load_webhook_url") as mock_load:
            def side_effect(env_var: str, root_arg: Path) -> str:
                if env_var == "ARCHIMEDES_WEBHOOK_URL":
                    return "https://discord.com/api/webhooks/archimedes_fake/token"
                if env_var == "REVIEW_WEBHOOK_URL":
                    return "https://discord.com/api/webhooks/review_fake/token"
                return ""
            mock_load.side_effect = side_effect

            sent_log = root / "state" / "logs" / "review_dispatch_sent.json"
            orig_sent_log = rd_mod.SENT_LOG
            rd_mod.SENT_LOG = sent_log
            try:
                dispatch_result = run_review_dispatch(root, dry_run=False)
            finally:
                rd_mod.SENT_LOG = orig_sent_log

        assert len(posted_to) >= 1, "expected at least one webhook post"
        archimedes_url = "https://discord.com/api/webhooks/archimedes_fake/token"
        assert archimedes_url in posted_to, \
            f"archimedes review should post to archimedes webhook, posted to: {posted_to}"
        print("  ✓ archimedes review routes to dedicated ARCHIMEDES_WEBHOOK_URL")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_review_dispatch_idempotent() -> None:
    root = _make_temp_root()
    try:
        result = create_task_from_message(
            text="task: patch the risk calculation function v2",
            user="operator",
            lane="jarvis",
            channel="jarvis",
            message_id="dispatch_test_007",
            root=root,
        )
        route = result.get("route_result") or {}
        review_id = route.get("review_id")
        if not review_id:
            print("  ⚠ no review created — skipping review idempotency test")
            return

        import scripts.review_dispatch_to_discord as rd_mod
        sent_log = root / "state" / "logs" / "review_dispatch_sent.json"
        save_sent(sent_log, {review_id})

        orig_sent_log = rd_mod.SENT_LOG
        rd_mod.SENT_LOG = sent_log
        try:
            dispatch_result = run_review_dispatch(root, dry_run=True)
        finally:
            rd_mod.SENT_LOG = orig_sent_log

        assert review_id not in [d["id"] for d in dispatch_result["dispatched"]], \
            "already-sent review should be skipped"
        assert dispatch_result["skipped_count"] >= 1
        print("  ✓ review dispatch idempotency: already-sent items skipped")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_review_format_contains_verdict_commands() -> None:
    r = {
        "review_id": "rev_abc123",
        "task_id": "task_xyz",
        "reviewer_role": "archimedes",
        "summary": "Fix null check in login handler",
    }
    msg = _format_review_message(r)
    assert "rev_abc123" in msg
    assert "task_xyz" in msg
    assert "review_decision.py" in msg
    assert "--verdict approved" in msg
    assert "--verdict changes_requested" in msg
    print("  ✓ review message format contains verdict commands")


def test_approval_format_contains_decision_commands() -> None:
    a = {
        "approval_id": "appr_def456",
        "task_id": "task_xyz",
        "requested_reviewer": "anton",
        "summary": "Deploy NQ strategy runner restart",
    }
    msg = _format_approval_message(a)
    assert "appr_def456" in msg
    assert "task_xyz" in msg
    assert "approval_decision.py" in msg
    assert "--decision approved" in msg
    assert "--decision rejected" in msg
    print("  ✓ approval message format contains decision commands")


if __name__ == "__main__":
    tests = [
        test_load_save_sent_round_trip,
        test_load_sent_tolerates_corrupt_file,
        test_hal_dispatch_queued_code_task_dry_run,
        test_hal_dispatch_idempotent,
        test_hal_dispatch_excludes_deploy_tasks,
        test_hal_format_message_contains_key_fields,
        test_review_dispatch_dry_run_with_pending_review,
        test_review_dispatch_archimedes_routed_to_dedicated_webhook,
        test_review_dispatch_idempotent,
        test_review_format_contains_verdict_commands,
        test_approval_format_contains_decision_commands,
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
