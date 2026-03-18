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
    _fingerprint,
    _is_duplicate,
    _was_actionable,
    _save_fingerprint,
    _CLEAR_SENTINEL,
    collect,
    needs_attention,
    render_discord,
    render_recovery,
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


# ---------------------------------------------------------------------------
# Fingerprint / duplicate suppression
# ---------------------------------------------------------------------------

def test_fingerprint_stable():
    """Same data → same fingerprint."""
    data = {
        "approvals": [{"approval_id": "apr_001", "task_id": "t1", "request": "x"}],
        "failed": [{"task_id": "t2", "request": "y", "error": "timeout"}],
        "blocked": [],
        "timers": [{"unit": "x.timer", "label": "Ralph", "active": True}],
        "outbox": {"pending": 0, "failed": 0},
    }
    assert _fingerprint(data) == _fingerprint(data)


def test_fingerprint_changes_with_new_approval():
    data1 = {
        "approvals": [{"approval_id": "apr_001", "task_id": "t1", "request": "x"}],
        "failed": [], "blocked": [],
        "timers": [{"active": True, "unit": "x"}],
        "outbox": {"failed": 0},
    }
    data2 = {
        "approvals": [
            {"approval_id": "apr_001", "task_id": "t1", "request": "x"},
            {"approval_id": "apr_002", "task_id": "t2", "request": "y"},
        ],
        "failed": [], "blocked": [],
        "timers": [{"active": True, "unit": "x"}],
        "outbox": {"failed": 0},
    }
    assert _fingerprint(data1) != _fingerprint(data2)


def test_fingerprint_ignores_queue_changes():
    """Queue depth changes should NOT change the fingerprint — prevents spam."""
    data1 = {
        "approvals": [{"approval_id": "apr_001", "task_id": "t1", "request": "x"}],
        "queued": [{"task_id": "q1", "request": "a", "error": ""}],
        "failed": [], "blocked": [],
        "timers": [{"active": True, "unit": "x"}],
        "outbox": {"failed": 0},
    }
    data2 = {
        "approvals": [{"approval_id": "apr_001", "task_id": "t1", "request": "x"}],
        "queued": [
            {"task_id": "q1", "request": "a", "error": ""},
            {"task_id": "q2", "request": "b", "error": ""},
        ],
        "failed": [], "blocked": [],
        "timers": [{"active": True, "unit": "x"}],
        "outbox": {"failed": 0},
    }
    assert _fingerprint(data1) == _fingerprint(data2)


def test_duplicate_suppression_round_trip(tmp_path):
    """Save fingerprint, then verify is_duplicate detects it."""
    with patch("scripts.operator_status._state_dir", return_value=tmp_path):
        fp = "abc123"
        assert _is_duplicate(fp) is False
        _save_fingerprint(fp)
        assert _is_duplicate(fp) is True
        assert _is_duplicate("different") is False


# ---------------------------------------------------------------------------
# Recovery / all-clear logic
# ---------------------------------------------------------------------------

def test_was_actionable_false_when_no_file(tmp_path):
    with patch("scripts.operator_status._state_dir", return_value=tmp_path):
        assert _was_actionable() is False


def test_was_actionable_true_after_actionable_post(tmp_path):
    with patch("scripts.operator_status._state_dir", return_value=tmp_path):
        _save_fingerprint("some_real_hash")
        assert _was_actionable() is True


def test_was_actionable_false_after_clear(tmp_path):
    with patch("scripts.operator_status._state_dir", return_value=tmp_path):
        _save_fingerprint(_CLEAR_SENTINEL)
        assert _was_actionable() is False


def test_recovery_render_is_short():
    data = {
        "ts": "2026-03-18T21:30:00Z",
        "timers": [
            {"unit": "a", "label": "Ralph", "active": True},
            {"unit": "b", "label": "Gateway", "active": True},
        ],
        "queued": [{"task_id": "q1"}],
    }
    text = render_recovery(data)
    assert "All clear" in text
    assert "2 services OK" in text
    assert "1 queued" in text
    assert len(text) < 200  # must be very short


def test_recovery_not_repeated(tmp_path):
    """After a recovery post, _was_actionable() should be False → no repeat."""
    with patch("scripts.operator_status._state_dir", return_value=tmp_path):
        # Simulate: actionable state posted
        _save_fingerprint("actionable_hash_xyz")
        assert _was_actionable() is True
        # Simulate: recovery posted
        _save_fingerprint(_CLEAR_SENTINEL)
        assert _was_actionable() is False
