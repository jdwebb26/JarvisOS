"""test_ralph_v1.py — Focused tests for Ralph v1 bounded autonomy loop.

Tests:
  1. unhealthy system → cycle blocked, no task touched
  2. queued task → dispatched → review requested  (happy path smoke)
  3. review-ready task → approval requested       (happy path stage 2)
  4. no eligible tasks → idle result

Run: pytest tests/test_ralph_v1.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(
    task_id: str = "task_ralph_test_0001",
    status: str = "queued",
    execution_backend: str = "ralph_adapter",
    task_type: str = "general",
    risk_level: str = "normal",
    normalized_request: str = "test task: do a thing",
    review_required: bool = True,
    approval_required: bool = True,
) -> MagicMock:
    t = MagicMock()
    t.task_id = task_id
    t.status = status
    t.execution_backend = execution_backend
    t.task_type = task_type
    t.risk_level = risk_level
    t.normalized_request = normalized_request
    t.raw_request = normalized_request
    t.created_at = "2026-03-17T00:00:00+00:00"
    t.backend_assignment_id = "bassign_test"
    t.checkpoint_summary = ""
    t.parent_task_id = None
    t.final_outcome = ""
    t.related_review_ids = []
    t.related_approval_ids = []
    t.review_required = review_required
    t.approval_required = approval_required
    return t


def _make_review(review_id: str = "rev_test_001", status: str = "approved") -> MagicMock:
    r = MagicMock()
    r.review_id = review_id
    r.status = status
    r.verdict_reason = "Looks good"
    return r


def _make_approval(approval_id: str = "apr_test_001") -> MagicMock:
    a = MagicMock()
    a.approval_id = approval_id
    a.status = "pending"
    return a


# ---------------------------------------------------------------------------
# Test 1: unhealthy system → blocked, no task advanced
# ---------------------------------------------------------------------------

def test_unhealthy_system_blocks_cycle() -> None:
    """When any health gate fails, cycle returns blocked and no task is modified."""
    from runtime.ralph.agent_loop import run_cycle

    failing_gateway = {"ok": False, "gate": "gateway", "error": "connection refused"}
    passing_model = {"ok": True, "gate": "model_backend", "models": ["qwen3.5-35b-a3b"]}
    passing_hal = {"ok": True, "gate": "hal_status", "state": "idle"}
    passing_outbox = {"ok": True, "gate": "discord_outbox", "pending": 0, "failed": 0}

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        with (
            patch("runtime.ralph.agent_loop._load_env"),
            patch("runtime.ralph.agent_loop.run_health_gates",
                  return_value=(False, [failing_gateway, passing_model, passing_hal, passing_outbox])),
            patch("runtime.ralph.agent_loop.pick_review_ready_task") as mock_review,
            patch("runtime.ralph.agent_loop.pick_queued_task") as mock_queued,
            patch("runtime.ralph.agent_loop.emit_event", return_value={}),
        ):
            result = run_cycle(root)

    assert result["outcome"] == "blocked"
    assert result["stage"] == "health_gates"
    assert "gateway" in result["details"]

    # Neither task picker should have been called.
    mock_review.assert_not_called()
    mock_queued.assert_not_called()


def test_unhealthy_hal_blocks_cycle() -> None:
    """HAL in error state causes blocked outcome."""
    from runtime.ralph.agent_loop import run_cycle

    gates_unhealthy = [
        {"ok": True, "gate": "gateway"},
        {"ok": True, "gate": "model_backend", "models": ["qwen3.5-35b-a3b"]},
        {"ok": False, "gate": "hal_status", "error": "HAL state=error: task_wire_proof failed"},
        {"ok": True, "gate": "discord_outbox", "pending": 0, "failed": 0},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        with (
            patch("runtime.ralph.agent_loop._load_env"),
            patch("runtime.ralph.agent_loop.run_health_gates",
                  return_value=(False, gates_unhealthy)),
            patch("runtime.ralph.agent_loop.pick_review_ready_task") as mock_review,
            patch("runtime.ralph.agent_loop.emit_event", return_value={}),
        ):
            result = run_cycle(root)

    assert result["outcome"] == "blocked"
    assert "hal_status" in result["details"]
    mock_review.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: queued task → dispatched → review requested (happy path)
# ---------------------------------------------------------------------------

def test_queued_task_advances_to_review() -> None:
    """A queued ralph_adapter task is dispatched through HAL and review is requested."""
    from runtime.ralph.agent_loop import run_cycle

    task = _make_task()
    review = _make_review()

    healthy_gates = [
        {"ok": True, "gate": "gateway"},
        {"ok": True, "gate": "model_backend", "models": ["qwen3.5-35b-a3b"]},
        {"ok": True, "gate": "hal_status", "state": "idle"},
        {"ok": True, "gate": "discord_outbox", "pending": 0, "failed": 0},
    ]

    qwen_result = {
        "ok": True,
        "content": "## Result\nTask completed.\n## Output\nSome output.\n## Issues\nNone",
        "error": "",
        "elapsed": 3.14,
        "model": "qwen3.5-35b-a3b",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        with (
            patch("runtime.ralph.agent_loop._load_env"),
            patch("runtime.ralph.agent_loop.run_health_gates",
                  return_value=(True, healthy_gates)),
            patch("runtime.ralph.agent_loop.pick_review_ready_task", return_value=None),
            patch("runtime.ralph.agent_loop.pick_queued_task", return_value=task),
            patch("runtime.ralph.agent_loop.call_hal_via_qwen", return_value=qwen_result),
            patch("runtime.ralph.agent_loop._record_hal_result", return_value="bkres_test_001"),
            # task_runtime functions
            patch("runtime.ralph.agent_loop.stage_dispatch_and_review.func"
                  if hasattr(
                      __import__("runtime.ralph.agent_loop", fromlist=["stage_dispatch_and_review"]),
                      "__wrapped__"
                  ) else "runtime.ralph.agent_loop.stage_dispatch_and_review",
                  return_value=f"review_requested:{review.review_id}"),
        ):
            result = run_cycle(root)

    assert result["outcome"] == f"review_requested:{review.review_id}"
    assert result["stage"] == "dispatch_and_review"
    assert result["task_id"] == task.task_id


def test_queued_task_advances_to_review_via_stage() -> None:
    """Integration-style test: stage_dispatch_and_review with mocked runtime calls."""
    from runtime.ralph.agent_loop import stage_dispatch_and_review
    import runtime.ralph.agent_loop as _mod

    task = _make_task()
    review = _make_review()

    qwen_result = {
        "ok": True,
        "content": "## Result\nDone.\n## Output\nResult text.\n## Issues\nNone",
        "error": "",
        "elapsed": 1.0,
        "model": "qwen3.5-35b-a3b",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        with (
            patch.object(_mod, "call_hal_via_qwen", return_value=qwen_result),
            patch.object(_mod, "_record_hal_result", return_value="bkres_stage_test"),
            patch("runtime.core.task_store.load_task", return_value=task),
            patch("runtime.core.task_store.save_task", return_value=task),
            patch("runtime.core.task_runtime.start_task",
                  return_value={"status": "running", "task_id": task.task_id}),
            patch("runtime.core.task_runtime.complete_task",
                  return_value={"status": "completed", "task_id": task.task_id}),
            patch("runtime.core.task_runtime.fail_task",
                  return_value={"status": "failed", "task_id": task.task_id}),
            patch("runtime.core.task_runtime.block_task",
                  return_value={"status": "blocked", "task_id": task.task_id}),
            patch("runtime.core.review_store.request_review", return_value=review),
            patch("runtime.core.agent_status_store.update_agent_status", return_value={}),
        ):
            outcome = stage_dispatch_and_review(task, root=root)

    assert outcome.startswith("review_requested:"), f"Unexpected outcome: {outcome}"


# ---------------------------------------------------------------------------
# Test 3: review-ready task → approval requested (stage 2 happy path + guards)
# ---------------------------------------------------------------------------

def _run_stage_review_to_approval(
    task_status: str = "waiting_review",
    review_status: str = "approved",
    task_type: str = "general",
    risk_level: str = "normal",
    approval_required: bool = True,
) -> tuple[str, MagicMock, MagicMock]:
    """Helper: run stage_review_to_approval with configurable task/review state.

    Returns (outcome_str, mock_request_approval, mock_transition_task).
    The task loaded from store will match task_status/task_type/risk_level.
    """
    from runtime.ralph.agent_loop import stage_review_to_approval

    task = _make_task(
        status=task_status,
        task_type=task_type,
        risk_level=risk_level,
        approval_required=approval_required,
    )
    # The store-loaded "fresh" task mirrors the in-memory task.
    fresh = _make_task(
        status=task_status,
        task_type=task_type,
        risk_level=risk_level,
        approval_required=approval_required,
    )
    review = _make_review(status=review_status)
    approval = _make_approval()
    mock_request_approval = MagicMock(return_value=approval)
    mock_transition_task = MagicMock(return_value=fresh)

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with (
            patch("runtime.core.task_store.load_task", return_value=fresh),
            patch("runtime.core.review_store.latest_review_for_task", return_value=review),
            patch("runtime.core.review_store.choose_followup_approval_reviewer",
                  wraps=lambda t: "operator" if t.task_type not in {"deploy", "quant"} and t.risk_level != "high_stakes" else "anton"),
            patch("runtime.core.task_runtime.checkpoint_task", return_value={}),
            patch("runtime.core.approval_store.request_approval", mock_request_approval),
            patch("runtime.core.task_store.transition_task", mock_transition_task),
            patch("runtime.core.agent_status_store.update_agent_status", return_value=None),
        ):
            outcome = stage_review_to_approval(task, root=root)

    return outcome, mock_request_approval, mock_transition_task


def test_review_approved_advances_to_approval() -> None:
    """Happy path: approved review + approval_required=True → approval requested."""
    outcome, mock_apr, mock_trans = _run_stage_review_to_approval(approval_required=True)

    assert outcome.startswith("approval_requested:"), f"Unexpected: {outcome}"
    mock_apr.assert_called_once()
    call_kwargs = mock_apr.call_args.kwargs
    assert call_kwargs["requested_reviewer"] == "operator"
    assert call_kwargs["approval_type"] == "general"
    assert call_kwargs["requested_by"] == "ralph"
    mock_trans.assert_not_called()  # No direct completion


def test_review_approved_high_stakes_routes_to_anton() -> None:
    """High-stakes tasks route approval to anton, not operator."""
    outcome, mock_apr, _ = _run_stage_review_to_approval(risk_level="high_stakes", approval_required=True)

    assert outcome.startswith("approval_requested:"), f"Unexpected: {outcome}"
    call_kwargs = mock_apr.call_args.kwargs
    assert call_kwargs["requested_reviewer"] == "anton", (
        f"Expected anton but got {call_kwargs['requested_reviewer']}"
    )


def test_review_to_approval_blocked_if_task_not_in_waiting_review() -> None:
    """If task drifted out of waiting_review, stage returns blocked without side effects."""
    from runtime.ralph.agent_loop import stage_review_to_approval

    task = _make_task(status="waiting_review")
    fresh = _make_task(status="queued")  # Drifted to a different status
    review = _make_review(status="approved")
    mock_apr = MagicMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with (
            patch("runtime.core.task_store.load_task", return_value=fresh),
            patch("runtime.core.review_store.latest_review_for_task", return_value=review),
            patch("runtime.core.approval_store.request_approval", mock_apr),
        ):
            outcome = stage_review_to_approval(task, root=root)

    assert outcome.startswith("blocked:"), f"Expected blocked, got: {outcome}"
    assert "waiting_review" in outcome
    mock_apr.assert_not_called()


def test_review_to_approval_blocked_if_review_pending() -> None:
    """Pending review → blocked, no approval created."""
    outcome, mock_apr, _ = _run_stage_review_to_approval(review_status="pending")

    assert outcome.startswith("blocked:"), f"Expected blocked, got: {outcome}"
    assert "approved" in outcome.lower()
    mock_apr.assert_not_called()


def test_review_to_approval_blocked_if_review_rejected() -> None:
    """Rejected review → blocked, no approval created."""
    outcome, mock_apr, _ = _run_stage_review_to_approval(review_status="rejected")

    assert outcome.startswith("blocked:"), f"Expected blocked, got: {outcome}"
    mock_apr.assert_not_called()


def test_checkpoint_written_before_approval() -> None:
    """A checkpoint is recorded before the approval request is created."""
    from runtime.ralph.agent_loop import stage_review_to_approval

    task = _make_task(status="waiting_review")
    fresh = _make_task(status="waiting_review")
    review = _make_review(status="approved")
    approval = _make_approval()

    call_order: list[str] = []

    def track_checkpoint(**kwargs: Any) -> dict:
        call_order.append("checkpoint")
        return {}

    def track_approval(**kwargs: Any) -> MagicMock:
        call_order.append("approval")
        return approval

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with (
            patch("runtime.core.task_store.load_task", return_value=fresh),
            patch("runtime.core.review_store.latest_review_for_task", return_value=review),
            patch("runtime.core.review_store.choose_followup_approval_reviewer", return_value="operator"),
            patch("runtime.core.task_runtime.checkpoint_task", side_effect=track_checkpoint),
            patch("runtime.core.approval_store.request_approval", side_effect=track_approval),
        ):
            outcome = stage_review_to_approval(task, root=root)

    assert outcome.startswith("approval_requested:"), f"Unexpected: {outcome}"
    assert call_order == ["checkpoint", "approval"], (
        f"Expected checkpoint before approval, got: {call_order}"
    )


# ---------------------------------------------------------------------------
# Test 3b: approval_required gate in review_to_approval
# ---------------------------------------------------------------------------

def test_review_approved_no_approval_required_completes_directly() -> None:
    """approval_required=False + approved review → task completes directly, no approval."""
    outcome, mock_apr, mock_trans = _run_stage_review_to_approval(
        approval_required=False,
    )

    assert outcome.startswith("review_complete:"), f"Unexpected: {outcome}"
    mock_apr.assert_not_called()  # No approval requested
    mock_trans.assert_called_once()
    call_kwargs = mock_trans.call_args.kwargs if mock_trans.call_args.kwargs else {}
    call_args = mock_trans.call_args
    # transition_task called with to_status="completed"
    assert call_args[1]["to_status"] == "completed" if len(call_args) > 1 else call_kwargs.get("to_status") == "completed"


def test_review_approved_with_approval_required_requests_approval() -> None:
    """approval_required=True + approved review → approval requested (standard path)."""
    outcome, mock_apr, mock_trans = _run_stage_review_to_approval(
        approval_required=True,
    )

    assert outcome.startswith("approval_requested:"), f"Unexpected: {outcome}"
    mock_apr.assert_called_once()
    mock_trans.assert_not_called()  # No direct completion


def test_code_task_with_review_and_no_approval_completes_after_review() -> None:
    """Code task (review_required=True, approval_required=False) completes after review."""
    outcome, mock_apr, mock_trans = _run_stage_review_to_approval(
        task_type="code",
        risk_level="normal",
        approval_required=False,
    )

    # Should complete directly, not request approval
    assert outcome.startswith("review_complete:"), f"Unexpected: {outcome}"
    mock_apr.assert_not_called()
    mock_trans.assert_called_once()


# ---------------------------------------------------------------------------
# Test 4: no eligible tasks → idle
# ---------------------------------------------------------------------------

def test_idle_when_no_eligible_tasks() -> None:
    """When no tasks are queued or review-ready, cycle returns idle."""
    from runtime.ralph.agent_loop import run_cycle

    healthy_gates = [
        {"ok": True, "gate": "gateway"},
        {"ok": True, "gate": "model_backend", "models": ["qwen3.5-35b-a3b"]},
        {"ok": True, "gate": "hal_status", "state": "idle"},
        {"ok": True, "gate": "discord_outbox", "pending": 0, "failed": 0},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        with (
            patch("runtime.ralph.agent_loop._load_env"),
            patch("runtime.ralph.agent_loop.run_health_gates",
                  return_value=(True, healthy_gates)),
            patch("runtime.ralph.agent_loop.pick_review_ready_task", return_value=None),
            patch("runtime.ralph.agent_loop.pick_queued_task", return_value=None),
            patch("runtime.ralph.agent_loop.emit_event", return_value={}),
        ):
            result = run_cycle(root)

    assert result["outcome"] == "idle"
    assert result["stage"] == "idle"


# ---------------------------------------------------------------------------
# Test 5: HAL failure → task marked failed
# ---------------------------------------------------------------------------

def test_hal_failure_marks_task_failed() -> None:
    """When Qwen/HAL returns an error, the task is marked failed and cycle exits."""
    from runtime.ralph.agent_loop import stage_dispatch_and_review

    task = _make_task()
    qwen_fail = {"ok": False, "content": "", "error": "timeout", "elapsed": 30.0, "model": "qwen3.5-35b-a3b"}

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        fail_result = {"status": "failed", "task_id": task.task_id}

        import runtime.ralph.agent_loop as _mod
        with (
            patch.object(_mod, "call_hal_via_qwen", return_value=qwen_fail),
            patch.object(_mod, "_record_hal_result", return_value="bkres_fail_test"),
            patch("runtime.core.task_store.load_task", return_value=task),
            patch("runtime.core.task_store.save_task", return_value=task),
            patch("runtime.core.task_runtime.start_task",
                  return_value={"status": "running", "task_id": task.task_id}),
            patch("runtime.core.task_runtime.fail_task", return_value=fail_result) as mock_fail,
            patch("runtime.core.agent_status_store.update_agent_status", return_value={}),
        ):
            outcome = stage_dispatch_and_review(task, root=root)

    assert outcome.startswith("failed:hal:"), f"Unexpected outcome: {outcome}"
    mock_fail.assert_called_once()


# ---------------------------------------------------------------------------
# Test 6: eligibility filtering
# ---------------------------------------------------------------------------

def test_high_stakes_deploy_not_eligible() -> None:
    """High-stakes deploy tasks are never picked up by Ralph v1."""
    from runtime.ralph.agent_loop import _is_eligible_queued

    task = _make_task(task_type="deploy", risk_level="high_stakes")

    with tempfile.TemporaryDirectory() as tmpdir:
        eligible, reason = _is_eligible_queued(task, root=Path(tmpdir))

    assert not eligible
    assert "blocked" in reason


def test_ralph_adapter_task_is_eligible() -> None:
    """ralph_adapter tasks are immediately eligible."""
    from runtime.ralph.agent_loop import _is_eligible_queued

    task = _make_task(execution_backend="ralph_adapter")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Patch dependency check to pass cleanly.
        with patch("runtime.core.task_store.task_dependency_summary",
                   return_value={"hard_block": False, "reason": ""}):
            eligible, reason = _is_eligible_queued(task, root=Path(tmpdir))

    assert eligible, f"Expected eligible but got: {reason}"


def test_qwen_executor_task_not_eligible_when_fresh() -> None:
    """qwen_executor tasks are not stolen until they're stale."""
    from runtime.ralph.agent_loop import _is_eligible_queued
    import datetime

    task = _make_task(execution_backend="qwen_executor")
    # Fresh task: created 30s ago
    recent = (datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(seconds=30)).isoformat()
    task.created_at = recent

    with tempfile.TemporaryDirectory() as tmpdir:
        eligible, reason = _is_eligible_queued(task, root=Path(tmpdir))

    assert not eligible
    assert "stale" in reason


