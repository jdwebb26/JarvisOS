"""Tests for promote_output — list, promote, inspect pipeline."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.promote_output import (
    list_promotable,
    promote_task_result,
    inspect_artifact,
    render_list,
    render_promote_result,
    render_inspect,
    _extract_result_id,
)


def _w(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _make_promotable_state(root: Path) -> None:
    """Create a completed task with backend result, no artifact yet."""
    _w(root / "state/tasks/task_promo.json", {
        "task_id": "task_promo",
        "status": "completed",
        "task_type": "general",
        "risk_level": "normal",
        "review_required": False,
        "approval_required": False,
        "execution_backend": "ralph_adapter",
        "source_lane": "operator",
        "source_channel": "todo",
        "source_user": "operator",
        "source_message_id": "msg_001",
        "trigger_type": "explicit_task_colon",
        "raw_request": "Summarize the latest market conditions for NQ",
        "created_at": "2026-03-18T10:00:00+00:00",
        "updated_at": "2026-03-18T11:00:00+00:00",
        "normalized_request": "Summarize the latest market conditions for NQ",
        "final_outcome": "hal executed in 5s. Model: qwen3.5. Result id: bkres_testresult001",
        "promoted_artifact_id": None,
        "related_artifact_ids": [],
        "related_review_ids": ["rev_test1"],
        "related_approval_ids": [],
        "lifecycle_state": "active",
        "home_runtime_workspace": "jarvis_v5_runtime",
        "target_workspace_id": None,
        "allowed_workspace_ids": [],
        "touched_workspace_ids": [],
        "candidate_artifact_ids": [],
        "demoted_artifact_ids": [],
        "revoked_artifact_ids": [],
        "impacted_output_ids": [],
    })

    _w(root / "state/backend_execution_results/bkres_testresult001.json", {
        "backend_execution_result_id": "bkres_testresult001",
        "task_id": "task_promo",
        "status": "completed",
        "outcome_summary": "## NQ Market Summary\n\nThe NQ E-mini futures show bullish momentum with key support at 18,500.",
        "model_name": "qwen3.5-35b-a3b",
        "actor": "ralph",
        "lane": "ralph",
    })

    # A task that already has a promoted artifact (should be excluded from list)
    _w(root / "state/tasks/task_done.json", {
        "task_id": "task_done",
        "status": "completed",
        "task_type": "general",
        "execution_backend": "ralph_adapter",
        "final_outcome": "hal executed. Result id: bkres_doneresult",
        "promoted_artifact_id": "art_existing",
        "normalized_request": "Already promoted task",
    })

    # A review for the task
    _w(root / "state/reviews/rev_test1.json", {
        "review_id": "rev_test1",
        "task_id": "task_promo",
        "status": "approved",
        "requested_reviewer": "archimedes",
    })

    # Ensure workspace dirs exist
    (root / "workspace" / "out").mkdir(parents=True, exist_ok=True)
    (root / "state" / "artifacts").mkdir(parents=True, exist_ok=True)
    (root / "state" / "task_events").mkdir(parents=True, exist_ok=True)
    (root / "state" / "candidate_records").mkdir(parents=True, exist_ok=True)
    (root / "state" / "candidate_promotions").mkdir(parents=True, exist_ok=True)
    (root / "state" / "artifact_provenance").mkdir(parents=True, exist_ok=True)
    (root / "state" / "publish_provenance").mkdir(parents=True, exist_ok=True)
    (root / "state" / "dispatch_events").mkdir(parents=True, exist_ok=True)
    (root / "state" / "discord_outbox").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# _extract_result_id
# ---------------------------------------------------------------------------

class TestExtractResultId:
    def test_extracts_from_outcome(self):
        assert _extract_result_id("hal executed in 5s. Result id: bkres_abc123") == "bkres_abc123"

    def test_returns_none_for_missing(self):
        assert _extract_result_id("completed without result id") is None

    def test_extracts_with_extra_text(self):
        r = _extract_result_id("Model: qwen. Result id: bkres_xyz789. Done.")
        assert r == "bkres_xyz789"


# ---------------------------------------------------------------------------
# list_promotable
# ---------------------------------------------------------------------------

class TestListPromotable:
    def test_finds_promotable_task(self, tmp_path):
        _make_promotable_state(tmp_path)
        items = list_promotable(tmp_path)
        assert len(items) == 1
        assert items[0]["task_id"] == "task_promo"
        assert items[0]["has_review"] is True

    def test_excludes_already_promoted(self, tmp_path):
        _make_promotable_state(tmp_path)
        items = list_promotable(tmp_path)
        ids = [i["task_id"] for i in items]
        assert "task_done" not in ids

    def test_empty_state(self, tmp_path):
        (tmp_path / "state/tasks").mkdir(parents=True)
        assert list_promotable(tmp_path) == []


# ---------------------------------------------------------------------------
# promote_task_result
# ---------------------------------------------------------------------------

class TestPromoteTaskResult:
    def test_full_promotion_pipeline(self, tmp_path):
        _make_promotable_state(tmp_path)
        result = promote_task_result("task_promo", root=tmp_path)
        assert result["ok"] is True
        assert result["artifact_id"].startswith("art_")
        assert result["output_id"].startswith("out_")
        assert result["content_length"] > 0

        # Verify artifact exists on disk
        art_path = tmp_path / "state" / "artifacts" / f"{result['artifact_id']}.json"
        assert art_path.exists()
        art = json.loads(art_path.read_text())
        assert art["lifecycle_state"] == "promoted"
        assert art["promoted_by"] == "operator"

        # Verify output exists
        md_path = Path(result["markdown_path"])
        assert md_path.exists()
        assert "NQ Market Summary" in md_path.read_text()

        # Verify task has promoted_artifact_id
        task = json.loads((tmp_path / "state/tasks/task_promo.json").read_text())
        assert task["promoted_artifact_id"] == result["artifact_id"]

    def test_rejects_non_completed(self, tmp_path):
        _make_promotable_state(tmp_path)
        # Modify task to queued
        tp = tmp_path / "state/tasks/task_promo.json"
        t = json.loads(tp.read_text())
        t["status"] = "queued"
        tp.write_text(json.dumps(t))

        result = promote_task_result("task_promo", root=tmp_path)
        assert result["ok"] is False
        assert "not completed" in result["error"]

    def test_rejects_already_promoted(self, tmp_path):
        _make_promotable_state(tmp_path)
        # Promote once
        r1 = promote_task_result("task_promo", root=tmp_path)
        assert r1["ok"] is True
        # Try again
        r2 = promote_task_result("task_promo", root=tmp_path)
        assert r2["ok"] is False
        assert "already has promoted artifact" in r2["error"]

    def test_rejects_missing_task(self, tmp_path):
        (tmp_path / "state/tasks").mkdir(parents=True)
        result = promote_task_result("task_nonexistent", root=tmp_path)
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# inspect_artifact
# ---------------------------------------------------------------------------

class TestInspectArtifact:
    def test_inspect_promoted_artifact(self, tmp_path):
        _make_promotable_state(tmp_path)
        # Promote first
        r = promote_task_result("task_promo", root=tmp_path)
        assert r["ok"] is True

        data = inspect_artifact(r["artifact_id"], tmp_path)
        assert data["ok"] is True
        assert data["lifecycle_state"] == "promoted"
        assert data["task_id"] == "task_promo"
        assert len(data["reviews"]) == 1
        assert data["reviews"][0]["status"] == "approved"
        assert len(data["outputs"]) == 1
        assert data["outputs"][0]["status"] == "published"

    def test_inspect_nonexistent(self, tmp_path):
        (tmp_path / "state/artifacts").mkdir(parents=True)
        data = inspect_artifact("art_nonexistent", tmp_path)
        assert data["ok"] is False


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

class TestRenderers:
    def test_render_list_empty(self):
        assert "No promotable" in render_list([])

    def test_render_list_with_items(self):
        items = [{"task_id": "task_x", "request": "do stuff", "task_type": "general",
                  "content_length": 500, "has_review": True, "result_id": "r1",
                  "model": "qwen", "source_channel": "todo"}]
        text = render_list(items)
        assert "PROMOTABLE" in text
        assert "--promote" in text

    def test_render_promote_success(self):
        data = {"ok": True, "artifact_id": "art_x", "output_id": "out_y",
                "task_id": "task_z", "title": "test", "model": "qwen",
                "content_length": 100, "markdown_path": "/tmp/test.md", "result_id": "r1"}
        text = render_promote_result(data)
        assert "PROMOTED" in text
        assert "--inspect" in text

    def test_render_promote_error(self):
        data = {"ok": False, "error": "not found"}
        assert "ERROR" in render_promote_result(data)

    def test_render_inspect_with_provenance(self):
        data = {"ok": True, "artifact_id": "art_x", "lifecycle_state": "promoted",
                "artifact_type": "general", "title": "test", "task_id": "task_z",
                "task_status": "completed", "task_request": "do stuff",
                "created_at": "2026-03-18T10:00:00", "promoted_at": "2026-03-18T11:00:00",
                "promoted_by": "operator", "provenance_ref": "test:ref",
                "content_length": 500,
                "reviews": [{"review_id": "rev_1", "status": "approved", "reviewer": "arch"}],
                "approvals": [{"approval_id": "apr_1", "status": "approved"}],
                "outputs": [{"output_id": "out_1", "status": "published",
                             "markdown_path": "/tmp/out.md"}]}
        text = render_inspect(data)
        assert "promoted" in text
        assert "rev_1" in text
        assert "apr_1" in text
        assert "out_1" in text
