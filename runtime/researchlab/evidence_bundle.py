#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import EvidenceBundleRef, new_id, now_iso


ROOT = Path(__file__).resolve().parents[2]


def evidence_bundles_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "evidence_bundles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def evidence_bundle_path(bundle_id: str, *, root: Optional[Path] = None) -> Path:
    return evidence_bundles_dir(root) / f"{bundle_id}.json"


def write_evidence_bundle(
    *,
    actor: str,
    lane: str,
    evidence_kind: str,
    source_records: list[dict[str, Any]],
    result_records: list[dict[str, Any]],
    root: Optional[Path] = None,
    artifact_ids: Optional[list[str]] = None,
    trace_ids: Optional[list[str]] = None,
    eval_result_ids: Optional[list[str]] = None,
    provenance_refs: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if not list(source_records or []) and not list(result_records or []):
        raise ValueError("Evidence bundle requires non-empty source_records or result_records.")
    bundle_id = new_id("evidence")
    timestamp = now_iso()
    ref = EvidenceBundleRef(
        bundle_id=bundle_id,
        artifact_ids=list(artifact_ids or []),
        trace_ids=list(trace_ids or []),
        eval_result_ids=list(eval_result_ids or []),
        provenance_refs=dict(provenance_refs or {}),
        evidence_kind=evidence_kind,
        status="available",
        metadata=dict(metadata or {}),
    )
    payload = {
        "bundle_id": bundle_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "actor": actor,
        "lane": lane,
        "evidence_kind": evidence_kind,
        "status": "available",
        "source_records": list(source_records or []),
        "result_records": list(result_records or []),
        "metadata": dict(metadata or {}),
        "ref": ref.to_dict(),
    }
    evidence_bundle_path(bundle_id, root=root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_evidence_bundle(bundle_id: str, *, root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    path = evidence_bundle_path(bundle_id, root=root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_evidence_bundles(*, root: Optional[Path] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(evidence_bundles_dir(root).glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    return rows


def build_evidence_bundle_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    rows = list_evidence_bundles(root=root)
    kind_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for row in rows:
        kind = str(row.get("evidence_kind") or "unknown")
        status = str(row.get("status") or "unknown")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "evidence_bundle_count": len(rows),
        "evidence_kind_counts": kind_counts,
        "evidence_status_counts": status_counts,
        "latest_evidence_bundle": rows[0] if rows else None,
    }
