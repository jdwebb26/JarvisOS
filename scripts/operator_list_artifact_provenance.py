#!/usr/bin/env python3
"""List ingested artifact provenance records visible to the operator.

Shows factory provenance with evidence_files, lifecycle state, and
source references in a compact JSON view matching the operator_list_*
pattern.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import now_iso
from runtime.core.provenance_store import list_artifact_provenance


def _compact_row(record: Any) -> dict[str, Any]:
    d = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    refs = d.get("source_refs") or {}
    return {
        "artifact_provenance_id": d.get("artifact_provenance_id"),
        "artifact_id": d.get("artifact_id"),
        "task_id": d.get("task_id"),
        "actor": d.get("actor"),
        "lane": d.get("lane"),
        "producer_kind": d.get("producer_kind"),
        "lifecycle_state": d.get("lifecycle_state"),
        "candidate_id": refs.get("candidate_id") or d.get("candidate_id"),
        "gate_overall": refs.get("gate_overall"),
        "evidence_files": refs.get("evidence_files", []),
        "artifact_dir": refs.get("artifact_dir"),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
    }


def list_artifact_provenance_view(
    root: Path,
    *,
    limit: int = 20,
    factory_only: bool = False,
    lifecycle_state: str | None = None,
) -> dict[str, Any]:
    rows = list_artifact_provenance(root=root)
    if factory_only:
        rows = [r for r in rows if getattr(r, "producer_kind", None) == "strategy_factory"]
    if lifecycle_state:
        rows = [r for r in rows if getattr(r, "lifecycle_state", "").upper() == lifecycle_state.upper()]
    compact = [_compact_row(r) for r in rows[:limit]]
    return {
        "generated_at": now_iso(),
        "count": len(compact),
        "total": len(rows),
        "rows": compact,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List compact recent artifact provenance records (factory evidence bundles)."
    )
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--factory-only", action="store_true", help="Show only strategy_factory records")
    parser.add_argument("--lifecycle-state", default="", help="Filter by lifecycle state (e.g. PASS, FAIL)")
    args = parser.parse_args()

    payload = list_artifact_provenance_view(
        Path(args.root).resolve(),
        limit=args.limit,
        factory_only=args.factory_only,
        lifecycle_state=args.lifecycle_state or None,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
