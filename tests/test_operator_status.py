"""test_operator_status.py — Tests for operator_status data collection and rendering."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_status import (
    _pending_approvals,
    _actionable_tasks,
    _outbox_health,
    collect,
    needs_attention,
    render_discord,
    render_terminal,
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n")


def _make_state(tmpdir: Path) -> None:
    """Create a minimal state directory for testing."""
    # One pending approval with task in waiting_approval
    _write_json(tmpdir / "state/approvals/apr_001.json", {
        "approval_id": "apr_001",
        "task_id": "task_001",
        "status": "pending",
    })
    _write_json(tmpdir / "state/tasks/task_001.json", {
        "task_id": "task_001",
        "status": "waiting_approval",
        "normalized_request": "Fix the login bug",
        "last_error": "",
    })

    # Stale approval: task completed — should be filtered out
    _write_json(tmpdir / "state/approvals/apr_002.json", {
        "approval_id": "apr_002",
        "task_id": "task_002",
        "status": "pending",
    })
    _write_json(tmpdir / "state/tasks/task_002.json", {
        "task_id": "task_002",
        "status": "completed",
        "normalized_request": "Old completed task",
        "last_error": "",
    })

    # Stale approval: task in waiting_review — should be filtered out
    _write_json(tmpdir / "state/approvals/apr_003.json", {
        "approval_id": "apr_003",
        "task_id": "task_003",
        "status": "pending",
    })
    _write_json(tmpdir / "state/tasks/task_003.json", {
        "task_id": "task_003",
        "status": "waiting_review",
        "normalized_request": "Regressed to review",
        "last_error": "",
    })

    # Already-decided approval — should be filtered out
    _write_json(tmpdir / "state/approvals/apr_004.json", {
        "approval_id": "apr_004",
        "task_id": "task_004",
        "status": "approved",
    })

    # Queued task
    _write_json(tmpdir / "state/tasks/task_010.json", {
        "task_id": "task_010",
        "status": "queued",
        "normalized_request": "Say hello",
        "last_error": "",
    })

    # Failed task
    _write_json(tmpdir / "state/tasks/task_011.json", {
        "task_id": "task_011",
        "status": "failed",
        "normalized_request": "Browse website",
        "last_error": "tab_open_failed",
    })

    # Blocked task
    _write_json(tmpdir / "state/tasks/task_012.json", {
        "task_id": "task_012",
        "status": "blocked",
        "normalized_request": "Search VIX",
        "last_error": "",
    })

    # Outbox: one pending, one failed
    _write_json(tmpdir / "state/discord_outbox/outbox_a.json", {"status": "pending"})
    _write_json(tmpdir / "state/discord_outbox/outbox_b.json", {"status": "failed"})
    _write_json(tmpdir / "state/discord_outbox/outbox_c.json", {"status": "delivered"})


def test_pending_approvals_filters_stale():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        with patch("scripts.operator_status.ROOT", root):
            approvals = _pending_approvals()
    # Only apr_001 (task in waiting_approval) should remain
    assert len(approvals) == 1
    assert approvals[0]["approval_id"] == "apr_001"


def test_actionable_tasks_groups_correctly():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        with patch("scripts.operator_status.ROOT", root):
            tasks = _actionable_tasks()
    assert len(tasks["queued"]) == 1
    assert len(tasks["failed"]) == 1
    assert len(tasks["blocked"]) == 1
    assert tasks["queued"][0]["task_id"] == "task_010"
    assert tasks["failed"][0]["task_id"] == "task_011"
    assert tasks["blocked"][0]["task_id"] == "task_012"


def test_outbox_health_counts():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        with patch("scripts.operator_status.ROOT", root):
            health = _outbox_health()
    assert health["pending"] == 1
    assert health["failed"] == 1


def test_needs_attention_true_with_approvals():
    data = {
        "approvals": [{"approval_id": "apr_001"}],
        "failed": [],
        "timers": [{"active": True}],
        "outbox": {"failed": 0},
    }
    assert needs_attention(data) is True


def test_needs_attention_true_with_failed_tasks():
    data = {
        "approvals": [],
        "failed": [{"task_id": "task_011"}],
        "timers": [{"active": True}],
        "outbox": {"failed": 0},
    }
    assert needs_attention(data) is True


def test_needs_attention_true_with_service_down():
    data = {
        "approvals": [],
        "failed": [],
        "timers": [{"active": False, "label": "Ralph"}],
        "outbox": {"failed": 0},
    }
    assert needs_attention(data) is True


def test_needs_attention_false_when_clear():
    data = {
        "approvals": [],
        "failed": [],
        "timers": [{"active": True}],
        "outbox": {"failed": 0},
    }
    assert needs_attention(data) is False


def test_render_terminal_contains_key_sections():
    data = {
        "ts": "2026-03-18T21:00:00Z",
        "approvals": [{"approval_id": "apr_001", "task_id": "task_001", "request": "Fix bug"}],
        "queued": [{"task_id": "task_010", "request": "Say hello", "error": ""}],
        "blocked": [],
        "failed": [{"task_id": "task_011", "request": "Browse", "error": "tab_open_failed"}],
        "timers": [{"unit": "x.timer", "label": "Ralph", "active": True}],
        "outbox": {"pending": 0, "failed": 0},
    }
    text = render_terminal(data)
    assert "APPROVALS" in text
    assert "FAILED" in text
    assert "QUEUE" in text
    assert "--approve" in text
    assert "--retry" in text


def test_render_discord_phone_length():
    data = {
        "ts": "2026-03-18T21:00:00Z",
        "approvals": [{"approval_id": "apr_001", "task_id": "task_001", "request": "Fix bug"}],
        "queued": [],
        "blocked": [],
        "failed": [],
        "timers": [{"unit": "x.timer", "label": "Ralph", "active": True}],
        "outbox": {"pending": 0, "failed": 0},
    }
    text = render_discord(data)
    assert len(text) < 2000  # Discord message limit
    assert "Operator Status" in text
    assert "pending approval" in text


def test_render_discord_nothing_needed():
    data = {
        "ts": "2026-03-18T21:00:00Z",
        "approvals": [],
        "queued": [],
        "blocked": [],
        "failed": [],
        "timers": [{"unit": "x.timer", "label": "Ralph", "active": True}],
        "outbox": {"pending": 0, "failed": 0},
    }
    text = render_discord(data)
    assert "Nothing needs attention" in text