# ---------------------------------------------------------------------------
# Test 7: post-approval re-queue guard (defense-in-depth)
# ---------------------------------------------------------------------------

def test_completed_reviewed_approved_task_not_eligible() -> None:
    """A task with final_outcome + review + approval is never eligible for re-dispatch."""
    from runtime.ralph.agent_loop import _is_eligible_queued

    task = _make_task(execution_backend="ralph_adapter")
    task.final_outcome = "HAL executed via Qwen in 28.73s."
    task.related_review_ids = ["rev_test_001"]
    task.related_approval_ids = ["apr_test_001"]

    with tempfile.TemporaryDirectory() as tmpdir:
        eligible, reason = _is_eligible_queued(task, root=Path(tmpdir))

    assert not eligible, f"Expected ineligible but got eligible"
    assert "re-queue guard" in reason


def test_task_without_approval_is_still_eligible() -> None:
    """A queued task with final_outcome but no approval is still eligible (retry case)."""
    from runtime.ralph.agent_loop import _is_eligible_queued

    task = _make_task(execution_backend="ralph_adapter")
    task.final_outcome = "HAL executed."
    task.related_review_ids = ["rev_test_001"]
    task.related_approval_ids = []  # No approval yet

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("runtime.core.task_store.task_dependency_summary",
                   return_value={"hard_block": False, "reason": ""}):
            eligible, reason = _is_eligible_queued(task, root=Path(tmpdir))

    assert eligible, f"Expected eligible (retry case) but got: {reason}"


