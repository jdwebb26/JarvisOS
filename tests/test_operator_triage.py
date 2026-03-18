"""Tests for operator_triage — bucketed backlog classification."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage import (
    _is_transient,
    triage,
    render_compact,
    render_full,
)


def _w(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def _make_state(root: Path) -> None:
    # Valid pending approval
    _w(root / "state/approvals/apr_ok.json", {
        "approval_id": "apr_ok", "task_id": "task_a",
        "status": "pending", "summary": "Approve me",
    })
    _w(root / "state/tasks/task_a.json", {
        "task_id": "task_a", "status": "waiting_approval",
        "normalized_request": "Fix the login flow", "last_error": "",
    })

    # Stale pending approval (task completed)
    _w(root / "state/approvals/apr_stale.json", {
        "approval_id": "apr_stale", "task_id": "task_b",
        "status": "pending", "summary": "Stale",
    })
    _w(root / "state/tasks/task_b.json", {
        "task_id": "task_b", "status": "completed",
        "normalized_request": "Old task", "last_error": "",
    })

    # Transient failure
    _w(root / "state/tasks/task_c.json", {
        "task_id": "task_c", "status": "failed",
        "normalized_request": "Run Kitt brief",
        "last_error": "[TRANSIENT] kitt_quant: NVIDIA API timeout",
    })

    # Permanent failure
    _w(root / "state/tasks/task_d.json", {
        "task_id": "task_d", "status": "failed",
        "normalized_request": "Open browser",
        "last_error": "Backend browser_backend failed: tab_open_failed",
    })

    # Blocked
    _w(root / "state/tasks/task_e.json", {
        "task_id": "task_e", "status": "blocked",
        "normalized_request": "Search VIX", "last_error": "",
    })

    # Queued
    _w(root / "state/tasks/task_f.json", {
        "task_id": "task_f", "status": "queued",
        "normalized_request": "Say hello", "last_error": "",
    })

    # Completed (should be ignored)
    _w(root / "state/tasks/task_g.json", {
        "task_id": "task_g", "status": "completed",
        "normalized_request": "Done", "last_error": "",
    })


# ---------------------------------------------------------------------------
# _is_transient
# ---------------------------------------------------------------------------

class TestIsTransient:
    def test_transient_tag(self):
        assert _is_transient("[TRANSIENT] kitt_quant: timeout") is True

    def test_timeout_keyword(self):
        assert _is_transient("NVIDIA API timeout: HTTPSConnectionPool") is True

    def test_connection_refused(self):
        assert _is_transient("Connection refused on port 18789") is True

    def test_timed_out(self):
        assert _is_transient("Read timed out. (read timeout=180)") is True

    def test_permanent_config_error(self):
        assert _is_transient("NVIDIA_API_KEY is not set") is False

    def test_permanent_browser_error(self):
        assert _is_transient("Browser action requires review") is False

    def test_empty_string(self):
        assert _is_transient("") is False


# ---------------------------------------------------------------------------
# triage buckets
# ---------------------------------------------------------------------------

class TestTriage:
    def test_buckets(self, tmp_path):
        _make_state(tmp_path)
        data = triage(tmp_path)
        assert len(data["approvals"]) == 1
        assert data["approvals"][0]["task_id"] == "task_a"

    def test_stale_approvals(self, tmp_path):
        _make_state(tmp_path)
        data = triage(tmp_path)
        assert len(data["stale_approvals"]) == 1
        assert data["stale_approvals"][0]["approval_id"] == "apr_stale"

    def test_transient_vs_permanent(self, tmp_path):
        _make_state(tmp_path)
        data = triage(tmp_path)
        assert len(data["transient_failures"]) == 1
        assert data["transient_failures"][0]["task_id"] == "task_c"
        assert len(data["permanent_failures"]) == 1
        assert data["permanent_failures"][0]["task_id"] == "task_d"

    def test_blocked_and_queued(self, tmp_path):
        _make_state(tmp_path)
        data = triage(tmp_path)
        assert len(data["blocked"]) == 1
        assert len(data["queued"]) == 1

    def test_completed_excluded(self, tmp_path):
        _make_state(tmp_path)
        data = triage(tmp_path)
        all_ids = set()
        for lst in data.values():
            if isinstance(lst, list):
                for item in lst:
                    if isinstance(item, dict) and "task_id" in item:
                        all_ids.add(item["task_id"])
        assert "task_g" not in all_ids

    def test_empty_state(self, tmp_path):
        data = triage(tmp_path)
        assert data["approvals"] == []
        assert data["transient_failures"] == []
        assert data["permanent_failures"] == []


# ---------------------------------------------------------------------------
# renderers
# ---------------------------------------------------------------------------

class TestRenderers:
    def test_full_has_sections(self, tmp_path):
        _make_state(tmp_path)
        text = render_full(triage(tmp_path))
        assert "APPROVE" in text
        assert "RETRY" in text
        assert "INVESTIGATE" in text
        assert "RECONCILE" in text
        assert "--approve" in text
        assert "--retry" in text

    def test_compact_one_line_summary(self, tmp_path):
        _make_state(tmp_path)
        text = render_compact(triage(tmp_path))
        assert "TRIAGE:" in text
        assert "approve" in text
        assert "retry" in text

    def test_full_empty_state(self, tmp_path):
        text = render_full(triage(tmp_path))
        assert "Nothing to do" in text

    def test_compact_empty_state(self, tmp_path):
        text = render_compact(triage(tmp_path))
        assert "Nothing to do" in text
