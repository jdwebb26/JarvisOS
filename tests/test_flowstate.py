"""Tests for Flowstate source_store, distill_store, and operator CLI."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.flowstate.source_store import (
    create_source,
    list_sources,
    load_source,
    save_source,
)
from runtime.flowstate.distill_store import (
    create_distillation_artifact,
    create_extraction_artifact,
)


# ---------------------------------------------------------------------------
# Source store
# ---------------------------------------------------------------------------

class TestSourceStore:
    def test_create_source(self, tmp_path):
        record = create_source(
            source_type="note",
            title="Test note",
            content="Some content here.",
            source_ref="2026-03-18",
            created_by="test_user",
            root=tmp_path,
        )
        assert record["source_id"].startswith("fsrc_")
        assert record["processing_status"] == "ingested"
        assert record["title"] == "Test note"
        assert record["content"] == "Some content here."

        # File exists on disk
        path = tmp_path / "state" / "flowstate_sources" / f"{record['source_id']}.json"
        assert path.exists()

    def test_load_source(self, tmp_path):
        record = create_source(
            source_type="transcript", title="T", content="C",
            source_ref="", created_by="op", root=tmp_path,
        )
        loaded = load_source(record["source_id"], root=tmp_path)
        assert loaded is not None
        assert loaded["source_id"] == record["source_id"]
        # Backward-compat defaults
        assert loaded["distillation_artifact_ids"] == []
        assert loaded["promotion_request_ids"] == []

    def test_load_missing_source(self, tmp_path):
        assert load_source("fsrc_nonexistent", root=tmp_path) is None

    def test_list_sources(self, tmp_path):
        create_source(source_type="note", title="A", content="a",
                       source_ref="", created_by="op", root=tmp_path)
        create_source(source_type="note", title="B", content="b",
                       source_ref="", created_by="op", root=tmp_path)
        sources = list_sources(root=tmp_path)
        assert len(sources) == 2

    def test_list_sources_empty(self, tmp_path):
        assert list_sources(root=tmp_path) == []


# ---------------------------------------------------------------------------
# Distill store
# ---------------------------------------------------------------------------

class TestDistillStore:
    def test_create_extraction(self, tmp_path):
        source = create_source(
            source_type="transcript", title="Meeting", content="raw audio",
            source_ref="", created_by="op", root=tmp_path,
        )
        artifact = create_extraction_artifact(
            source_id=source["source_id"],
            extracted_text="Transcribed text of the meeting.",
            root=tmp_path,
        )
        assert artifact["artifact_id"].startswith("fext_")
        assert artifact["extracted_text"] == "Transcribed text of the meeting."

        # Source updated
        updated = load_source(source["source_id"], root=tmp_path)
        assert updated["processing_status"] == "extracted"
        assert updated["extraction_artifact_id"] == artifact["artifact_id"]

    def test_create_distillation(self, tmp_path):
        source = create_source(
            source_type="note", title="Research", content="Findings...",
            source_ref="", created_by="op", root=tmp_path,
        )
        artifact = create_distillation_artifact(
            source_id=source["source_id"],
            summary="Key findings from research.",
            key_claims=["claim1", "claim2"],
            key_ideas=["idea1"],
            candidate_actions=["action1"],
            notable_sections=[],
            caveats=["caveat1"],
            root=tmp_path,
        )
        assert artifact["artifact_id"].startswith("fdist_")
        assert artifact["summary"] == "Key findings from research."
        assert len(artifact["key_claims"]) == 2

        # Source updated
        updated = load_source(source["source_id"], root=tmp_path)
        assert updated["processing_status"] == "distilled"
        assert artifact["artifact_id"] in updated["distillation_artifact_ids"]
        assert updated["latest_distillation_artifact_id"] == artifact["artifact_id"]

    def test_distillation_preserves_promotion_status(self, tmp_path):
        source = create_source(
            source_type="note", title="P", content="c",
            source_ref="", created_by="op", root=tmp_path,
        )
        # Manually set to awaiting_promotion_approval
        source["processing_status"] = "awaiting_promotion_approval"
        save_source(source, root=tmp_path)

        artifact = create_distillation_artifact(
            source_id=source["source_id"],
            summary="New distillation",
            key_claims=[], key_ideas=[], candidate_actions=[],
            notable_sections=[], caveats=[],
            root=tmp_path,
        )
        updated = load_source(source["source_id"], root=tmp_path)
        assert updated["processing_status"] == "awaiting_promotion_approval"

    def test_distillation_missing_source(self, tmp_path):
        with pytest.raises(ValueError, match="not found"):
            create_distillation_artifact(
                source_id="fsrc_nonexistent",
                summary="nope", key_claims=[], key_ideas=[],
                candidate_actions=[], notable_sections=[], caveats=[],
                root=tmp_path,
            )

    def test_multiple_distillations(self, tmp_path):
        source = create_source(
            source_type="note", title="Multi", content="c",
            source_ref="", created_by="op", root=tmp_path,
        )
        d1 = create_distillation_artifact(
            source_id=source["source_id"], summary="First pass",
            key_claims=[], key_ideas=[], candidate_actions=[],
            notable_sections=[], caveats=[], root=tmp_path,
        )
        d2 = create_distillation_artifact(
            source_id=source["source_id"], summary="Second pass",
            key_claims=[], key_ideas=[], candidate_actions=[],
            notable_sections=[], caveats=[], root=tmp_path,
        )
        updated = load_source(source["source_id"], root=tmp_path)
        assert len(updated["distillation_artifact_ids"]) == 2
        assert updated["latest_distillation_artifact_id"] == d2["artifact_id"]


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_ingest_extract_distill_lifecycle(self, tmp_path):
        """Full lifecycle: ingest → extract → distill → verify state."""
        source = create_source(
            source_type="web_article", title="NQ Regime Analysis",
            content="Full article text about NQ regime signals...",
            source_ref="https://example.com/article", created_by="hermes",
            root=tmp_path,
        )
        assert source["processing_status"] == "ingested"

        ext = create_extraction_artifact(
            source_id=source["source_id"],
            extracted_text="Extracted: NQ regime signals show momentum shift...",
            root=tmp_path,
        )
        s2 = load_source(source["source_id"], root=tmp_path)
        assert s2["processing_status"] == "extracted"

        dist = create_distillation_artifact(
            source_id=source["source_id"],
            summary="NQ showing momentum regime shift based on breadth divergence.",
            key_claims=["Breadth divergence signals regime change"],
            key_ideas=["Monitor NQ breadth vs price for early regime detection"],
            candidate_actions=["Add breadth divergence to strategy factory feature set"],
            notable_sections=["Section 3: Breadth analysis"],
            caveats=["Single source — needs cross-validation"],
            root=tmp_path,
        )
        s3 = load_source(source["source_id"], root=tmp_path)
        assert s3["processing_status"] == "distilled"
        assert s3["extraction_artifact_id"] == ext["artifact_id"]
        assert s3["latest_distillation_artifact_id"] == dist["artifact_id"]
        assert len(s3["promotion_request_ids"]) == 0  # Not promoted
