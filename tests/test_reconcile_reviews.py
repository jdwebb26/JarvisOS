"""test_reconcile_reviews.py — Tests for review reconciliation."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.reconcile_reviews import (
    scan_reviews,
    cancel_review,
    apply_reconciliation,
    render_report,
)


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n")


def _make_state(tmpdir: Path) -> None:
    """Set up a test state directory with various review/task combos."""
    # Valid: pending review, task in waiting_review
    _write(tmpdir / "state/reviews/rev_valid_001.json", {
        "review_id": "rev_valid_001",
        "task_id": "task_001",
        "status": "pending",
        "requested_at": "2026-03-18T10:00:00Z",
        "summary": "Valid review",
    })
    _write(tmpdir / "state/tasks/task_001.json", {
        "task_id": "task_001",
        "status": "waiting_review",
    })

    # Stale: pending review, task completed
    _write(tmpdir / "state/reviews/rev_stale_001.json", {
        "review_id": "rev_stale_001",
        "task_id": "task_002",
        "status": "pending",
        "requested_at": "2026-03-18T09:00:00Z",
        "summary": "Stale review",
    })
    _write(tmpdir / "state/tasks/task_002.json", {
        "task_id": "task_002",
        "status": "completed",
    })

    # Stale: pending review, task waiting_approval
    _write(tmpdir / "state/reviews/rev_stale_002.json", {
        "review_id": "rev_stale_002",
        "task_id": "task_003",
        "status": "pending",
        "requested_at": "2026-03-18T09:00:00Z",
        "summary": "Moved to approval",
    })
    _write(tmpdir / "state/tasks/task_003.json", {
        "task_id": "task_003",
        "status": "waiting_approval",
    })

    # Stale: pending review, task blocked
    _write(tmpdir / "state/reviews/rev_stale_003.json", {
        "review_id": "rev_stale_003",
        "task_id": "task_004",
        "status": "pending",
        "requested_at": "2026-03-18T09:00:00Z",
        "summary": "Blocked task",
    })
    _write(tmpdir / "state/tasks/task_004.json", {
        "task_id": "task_004",
        "status": "blocked",
    })

    # Orphaned: pending review, no task file
    _write(tmpdir / "state/reviews/rev_orphan_001.json", {
        "review_id": "rev_orphan_001",
        "task_id": "task_999",
        "status": "pending",
        "requested_at": "2026-03-18T08:00:00Z",
        "summary": "Orphan",
    })

    # Duplicate: two pending reviews for same task, different timestamps
    _write(tmpdir / "state/reviews/rev_dup_old.json", {
        "review_id": "rev_dup_old",
        "task_id": "task_005",
        "status": "pending",
        "requested_at": "2026-03-18T07:00:00Z",
        "summary": "Older duplicate",
    })
    _write(tmpdir / "state/reviews/rev_dup_new.json", {
        "review_id": "rev_dup_new",
        "task_id": "task_005",
        "status": "pending",
        "requested_at": "2026-03-18T11:00:00Z",
        "summary": "Newer duplicate",
    })
    _write(tmpdir / "state/tasks/task_005.json", {
        "task_id": "task_005",
        "status": "waiting_review",
    })

    # Already decided: approved review (should be ignored)
    _write(tmpdir / "state/reviews/rev_done_001.json", {
        "review_id": "rev_done_001",
        "task_id": "task_006",
        "status": "approved",
        "requested_at": "2026-03-18T06:00:00Z",
    })


# ---------------------------------------------------------------------------
# Scan tests
# ---------------------------------------------------------------------------

def test_scan_classifies_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        scan = scan_reviews(root=root)
    valid_ids = {e["review_id"] for e in scan["valid"]}
    assert "rev_valid_001" in valid_ids


def test_scan_classifies_stale_completed():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        scan = scan_reviews(root=root)
    stale_ids = {e["review_id"] for e in scan["stale"]}
    assert "rev_stale_001" in stale_ids
    # Find the entry and check reason
    entry = [e for e in scan["stale"] if e["review_id"] == "rev_stale_001"][0]
    assert "completed" in entry["reason"]


def test_scan_classifies_stale_waiting_approval():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        scan = scan_reviews(root=root)
    stale_ids = {e["review_id"] for e in scan["stale"]}
    assert "rev_stale_002" in stale_ids


def test_scan_classifies_stale_blocked():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        scan = scan_reviews(root=root)
    stale_ids = {e["review_id"] for e in scan["stale"]}
    assert "rev_stale_003" in stale_ids


def test_scan_classifies_orphaned():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        scan = scan_reviews(root=root)
    orphan_ids = {e["review_id"] for e in scan["orphaned"]}
    assert "rev_orphan_001" in orphan_ids


def test_scan_detects_duplicates_keeps_newest():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        scan = scan_reviews(root=root)
    assert len(scan["duplicates"]) == 1
    dup = scan["duplicates"][0]
    assert dup["task_id"] == "task_005"
    assert dup["kept"] == "rev_dup_new"
    assert "rev_dup_old" in dup["cancel"]


def test_scan_ignores_decided_reviews():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        scan = scan_reviews(root=root)
    all_pending_ids = (
        {e["review_id"] for e in scan["valid"]}
        | {e["review_id"] for e in scan["stale"]}
        | {e["review_id"] for e in scan["orphaned"]}
    )
    assert "rev_done_001" not in all_pending_ids
    assert scan["by_status"].get("approved", 0) == 1


# ---------------------------------------------------------------------------
# Apply tests
# ---------------------------------------------------------------------------

def test_apply_cancels_stale_and_orphaned():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)
        scan = scan_reviews(root=root)
        result = apply_reconciliation(scan, root=root)

        # 3 stale + 1 orphaned + 1 duplicate cancel = 5
        assert result["cancelled"] == 5
        assert result["errors"] == 0

        # Verify the cancelled reviews are actually cancelled on disk
        for rid in ["rev_stale_001", "rev_stale_002", "rev_stale_003", "rev_orphan_001", "rev_dup_old"]:
            data = json.loads((root / f"state/reviews/{rid}.json").read_text())
            assert data["status"] == "cancelled", f"{rid} should be cancelled"
            assert "[reconcile]" in data.get("verdict_reason", "")

        # Valid review untouched
        valid = json.loads((root / "state/reviews/rev_valid_001.json").read_text())
        assert valid["status"] == "pending"

        # Kept duplicate untouched
        kept = json.loads((root / "state/reviews/rev_dup_new.json").read_text())
        assert kept["status"] == "pending"


def test_apply_idempotent():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _make_state(root)

        # First apply
        scan1 = scan_reviews(root=root)
        result1 = apply_reconciliation(scan1, root=root)
        assert result1["cancelled"] == 5

        # Second scan should find nothing to fix
        scan2 = scan_reviews(root=root)
        assert len(scan2["stale"]) == 0
        assert len(scan2["orphaned"]) == 0
        assert len(scan2["duplicates"]) == 0

        # Second apply should cancel nothing
        result2 = apply_reconciliation(scan2, root=root)
        assert result2["cancelled"] == 0


# ---------------------------------------------------------------------------
# Render tests
# ---------------------------------------------------------------------------

def test_render_report_clean():
    scan = {
        "total": 10, "by_status": {"approved": 8, "pending": 2},
        "valid": [{"review_id": "rev_a"}, {"review_id": "rev_b"}],
        "stale": [], "orphaned": [], "duplicates": [],
    }
    text = render_report(scan)
    assert "No problems found" in text
    assert "Total reviews: 10" in text


def test_render_report_with_problems():
    scan = {
        "total": 5, "by_status": {"pending": 3},
        "valid": [],
        "stale": [{"review_id": "rev_s1", "task_id": "task_s1", "reason": "task_status=completed"}],
        "orphaned": [{"review_id": "rev_o1", "task_id": "task_o1", "reason": "task_missing"}],
        "duplicates": [{"task_id": "task_d1", "kept": "rev_d2", "cancel": ["rev_d1"], "count": 2}],
    }
    text = render_report(scan)
    assert "STALE" in text
    assert "ORPHANED" in text
    assert "DUPLICATES" in text
    assert "rev_s1" in text