# ---------------------------------------------------------------------------
# Test 8: _choose_resume_target and approval resume behavior
# ---------------------------------------------------------------------------

def test_choose_resume_target_ralph_completed() -> None:
    """Ralph-owned task with final_outcome → resume to COMPLETED."""
    from runtime.core.approval_store import _choose_resume_target

    task = MagicMock()
    task.execution_backend = "ralph_adapter"
    task.final_outcome = "HAL executed via Qwen in 28.73s."

    assert _choose_resume_target(task) == "completed"


def test_choose_resume_target_live_apply() -> None:
    """Task with candidate_ready_for_live_apply → resume to READY_TO_SHIP."""
    from runtime.core.approval_store import _choose_resume_target

    task = MagicMock()
    task.execution_backend = "qwen_executor"
    task.final_outcome = "candidate_ready_for_live_apply"

    assert _choose_resume_target(task) == "ready_to_ship"


def test_choose_resume_target_normal_queued() -> None:
    """Non-Ralph task without live_apply → resume to QUEUED."""
    from runtime.core.approval_store import _choose_resume_target

    task = MagicMock()
    task.execution_backend = "qwen_executor"
    task.final_outcome = "some other outcome"

    assert _choose_resume_target(task) == "queued"


def test_choose_resume_target_ralph_no_outcome() -> None:
    """Ralph task without final_outcome → resume to QUEUED (re-execute needed)."""
    from runtime.core.approval_store import _choose_resume_target

    task = MagicMock()
    task.execution_backend = "ralph_adapter"
    task.final_outcome = ""

    assert _choose_resume_target(task) == "queued"


