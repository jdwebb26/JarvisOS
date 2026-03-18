"""Tests for reconcile_approvals — stale/orphaned/duplicate detection and cleanup."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.reconcile_approvals import (
    scan_approvals,
    cancel_approval,
    apply_reconciliation,
    render_report,
)


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _make_state(root: Path) -> None:
    """Build a test state with valid, stale, orphaned, and duplicate approvals."""
    # Valid: pending approval + task in waiting_approval
    _write(root / "state/approvals/apr_valid.json", {
        "approval_id": "apr_valid",
        "task_id": "task_001",
        "status": "pending",
        "summary": "Valid approval",
        "requested_at": "2026-03-18T10:00:00Z",
        "updated_at": "2026-03-18T10:00:00Z",
    })
    _write(root / "state/tasks/task_001.json", {
        "task_id": "task_001",
        "status": "waiting_approval",
        "normalized_request": "Fix the login bug",
    })

    # Stale: pending approval but task completed
    _write(root / "state/approvals/apr_stale.json", {
        "approval_id": "apr_stale",
        "task_id": "task_002",
        "status": "pending",
        "summary": "Stale approval",
        "requested_at": "2026-03-18T09:00:00Z",
        "updated_at": "2026-03-18T09:00:00Z",
    })
    _write(root / "state/tasks/task_002.json", {
        "task_id": "task_002",
        "status": "completed",
        "normalized_request": "Old completed task",
    })

    # Stale: pending approval but task failed
    _write(root / "state/approvals/apr_stale2.json", {
        "approval_id": "apr_stale2",
        "task_id": "task_003",
        "status": "pending",
        "summary": "Another stale",
        "requested_at": "2026-03-18T09:30:00Z",
        "updated_at": "2026-03-18T09:30:00Z",
    })
    _write(root / "state/tasks/task_003.json", {
        "task_id": "task_003",
        "status": "failed",
        "normalized_request": "Failed task",
    })

    # Orphaned: pending approval but task file missing
    _write(root / "state/approvals/apr_orphan.json", {
        "approval_id": "apr_orphan",
        "task_id": "task_missing",
        "status": "pending",
        "summary": "Orphaned approval",
        "requested_at": "2026-03-18T08:00:00Z",
        "updated_at": "2026-03-18T08:00:00Z",
    })

    # Already decided: should be ignored entirely
    _write(root / "state/approvals/apr_done.json", {
        "approval_id": "apr_done",
        "task_id": "task_001",
        "status": "approved",
        "summary": "Already approved",
        "requested_at": "2026-03-17T10:00:00Z",
        "updated_at": "2026-03-17T12:00:00Z",
    })

    # Duplicates: two pending approvals for the same task
    _write(root / "state/approvals/apr_dup1.json", {
        "approval_id": "apr_dup1",
        "task_id": "task_004",
        "status": "pending",
        "summary": "First dup",
        "requested_at": "2026-03-18T11:00:00Z",
        "updated_at": "2026-03-18T11:00:00Z",
    })
    _write(root / "state/approvals/apr_dup2.json", {
        "approval_id": "apr_dup2",
        "task_id": "task_004",
        "status": "pending",
        "summary": "Second dup",
        "requested_at": "2026-03-18T11:30:00Z",
        "updated_at": "2026-03-18T11:30:00Z",
    })
    _write(root / "state/tasks/task_004.json", {
        "task_id": "task_004",
        "status": "waiting_approval",
        "normalized_request": "Task with duplicates",
    })


# ---------------------------------------------------------------------------
# Scan tests
# ---------------------------------------------------------------------------

def test_scan_finds_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        result = scan_approvals(root=root)
    # apr_valid + apr_dup1 + apr_dup2 are valid (task is waiting_approval)
    assert len(result["valid"]) == 3


def test_scan_finds_stale():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        result = scan_approvals(root=root)
    assert len(result["stale"]) == 2
    stale_ids = {e["approval_id"] for e in result["stale"]}
    assert stale_ids == {"apr_stale", "apr_stale2"}


def test_scan_finds_orphaned():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        result = scan_approvals(root=root)
    assert len(result["orphaned"]) == 1
    assert result["orphaned"][0]["approval_id"] == "apr_orphan"


def test_scan_finds_duplicates():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        result = scan_approvals(root=root)
    assert len(result["duplicates"]) == 1
    assert result["duplicates"][0]["task_id"] == "task_004"
    assert result["duplicates"][0]["count"] == 2


def test_scan_ignores_non_pending():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        result = scan_approvals(root=root)
    # apr_done (approved) should not appear in any list
    all_ids = set()
    for lst in [result["valid"], result["stale"], result["orphaned"]]:
        for e in lst:
            all_ids.add(e["approval_id"])
    assert "apr_done" not in all_ids


def test_scan_empty_state():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = scan_approvals(root=Path(tmpdir))
    assert result["total"] == 0
    assert result["valid"] == []


# ---------------------------------------------------------------------------
# Apply tests
# ---------------------------------------------------------------------------

def test_apply_cancels_stale(tmp_path):
    _make_state(tmp_path)
    scan = scan_approvals(root=tmp_path)
    result = apply_reconciliation(scan, root=tmp_path)
    assert result["cancelled"] >= 2  # 2 stale
    data = json.loads((tmp_path / "state/approvals/apr_stale.json").read_text())
    assert data["status"] == "cancelled"
    assert "[reconcile]" in data["decision_reason"]


def test_apply_cancels_orphaned(tmp_path):
    _make_state(tmp_path)
    scan = scan_approvals(root=tmp_path)
    apply_reconciliation(scan, root=tmp_path)
    data = json.loads((tmp_path / "state/approvals/apr_orphan.json").read_text())
    assert data["status"] == "cancelled"


def test_apply_cancels_duplicate_keeping_newest(tmp_path):
    _make_state(tmp_path)
    scan = scan_approvals(root=tmp_path)
    apply_reconciliation(scan, root=tmp_path)
    # apr_dup1 should be cancelled (older by ID sort), apr_dup2 kept
    d1 = json.loads((tmp_path / "state/approvals/apr_dup1.json").read_text())
    d2 = json.loads((tmp_path / "state/approvals/apr_dup2.json").read_text())
    assert d1["status"] == "cancelled"
    assert d2["status"] == "pending"


def test_apply_idempotent(tmp_path):
    """Running apply twice should not fail or double-cancel."""
    _make_state(tmp_path)
    scan1 = scan_approvals(root=tmp_path)
    apply_reconciliation(scan1, root=tmp_path)
    scan2 = scan_approvals(root=tmp_path)
    issues = len(scan2["stale"]) + len(scan2["orphaned"]) + len(scan2["duplicates"])
    assert issues == 0


def test_cancel_approval_returns_false_for_nonexistent():
    with tempfile.TemporaryDirectory() as tmpdir:
        assert cancel_approval("apr_nonexistent", "test", root=Path(tmpdir)) is False


def test_cancel_approval_returns_false_for_already_decided():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _write(root / "state/approvals/apr_decided.json", {
            "approval_id": "apr_decided",
            "task_id": "t",
            "status": "approved",
        })
        assert cancel_approval("apr_decided", "test", root=root) is False


# ---------------------------------------------------------------------------
# Render tests
# ---------------------------------------------------------------------------

def test_render_report_clean():
    scan = {
        "total": 5, "by_status": {"pending": 3, "approved": 2},
        "valid": [{"approval_id": "a1"}, {"approval_id": "a2"}, {"approval_id": "a3"}],
        "stale": [], "orphaned": [], "duplicates": [],
    }
    text = render_report(scan)
    assert "No issues found" in text
    assert "Valid pending: 3" in text


def test_render_report_with_issues():
    scan = {
        "total": 5, "by_status": {"pending": 3},
        "valid": [{"approval_id": "a1"}],
        "stale": [{"approval_id": "a2", "task_id": "t2", "reason": "task_status=completed"}],
        "orphaned": [{"approval_id": "a3", "task_id": "t3"}],
        "duplicates": [],
    }
    text = render_report(scan)
    assert "STALE" in text
    assert "ORPHANED" in text
    assert "issue(s) found" in text
