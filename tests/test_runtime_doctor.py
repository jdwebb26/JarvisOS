"""test_runtime_doctor.py — Tests for runtime_doctor checks."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runtime_doctor import (
    check_units,
    check_systemd_drift,
    check_outbox,
    check_action_backlog,
    run_all_checks,
    render_terminal,
)


# ---------------------------------------------------------------------------
# check_units
# ---------------------------------------------------------------------------

def test_check_units_all_active():
    with patch("scripts.runtime_doctor._systemctl", return_value="active"):
        results = check_units()
    assert all(r["level"] == "pass" for r in results)
    assert len(results) == 7


def test_check_units_one_down():
    def mock_systemctl(cmd):
        unit = cmd[-1] if cmd else ""
        return "inactive" if "ralph" in unit else "active"

    with patch("scripts.runtime_doctor._systemctl", side_effect=mock_systemctl):
        results = check_units()
    fails = [r for r in results if r["level"] == "fail"]
    assert len(fails) == 1
    assert "ralph" in fails[0]["check"]
    assert fails[0]["fix"]  # has a fix command


# ---------------------------------------------------------------------------
# check_systemd_drift
# ---------------------------------------------------------------------------

def test_drift_clean():
    with (
        patch("scripts.sync_systemd_units.discover_repo_units", return_value=[MagicMock(name=f"u{i}.service") for i in range(10)]),
        patch("scripts.sync_systemd_units.compute_plan", return_value=[]),
    ):
        results = check_systemd_drift()
    assert len(results) == 1
    assert results[0]["level"] == "pass"
    assert "0 drifted" in results[0]["detail"]


def test_drift_detected():
    with (
        patch("scripts.sync_systemd_units.discover_repo_units", return_value=[]),
        patch("scripts.sync_systemd_units.compute_plan", return_value=[
            {"name": "foo.timer", "action": "update"},
        ]),
    ):
        results = check_systemd_drift()
    assert results[0]["level"] == "warn"
    assert "foo.timer" in results[0]["detail"]


# ---------------------------------------------------------------------------
# check_outbox
# ---------------------------------------------------------------------------

def test_outbox_healthy():
    with patch("scripts.operator_status._outbox_health", return_value={"pending": 2, "failed": 0}):
        results = check_outbox()
    assert results[0]["level"] == "pass"


def test_outbox_warn():
    with patch("scripts.operator_status._outbox_health", return_value={"pending": 3, "failed": 8}):
        results = check_outbox()
    assert results[0]["level"] == "warn"


def test_outbox_critical():
    with patch("scripts.operator_status._outbox_health", return_value={"pending": 0, "failed": 25}):
        results = check_outbox()
    assert results[0]["level"] == "fail"


# ---------------------------------------------------------------------------
# check_action_backlog
# ---------------------------------------------------------------------------

def test_backlog_clean():
    with (
        patch("scripts.operator_status._pending_approvals", return_value=[]),
        patch("scripts.operator_status._actionable_tasks", return_value={"queued": [], "blocked": [], "failed": []}),
    ):
        results = check_action_backlog()
    assert all(r["level"] == "pass" for r in results)


def test_backlog_with_approvals():
    with (
        patch("scripts.operator_status._pending_approvals", return_value=[
            {"approval_id": "apr_001", "task_id": "task_001", "request": "Fix bug"},
        ]),
        patch("scripts.operator_status._actionable_tasks", return_value={"queued": [], "blocked": [], "failed": []}),
    ):
        results = check_action_backlog()
    approval_check = [r for r in results if r["check"] == "approvals"][0]
    assert approval_check["level"] == "warn"
    assert "1 waiting" in approval_check["detail"]
    assert "--approve" in approval_check["fix"]


# ---------------------------------------------------------------------------
# run_all_checks verdict logic
# ---------------------------------------------------------------------------

def test_verdict_pass():
    with (
        patch("scripts.runtime_doctor.check_units", return_value=[{"level": "pass", "check": "a", "label": "A", "detail": "ok", "fix": ""}]),
        patch("scripts.runtime_doctor.check_http", return_value=[{"level": "pass", "check": "b", "label": "B", "detail": "ok", "fix": ""}]),
        patch("scripts.runtime_doctor.check_systemd_drift", return_value=[{"level": "pass", "check": "c", "label": "C", "detail": "ok", "fix": ""}]),
        patch("scripts.runtime_doctor.check_outbox", return_value=[{"level": "pass", "check": "d", "label": "D", "detail": "ok", "fix": ""}]),
        patch("scripts.runtime_doctor.check_action_backlog", return_value=[{"level": "pass", "check": "e", "label": "E", "detail": "ok", "fix": ""}]),
    ):
        result = run_all_checks()
    assert result["verdict"] == "PASS"


def test_verdict_fail_overrides_warn():
    with (
        patch("scripts.runtime_doctor.check_units", return_value=[{"level": "fail", "check": "a", "label": "A", "detail": "down", "fix": "start it"}]),
        patch("scripts.runtime_doctor.check_http", return_value=[{"level": "warn", "check": "b", "label": "B", "detail": "slow", "fix": ""}]),
        patch("scripts.runtime_doctor.check_systemd_drift", return_value=[]),
        patch("scripts.runtime_doctor.check_outbox", return_value=[]),
        patch("scripts.runtime_doctor.check_action_backlog", return_value=[]),
    ):
        result = run_all_checks()
    assert result["verdict"] == "FAIL"


# ---------------------------------------------------------------------------
# render_terminal
# ---------------------------------------------------------------------------

def test_render_terminal_shows_verdict():
    result = {
        "verdict": "WARN",
        "pass": 5, "warn": 1, "fail": 0, "total": 6,
        "checks": [
            {"check": "x", "label": "Test", "level": "warn", "detail": "problem", "fix": "do something"},
        ],
    }
    text = render_terminal(result)
    assert "WARN" in text
    assert "[!!]" in text
    assert "fix:" in text