# ---------------------------------------------------------------------------
# Test 9: review verdict contract — Ralph-owned tasks
# ---------------------------------------------------------------------------

def test_review_verdict_ralph_task_no_transition() -> None:
    """record_review_verdict on a ralph_adapter task must NOT transition the task.

    Ralph's cycle handles review→approval. The verdict function should save the
    review verdict, write provenance/events/Discord, but skip the task transition.
    """
    from runtime.core.review_store import record_review_verdict

    task = _make_task(status="waiting_review", execution_backend="ralph_adapter")
    task.approval_required = False
    task.lifecycle_state = "working"
    task.normalized_request = "test request for review"
    task.promoted_artifact_id = None

    review = _make_review(review_id="rev_verdict_test", status="pending")

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with (
            patch("runtime.core.review_store.load_review", return_value=review),
            patch("runtime.core.review_store.save_review", return_value=review),
            patch("runtime.core.review_store.load_task", return_value=task),
            patch("runtime.core.review_store.select_task_artifact", return_value=None),
            patch("runtime.core.review_store.add_review_link"),
            patch("runtime.core.review_store.transition_task") as mock_transition,
            patch("runtime.core.review_store.save_decision_provenance"),
            patch("runtime.core.review_store.append_event"),
            patch("runtime.core.review_store.make_event", return_value=MagicMock()),
            patch("runtime.core.review_store.rebuild_all_outputs"),
        ):
            result = record_review_verdict(
                review_id="rev_verdict_test",
                verdict="approved",
                actor="archimedes",
                lane="review",
                reason="Looks good",
                root=root,
            )

    assert result.status == "approved"
    mock_transition.assert_not_called(), "Ralph-owned task must NOT be transitioned by verdict"


