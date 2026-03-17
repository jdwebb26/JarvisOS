#!/usr/bin/env python3
"""Bridge: ingest strategy_factory provenance_linkage.json files into the
runtime provenance store.

Usage:
    python -m runtime.core.factory_provenance_bridge
    python -m runtime.core.factory_provenance_bridge --artifact-root /path/to/artifacts/strategy_factory
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import ArtifactProvenanceRecord, new_id, now_iso
from runtime.core.provenance_store import save_artifact_provenance
from runtime.dashboard.rebuild_helpers import refresh_state_export

DEFAULT_ARTIFACT_ROOT = Path("/home/rollan/.openclaw/workspace/artifacts/strategy_factory")


def find_pending_linkages(artifact_root: Optional[Path] = None) -> list[Path]:
    """Return all provenance_linkage.json files not yet ingested."""
    root = Path(artifact_root or DEFAULT_ARTIFACT_ROOT)
    pending = []
    for path in sorted(root.glob("*/provenance_linkage.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not data.get("ingested"):
                pending.append(path)
        except Exception:
            continue
    return pending


def ingest_linkage(linkage_path: Path, *, runtime_root: Optional[Path] = None) -> dict:
    """Read a single provenance_linkage.json, create an ArtifactProvenanceRecord,
    and mark the linkage as ingested."""
    data = json.loads(linkage_path.read_text(encoding="utf-8"))
    if data.get("ingested"):
        return {"status": "already_ingested", "linkage_id": data.get("linkage_id")}

    record = save_artifact_provenance(
        ArtifactProvenanceRecord(
            artifact_provenance_id=new_id("aprov"),
            artifact_id=data.get("linkage_id", new_id("flink")),
            task_id=f"factory_run:{Path(linkage_path).parent.name}",
            created_at=data.get("produced_at", now_iso()),
            updated_at=now_iso(),
            actor="strategy_factory",
            lane="quant",
            producer_kind="strategy_factory",
            lifecycle_state=data.get("status", "unknown"),
            source_refs={
                "candidate_id": data.get("candidate_id"),
                "gate_overall": data.get("gate_overall"),
                "fold_count": data.get("fold_count"),
                "reject_reason": data.get("reject_reason"),
                "artifact_dir": data.get("artifact_dir"),
                "evidence_files": data.get("evidence_files", []),
            },
            replay_input={
                "source": "strategy_factory",
                "linkage_path": str(linkage_path),
            },
        ),
        root=runtime_root,
    )

    # Mark ingested so we don't re-process
    data["ingested"] = True
    data["provenance_record_id"] = record.artifact_provenance_id
    data["ingested_at"] = now_iso()
    linkage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return {
        "status": "ingested",
        "linkage_id": data.get("linkage_id"),
        "provenance_record_id": record.artifact_provenance_id,
    }


def ingest_all(
    artifact_root: Optional[Path] = None,
    runtime_root: Optional[Path] = None,
) -> list[dict]:
    """Ingest all pending factory linkages and refresh the state_export
    read-model so new provenance is immediately visible to operators."""
    results = []
    for path in find_pending_linkages(artifact_root):
        results.append(ingest_linkage(path, runtime_root=runtime_root))

    ingested = [r for r in results if r.get("status") == "ingested"]
    if ingested:
        refresh_state_export(Path(runtime_root or ROOT))

    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest strategy_factory provenance linkages into the runtime provenance store."
    )
    parser.add_argument(
        "--artifact-root",
        default=str(DEFAULT_ARTIFACT_ROOT),
        help="Root of strategy_factory artifact output dirs",
    )
    parser.add_argument(
        "--runtime-root",
        default=str(ROOT),
        help="Jarvis runtime root (where state/ lives)",
    )
    args = parser.parse_args()
    results = ingest_all(
        artifact_root=Path(args.artifact_root),
        runtime_root=Path(args.runtime_root),
    )
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
