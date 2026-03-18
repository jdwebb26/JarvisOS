"""Tests for auto-promotion wiring — idempotency and both completion paths."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.ralph.auto_promote import auto_promote_completed_task


def _w(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _make_completed_task(root: Path, *, task_id: str = "task_auto") -> None:
    """Create a completed task with backend result, ready for auto-promotion."""
    _w(root / f"state/tasks/{task_id}.json", {
        "task_id": task_id,
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
        "raw_request": "Summarize NQ conditions",
        "created_at": "2026-03-18T10:00:00+00:00",
        "updated_at": "2026-03-18T11:00:00+00:00",
        "normalized_request": "Summarize NQ conditions",
        "final_outcome": f"hal executed in 5s. Model: qwen3.5. Result id: bkres_{task_id}_r1",
        "promoted_artifact_id": None,
        "related_artifact_ids": [],
        "related_review_ids": [],
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

    _w(root / f"state/backend_execution_results/bkres_{task_id}_r1.json", {
        "backend_execution_result_id": f"bkres_{task_id}_r1",
        "task_id": task_id,
        "status": "completed",
        "outcome_summary": "## NQ Summary\n\nBullish momentum with support at 18,500. Key resistance at 19,200.",
        "model_name": "qwen3.5-35b-a3b",
        "actor": "ralph",
        "lane": "ralph",
    })

    # Ensure required dirs
    for d in [
        "workspace/out", "state/artifacts", "state/task_events",
        "state/candidate_records", "state/candidate_promotions",
        "state/artifact_provenance", "state/publish_provenance",
        "state/dispatch_events", "state/discord_outbox",
    ]:
        (root / d).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Path A: review_required=false / approval_required=false
# ---------------------------------------------------------------------------

class TestAutoPromoteNoApproval:
    def test_promotes_completed_task(self, tmp_path):
        _make_completed_task(tmp_path)
        artifact_id = auto_promote_completed_task("task_auto", root=tmp_path)
        assert artifact_id is not None
        assert artifact_id.startswith("art_")

        # Artifact on disk
        art_path = tmp_path / "state" / "artifacts" / f"{artifact_id}.json"
        assert art_path.exists()
        art = json.loads(art_path.read_text())
        assert art["lifecycle_state"] == "promoted"
        assert art["promoted_by"] == "ralph"

        # Output published
        out_files = list((tmp_path / "workspace" / "out").glob("out_*.json"))
        assert len(out_files) == 1
        out = json.loads(out_files[0].read_text())
        assert out["artifact_id"] == artifact_id
        assert out["task_id"] == "task_auto"

        # Task updated with promoted_artifact_id
        task = json.loads((tmp_path / "state/tasks/task_auto.json").read_text())
        assert task["promoted_artifact_id"] == artifact_id

    def test_idempotent_no_duplicate(self, tmp_path):
        """Running auto-promote twice must not create a second artifact or output."""
        _make_completed_task(tmp_path)

        art1 = auto_promote_completed_task("task_auto", root=tmp_path)
        assert art1 is not None

        art2 = auto_promote_completed_task("task_auto", root=tmp_path)
        # Second call returns None (already promoted)
        assert art2 is None

        # Only one artifact, one output
        art_files = list((tmp_path / "state" / "artifacts").glob("art_*.json"))
        assert len(art_files) == 1
        out_files = list((tmp_path / "workspace" / "out").glob("out_*.json"))
        assert len(out_files) == 1


# ---------------------------------------------------------------------------
# Path B: approval_required=true then approved
# ---------------------------------------------------------------------------

class TestAutoPromoteWithApproval:
    def test_promotes_after_approval(self, tmp_path):
        """Simulates the approval_complete path — task already completed."""
        _make_completed_task(tmp_path, task_id="task_approved")

        # Add a review and approval for provenance
        _w(tmp_path / "state/reviews/rev_ap1.json", {
            "review_id": "rev_ap1",
            "task_id": "task_approved",
            "status": "approved",
            "requested_reviewer": "archimedes",
        })
        _w(tmp_path / "state/approvals/apr_ap1.json", {
            "approval_id": "apr_ap1",
            "task_id": "task_approved",
            "status": "approved",
            "decided_by": "operator",
        })

        artifact_id = auto_promote_completed_task("task_approved", root=tmp_path)
        assert artifact_id is not None

        # Verify full chain
        art = json.loads((tmp_path / "state/artifacts" / f"{artifact_id}.json").read_text())
        assert art["lifecycle_state"] == "promoted"
        assert art["task_id"] == "task_approved"

        out_files = list((tmp_path / "workspace" / "out").glob("out_*.json"))
        assert len(out_files) == 1

    def test_idempotent_after_approval(self, tmp_path):
        _make_completed_task(tmp_path, task_id="task_approved2")
        art1 = auto_promote_completed_task("task_approved2", root=tmp_path)
        art2 = auto_promote_completed_task("task_approved2", root=tmp_path)
        assert art1 is not None
        assert art2 is None

        out_files = list((tmp_path / "workspace" / "out").glob("out_*.json"))
        assert len(out_files) == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestAutoPromoteEdgeCases:
    def test_skips_failed_task(self, tmp_path):
        _make_completed_task(tmp_path, task_id="task_fail")
        # Change status to failed
        tp = tmp_path / "state/tasks/task_fail.json"
        t = json.loads(tp.read_text())
        t["status"] = "failed"
        tp.write_text(json.dumps(t))

        result = auto_promote_completed_task("task_fail", root=tmp_path)
        assert result is None

    def test_skips_missing_task(self, tmp_path):
        (tmp_path / "state/tasks").mkdir(parents=True)
        result = auto_promote_completed_task("task_nonexistent", root=tmp_path)
        assert result is None

    def test_skips_empty_result(self, tmp_path):
        _make_completed_task(tmp_path, task_id="task_empty")
        # Overwrite result with empty content
        rp = tmp_path / "state/backend_execution_results/bkres_task_empty_r1.json"
        r = json.loads(rp.read_text())
        r["outcome_summary"] = ""
        rp.write_text(json.dumps(r))

        result = auto_promote_completed_task("task_empty", root=tmp_path)
        assert result is None

    def test_never_raises(self, tmp_path):
        """auto_promote must never raise, even with broken state."""
        # Completely empty state dir — should return None, not raise
        (tmp_path / "state/tasks").mkdir(parents=True)
        _w(tmp_path / "state/tasks/task_broken.json", {
            "task_id": "task_broken",
            "status": "completed",
            # Missing most fields
        })
        result = auto_promote_completed_task("task_broken", root=tmp_path)
        assert result is None