def test_review_verdict_non_ralph_task_transitions_normally() -> None:
    """record_review_verdict on a non-Ralph task with approval_required=False
    transitions to queued (existing behavior preserved)."""
    from runtime.core.review_store import record_review_verdict

    task = _make_task(status="waiting_review", execution_backend="qwen_executor")
    task.approval_required = False
    task.lifecycle_state = "working"
    task.normalized_request = "test request for review"
    task.promoted_artifact_id = None

    review = _make_review(review_id="rev_verdict_nonralph", status="pending")

    transition_result = MagicMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with (
            patch("runtime.core.review_store.load_review", return_value=review),
            patch("runtime.core.review_store.save_review", return_value=review),
            patch("runtime.core.review_store.load_task", return_value=task),
            patch("runtime.core.review_store.select_task_artifact", return_value=None),
            patch("runtime.core.review_store.add_review_link"),
            patch("runtime.core.review_store.transition_task", return_value=transition_result) as mock_transition,
            patch("runtime.core.review_store.save_decision_provenance"),
            patch("runtime.core.review_store.append_event"),
            patch("runtime.core.review_store.make_event", return_value=MagicMock()),
            patch("runtime.core.review_store.rebuild_all_outputs"),
        ):
            record_review_verdict(
                review_id="rev_verdict_nonralph",
                verdict="approved",
                actor="archimedes",
                lane="review",
                reason="Looks good",
                root=root,
            )

    mock_transition.assert_called_once()
    call_kwargs = mock_transition.call_args.kwargs
    assert call_kwargs["to_status"] == "queued"


