"""Tests for explain_task_progress — queue position, eligibility, stage explanation."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.explain_task_progress import (
    _is_ralph_eligible,
    _build_ralph_queue,
    explain,
    render_terminal,
    render_compact,
)


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

class TestRalphEligibility:
    def test_ralph_adapter_eligible(self):
        task = {"status": "queued", "task_type": "general", "risk_level": "normal",
                "execution_backend": "ralph_adapter", "created_at": "2026-01-01T00:00:00+00:00"}
        ok, reason = _is_ralph_eligible(task)
        assert ok is True

    def test_deploy_blocked(self):
        task = {"status": "queued", "task_type": "deploy", "risk_level": "normal",
                "execution_backend": "ralph_adapter"}
        ok, reason = _is_ralph_eligible(task)
        assert ok is False
        assert "deploy" in reason

    def test_high_stakes_blocked(self):
        task = {"status": "queued", "task_type": "code", "risk_level": "high_stakes",
                "execution_backend": "ralph_adapter"}
        ok, reason = _is_ralph_eligible(task)
        assert ok is False
        assert "high_stakes" in reason

    def test_wrong_backend(self):
        task = {"status": "queued", "task_type": "general", "risk_level": "normal",
                "execution_backend": "browser_backend"}
        ok, reason = _is_ralph_eligible(task)
        assert ok is False
        assert "not in Ralph" in reason

    def test_qwen_executor_not_stale(self):
        from datetime import datetime, timezone
        now = datetime.now(tz=timezone.utc).isoformat()
        task = {"status": "queued", "task_type": "general", "risk_level": "normal",
                "execution_backend": "qwen_executor", "created_at": now}
        ok, reason = _is_ralph_eligible(task)
        assert ok is False
        assert "won't steal" in reason

    def test_not_queued(self):
        task = {"status": "running", "task_type": "general", "risk_level": "normal",
                "execution_backend": "ralph_adapter"}
        ok, reason = _is_ralph_eligible(task)
        assert ok is False
        assert "status" in reason


# ---------------------------------------------------------------------------
# Queue ordering
# ---------------------------------------------------------------------------

class TestQueueOrdering:
    def test_ralph_adapter_before_qwen(self):
        tasks = [
            {"task_id": "t_qwen", "status": "queued", "task_type": "general",
             "risk_level": "normal", "execution_backend": "qwen_executor",
             "created_at": "2020-01-01T00:00:00+00:00", "normalized_request": "old qwen",
             "final_outcome": "", "related_review_ids": [], "related_approval_ids": []},
            {"task_id": "t_ralph", "status": "queued", "task_type": "general",
             "risk_level": "normal", "execution_backend": "ralph_adapter",
             "created_at": "2026-01-01T00:00:00+00:00", "normalized_request": "newer ralph",
             "final_outcome": "", "related_review_ids": [], "related_approval_ids": []},
        ]
        queue = _build_ralph_queue(tasks)
        eligible = [q for q in queue if q["eligible"]]
        assert eligible[0]["task_id"] == "t_ralph"

    def test_oldest_first_within_group(self):
        tasks = [
            {"task_id": "t_new", "status": "queued", "task_type": "general",
             "risk_level": "normal", "execution_backend": "ralph_adapter",
             "created_at": "2026-01-02T00:00:00+00:00", "normalized_request": "newer",
             "final_outcome": "", "related_review_ids": [], "related_approval_ids": []},
            {"task_id": "t_old", "status": "queued", "task_type": "general",
             "risk_level": "normal", "execution_backend": "ralph_adapter",
             "created_at": "2026-01-01T00:00:00+00:00", "normalized_request": "older",
             "final_outcome": "", "related_review_ids": [], "related_approval_ids": []},
        ]
        queue = _build_ralph_queue(tasks)
        eligible = [q for q in queue if q["eligible"]]
        assert eligible[0]["task_id"] == "t_old"
        assert eligible[1]["task_id"] == "t_new"

    def test_ineligible_tasks_included_but_marked(self):
        tasks = [
            {"task_id": "t_deploy", "status": "queued", "task_type": "deploy",
             "risk_level": "normal", "execution_backend": "ralph_adapter",
             "created_at": "2026-01-01T00:00:00+00:00", "normalized_request": "deploy thing",
             "final_outcome": "", "related_review_ids": [], "related_approval_ids": []},
        ]
        queue = _build_ralph_queue(tasks)
        assert len(queue) == 1
        assert queue[0]["eligible"] is False
        assert "deploy" in queue[0]["ineligible_reason"]


# ---------------------------------------------------------------------------
# Explain function
# ---------------------------------------------------------------------------

class TestExplain:
    def test_task_not_found(self, tmp_path):
        state_dir = tmp_path / "state" / "tasks"
        state_dir.mkdir(parents=True)
        result = explain("task_nonexistent", root=tmp_path)
        assert result["ok"] is False

    def test_queued_task(self, tmp_path):
        state_dir = tmp_path / "state" / "tasks"
        state_dir.mkdir(parents=True)
        task = {
            "task_id": "task_abc",
            "status": "queued",
            "task_type": "general",
            "risk_level": "normal",
            "review_required": False,
            "approval_required": False,
            "execution_backend": "ralph_adapter",
            "source_channel": "todo",
            "source_user": "discord:test",
            "source_message_id": "discord:123",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "normalized_request": "test task",
            "final_outcome": "",
            "related_review_ids": [],
            "related_approval_ids": [],
        }
        (state_dir / "task_abc.json").write_text(json.dumps(task))
        result = explain("task_abc", root=tmp_path)
        assert result["ok"] is True
        assert result["status"] == "queued"
        assert result["ralph_eligible"] is True
        assert result["queue_position"] == 1
        assert "action" in result

    def test_completed_task(self, tmp_path):
        state_dir = tmp_path / "state" / "tasks"
        state_dir.mkdir(parents=True)
        task = {
            "task_id": "task_done",
            "status": "completed",
            "task_type": "general",
            "risk_level": "normal",
            "review_required": False,
            "approval_required": False,
            "execution_backend": "ralph_adapter",
            "source_channel": "",
            "source_user": "",
            "source_message_id": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T01:00:00+00:00",
            "final_outcome": "hal executed in 5s",
        }
        (state_dir / "task_done.json").write_text(json.dumps(task))
        result = explain("task_done", root=tmp_path)
        assert result["ok"] is True
        assert result["status"] == "completed"
        assert "Done" in result["action"]

    def test_failed_task_with_transient_error(self, tmp_path):
        state_dir = tmp_path / "state" / "tasks"
        state_dir.mkdir(parents=True)
        task = {
            "task_id": "task_fail",
            "status": "failed",
            "task_type": "general",
            "risk_level": "normal",
            "review_required": False,
            "approval_required": False,
            "execution_backend": "ralph_adapter",
            "source_channel": "",
            "source_user": "",
            "source_message_id": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T01:00:00+00:00",
            "last_error": "NVIDIA API timeout: connection refused",
            "error_count": 1,
        }
        (state_dir / "task_fail.json").write_text(json.dumps(task))
        result = explain("task_fail", root=tmp_path)
        assert result["ok"] is True
        assert result["looks_transient"] is True
        assert "--retry" in result["action"]


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

class TestRenderers:
    def test_terminal_renders_queued(self):
        data = {
            "ok": True,
            "task_id": "task_abc",
            "status": "queued",
            "stage_explanation": "Waiting in queue.",
            "task_type": "general",
            "risk_level": "normal",
            "review_required": False,
            "approval_required": False,
            "execution_backend": "ralph_adapter",
            "source_channel": "todo",
            "source_user": "op",
            "source_message_id": "",
            "created": "5m ago",
            "updated": "5m ago",
            "ralph_eligible": True,
            "queue_position": 2,
            "queue_total": 5,
            "ahead_in_queue": [{"task_id": "t_1", "backend": "ralph_adapter", "request": "older"}],
            "higher_priority_work": [],
            "action": "~1 cycle away",
        }
        output = render_terminal(data)
        assert "Queue position: 2 of 5" in output
        assert "task_abc" in output

    def test_compact_renders_position(self):
        data = {
            "ok": True,
            "task_id": "task_abc123456789",
            "status": "queued",
            "queue_position": 3,
            "queue_total": 7,
            "action": "~5 cycles away",
        }
        output = render_compact(data)
        assert "[3/7]" in output
        assert "queued" in output

    def test_error_render(self):
        data = {"ok": False, "error": "Task not found"}
        assert "not found" in render_terminal(data)
        assert "not found" in render_compact(data)
