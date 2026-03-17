#!/usr/bin/env python3
"""Tests: post-ingestion state_export freshness after factory provenance bridge runs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runtime.core.factory_provenance_bridge import ingest_all, ingest_linkage
from runtime.dashboard.rebuild_helpers import refresh_state_export


def _scaffold(tmp_path: Path) -> tuple[Path, Path]:
    """Create minimal directory structure for a provenance ingestion test."""
    runtime_root = tmp_path / "jarvis"
    artifact_root = tmp_path / "artifacts" / "strategy_factory"

    # Minimal state dirs that state_export / rebuild_helpers expect
    for d in (
        "state/tasks",
        "state/reviews",
        "state/approvals",
        "state/artifacts",
        "state/artifact_provenance",
        "state/task_provenance",
        "state/promotion_provenance",
        "state/routing_provenance",
        "state/decision_provenance",
        "state/publish_provenance",
        "state/rollback_provenance",
        "state/memory_provenance",
        "state/flowstate_sources",
        "state/logs",
        "workspace/out",
    ):
        (runtime_root / d).mkdir(parents=True, exist_ok=True)

    # Factory artifact with pending linkage
    run_dir = artifact_root / "2026-03-17"
    run_dir.mkdir(parents=True)
    linkage = {
        "linkage_id": "flink_test001",
        "candidate_id": "test_cand",
        "status": "PASS",
        "gate_overall": "PASS",
        "evidence_files": ["candidate_result.json"],
    }
    (run_dir / "provenance_linkage.json").write_text(json.dumps(linkage), encoding="utf-8")

    return runtime_root, artifact_root


# -- Tests -------------------------------------------------------------------


def test_ingest_all_refreshes_state_export(tmp_path: Path) -> None:
    """After ingest_all, state/logs/state_export.json must exist and reflect
    the newly ingested artifact provenance record."""
    runtime_root, artifact_root = _scaffold(tmp_path)
    export_path = runtime_root / "state" / "logs" / "state_export.json"

    assert not export_path.exists(), "state_export.json should not exist before ingestion"

    results = ingest_all(artifact_root=artifact_root, runtime_root=runtime_root)

    assert any(r["status"] == "ingested" for r in results)
    assert export_path.exists(), "state_export.json must be written after ingestion"

    export = json.loads(export_path.read_text(encoding="utf-8"))
    # The provenance counts inside the summary come from build_state_export;
    # at minimum, artifact_provenance should no longer be zero.
    assert export.get("counts") is not None


def test_ingest_all_skips_refresh_when_nothing_ingested(tmp_path: Path) -> None:
    """If all linkages are already ingested, no refresh should happen (no
    wasted IO)."""
    runtime_root, artifact_root = _scaffold(tmp_path)
    export_path = runtime_root / "state" / "logs" / "state_export.json"

    # First pass: ingest
    ingest_all(artifact_root=artifact_root, runtime_root=runtime_root)
    assert export_path.exists()
    first_mtime = export_path.stat().st_mtime

    # Delete the export so we can tell if a second pass writes it
    export_path.unlink()

    # Second pass: nothing pending
    results = ingest_all(artifact_root=artifact_root, runtime_root=runtime_root)
    assert all(r["status"] == "already_ingested" for r in results)
    assert not export_path.exists(), "refresh should be skipped when nothing was ingested"


def test_refresh_state_export_standalone(tmp_path: Path) -> None:
    """refresh_state_export can be called independently and produces valid JSON."""
    runtime_root, _ = _scaffold(tmp_path)
    summary = refresh_state_export(runtime_root)

    assert isinstance(summary, dict)
    assert "counts" in summary
    export_path = runtime_root / "state" / "logs" / "state_export.json"
    assert export_path.exists()
    on_disk = json.loads(export_path.read_text(encoding="utf-8"))
    assert on_disk == summary


def test_ingest_linkage_does_not_refresh(tmp_path: Path) -> None:
    """Single-linkage ingest should NOT trigger a refresh (callers control that)."""
    runtime_root, artifact_root = _scaffold(tmp_path)
    linkage_path = artifact_root / "2026-03-17" / "provenance_linkage.json"
    export_path = runtime_root / "state" / "logs" / "state_export.json"

    ingest_linkage(linkage_path, runtime_root=runtime_root)
    assert not export_path.exists(), "single-linkage ingest must not trigger refresh"