# ---------------------------------------------------------------------------
# Test 10: Archimedes auto-review stage
# ---------------------------------------------------------------------------

def test_auto_review_approved_records_verdict() -> None:
    """stage_auto_review calls Qwen reviewer and records approved verdict."""
    from runtime.ralph.agent_loop import stage_auto_review
    import runtime.ralph.agent_loop as _mod

    task = _make_task(status="waiting_review")
    review = _make_review(review_id="rev_auto_test", status="pending")

    archimedes_result = {
        "approved": True,
        "reason": "Output is accurate and well-structured.",
        "elapsed": 2.5,
        "model": "qwen3.5-35b-a3b",
    }

    mock_verdict = MagicMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with (
            patch("runtime.core.task_store.load_task", return_value=task),
            patch("runtime.core.review_store.latest_review_for_task", return_value=review),
            patch.object(_mod, "call_archimedes_via_qwen", return_value=archimedes_result),
            patch("runtime.core.review_store.record_review_verdict", mock_verdict),
        ):
            outcome = stage_auto_review(task, root=root)

    assert outcome.startswith("review_approved:"), f"Unexpected: {outcome}"
    mock_verdict.assert_called_once()
    call_kwargs = mock_verdict.call_args.kwargs
    assert call_kwargs["verdict"] == "approved"
    assert call_kwargs["actor"] == "archimedes"


def test_auto_review_rejected_records_verdict() -> None:
    """stage_auto_review records rejected verdict when reviewer rejects."""
    from runtime.ralph.agent_loop import stage_auto_review
    import runtime.ralph.agent_loop as _mod

    task = _make_task(status="waiting_review")
    review = _make_review(review_id="rev_auto_reject", status="pending")

    archimedes_result = {
        "approved": False,
        "reason": "Output does not address the task requirements.",
        "elapsed": 1.8,
        "model": "qwen3.5-35b-a3b",
    }

    mock_verdict = MagicMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with (
            patch("runtime.core.task_store.load_task", return_value=task),
            patch("runtime.core.review_store.latest_review_for_task", return_value=review),
            patch.object(_mod, "call_archimedes_via_qwen", return_value=archimedes_result),
            patch("runtime.core.review_store.record_review_verdict", mock_verdict),
        ):
            outcome = stage_auto_review(task, root=root)

    assert outcome.startswith("review_rejected:"), f"Unexpected: {outcome}"
    mock_verdict.assert_called_once()
    assert mock_verdict.call_args.kwargs["verdict"] == "rejected"


def test_auto_review_transport_error_no_verdict() -> None:
    """Model transport errors must NOT record a verdict — task stays reviewable."""
    from runtime.ralph.agent_loop import stage_auto_review
    import runtime.ralph.agent_loop as _mod

    task = _make_task(status="waiting_review")
    review = _make_review(review_id="rev_auto_err", status="pending")

    error_result = {
        "approved": None,
        "error": True,
        "reason": "Model error: http 400",
        "elapsed": 0.5,
        "model": "qwen3.5-35b-a3b",
    }
    mock_verdict = MagicMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with (
            patch("runtime.core.task_store.load_task", return_value=task),
            patch("runtime.core.review_store.latest_review_for_task", return_value=review),
            patch.object(_mod, "call_archimedes_via_qwen", return_value=error_result),
            patch("runtime.core.review_store.record_review_verdict", mock_verdict),
        ):
            outcome = stage_auto_review(task, root=root)

    assert outcome.startswith("failed:archimedes_error:"), f"Unexpected: {outcome}"
    mock_verdict.assert_not_called()  # No verdict recorded on transport error


def test_auto_review_skips_non_pending_review() -> None:
    """stage_auto_review returns blocked if review is not pending."""
    from runtime.ralph.agent_loop import stage_auto_review

    task = _make_task(status="waiting_review")
    review = _make_review(review_id="rev_already_done", status="approved")

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with (
            patch("runtime.core.task_store.load_task", return_value=task),
            patch("runtime.core.review_store.latest_review_for_task", return_value=review),
        ):
            outcome = stage_auto_review(task, root=root)

    assert outcome.startswith("blocked:"), f"Expected blocked, got: {outcome}"


def test_auto_review_stage_in_cycle_priority() -> None:
    """Auto-review runs between review-ready and queued stages."""
    from runtime.ralph.agent_loop import run_cycle

    task = _make_task(status="waiting_review")

    healthy_gates = [
        {"ok": True, "gate": "gateway"},
        {"ok": True, "gate": "model_backend", "models": ["qwen3.5-35b-a3b"]},
        {"ok": True, "gate": "hal_status", "state": "idle"},
        {"ok": True, "gate": "discord_outbox", "pending": 0, "failed": 0},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with (
            patch("runtime.ralph.agent_loop._load_env"),
            patch("runtime.ralph.agent_loop.run_health_gates",
                  return_value=(True, healthy_gates)),
            patch("runtime.ralph.agent_loop.pick_review_ready_task", return_value=None),
            patch("runtime.ralph.agent_loop.pick_pending_review_task", return_value=task),
            patch("runtime.ralph.agent_loop.stage_auto_review",
                  return_value="review_approved:rev_test") as mock_stage,
            patch("runtime.ralph.agent_loop.pick_queued_task") as mock_queued,
        ):
            result = run_cycle(root)

    assert result["stage"] == "auto_review"
    assert result["outcome"] == "review_approved:rev_test"
    mock_stage.assert_called_once()
    mock_queued.assert_not_called()  # auto_review took priority


# ---------------------------------------------------------------------------
# Test 11: stale-running recovery
# ---------------------------------------------------------------------------

def test_recover_stale_running_task() -> None:
    """A Ralph-owned task stuck in 'running' beyond threshold is failed."""
    from runtime.ralph.agent_loop import recover_stale_running
    import datetime

    task = _make_task(status="running", execution_backend="ralph_adapter")
    # Updated 20 minutes ago — well past STALE_RUNNING_SECONDS (600s)
    old = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(seconds=1200)
    task.updated_at = old.isoformat()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with (
            patch("runtime.core.task_store.list_tasks", return_value=[task]),
            patch("runtime.core.task_runtime.fail_task",
                  return_value={"status": "failed"}) as mock_fail,
            patch("runtime.ralph.agent_loop.emit_event", return_value={}),
        ):
            recovered = recover_stale_running(root)

    assert recovered == task.task_id
    mock_fail.assert_called_once()
    assert "Stale-running recovery" in mock_fail.call_args.kwargs["reason"]


def test_recent_running_task_not_recovered() -> None:
    """A task running for less than the threshold is NOT recovered."""
    from runtime.ralph.agent_loop import recover_stale_running
    import datetime

    task = _make_task(status="running", execution_backend="ralph_adapter")
    # Updated 30 seconds ago — well within threshold
    recent = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(seconds=30)
    task.updated_at = recent.isoformat()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with patch("runtime.core.task_store.list_tasks", return_value=[task]):
            recovered = recover_stale_running(root)

    assert recovered is None


def test_non_ralph_running_task_not_recovered() -> None:
    """Only ralph_adapter tasks are recovered."""
    from runtime.ralph.agent_loop import recover_stale_running
    import datetime

    task = _make_task(status="running", execution_backend="qwen_executor")
    old = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(seconds=1200)
    task.updated_at = old.isoformat()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with patch("runtime.core.task_store.list_tasks", return_value=[task]):
            recovered = recover_stale_running(root)

    assert recovered is None


# ---------------------------------------------------------------------------
# Test 12: retry / requeue
# ---------------------------------------------------------------------------

def test_retry_failed_task_requeues() -> None:
    """retry_task requeues a failed Ralph task and clears error state."""
    from runtime.ralph.agent_loop import retry_task

    task = _make_task(status="failed", execution_backend="ralph_adapter")
    task.error_count = 2
    task.last_error = "HAL execution failed"
    task.final_outcome = "old outcome"
    task.related_review_ids = ["rev_old"]
    task.related_approval_ids = ["apr_old"]

    mock_transition = MagicMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with (
            patch("runtime.core.task_store.load_task", return_value=task),
            patch("runtime.core.task_store.save_task", return_value=task) as mock_save,
            patch("runtime.core.task_store.transition_task", mock_transition),
        ):
            result = retry_task(task.task_id, root=root)

    assert result["ok"] is True
    assert result["previous_status"] == "failed"
    assert result["new_status"] == "queued"

    # Error state should be cleared before transition
    assert task.error_count == 0
    assert task.last_error == ""
    assert task.final_outcome == ""
    assert task.related_review_ids == []
    assert task.related_approval_ids == []
    mock_save.assert_called_once()
    mock_transition.assert_called_once()


def test_retry_blocked_task_requeues() -> None:
    """retry_task also works for blocked tasks."""
    from runtime.ralph.agent_loop import retry_task

    task = _make_task(status="blocked", execution_backend="ralph_adapter")

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with (
            patch("runtime.core.task_store.load_task", return_value=task),
            patch("runtime.core.task_store.save_task", return_value=task),
            patch("runtime.core.task_store.transition_task", MagicMock()),
        ):
            result = retry_task(task.task_id, root=root)

    assert result["ok"] is True
    assert result["previous_status"] == "blocked"


def test_retry_non_ralph_task_rejected() -> None:
    """retry_task rejects non-Ralph tasks."""
    from runtime.ralph.agent_loop import retry_task

    task = _make_task(status="failed", execution_backend="qwen_executor")

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with patch("runtime.core.task_store.load_task", return_value=task):
            result = retry_task(task.task_id, root=root)

    assert result["ok"] is False
    assert "Not a Ralph-owned task" in result["error"]


def test_retry_running_task_rejected() -> None:
    """retry_task rejects tasks not in failed/blocked status."""
    from runtime.ralph.agent_loop import retry_task

    task = _make_task(status="running", execution_backend="ralph_adapter")

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with patch("runtime.core.task_store.load_task", return_value=task):
            result = retry_task(task.task_id, root=root)

    assert result["ok"] is False
    assert "running" in result["error"]
