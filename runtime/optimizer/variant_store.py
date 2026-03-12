#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import new_id, now_iso


ROOT = Path(__file__).resolve().parents[2]


def optimizer_variants_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "optimizer_variants"
    path.mkdir(parents=True, exist_ok=True)
    return path


def optimizer_runs_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "optimizer_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _variant_path(variant_id: str, *, root: Optional[Path] = None) -> Path:
    return optimizer_variants_dir(root=root) / f"{variant_id}.json"


def _run_path(run_id: str, *, root: Optional[Path] = None) -> Path:
    return optimizer_runs_dir(root=root) / f"{run_id}.json"


def register_optimizer_variant(
    *,
    actor: str,
    lane: str,
    variant_kind: str,
    base_name: str,
    variant_label: str,
    proposal: dict[str, Any],
    summary: str = "",
    source_refs: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    record = {
        "variant_id": new_id("optvar"),
        "created_at": timestamp,
        "updated_at": timestamp,
        "actor": actor,
        "lane": lane,
        "variant_kind": variant_kind,
        "base_name": base_name,
        "variant_label": variant_label,
        "summary": summary or f"Proposed {variant_kind} variant `{variant_label}` for `{base_name}`.",
        "proposal": dict(proposal or {}),
        "source_refs": dict(source_refs or {}),
        "metadata": {
            "promotion_disabled": True,
            "approval_required": True,
            "authoritative": False,
            **dict(metadata or {}),
        },
        "status": "candidate",
        "latest_run_id": None,
    }
    return save_optimizer_variant(record, root=root)


def save_optimizer_variant(record: dict[str, Any], *, root: Optional[Path] = None) -> dict[str, Any]:
    payload = dict(record)
    payload["updated_at"] = now_iso()
    _variant_path(str(payload["variant_id"]), root=root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_optimizer_variant(variant_id: str, *, root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    path = _variant_path(variant_id, root=root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_optimizer_variants(*, root: Optional[Path] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(optimizer_variants_dir(root=root).glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(key=lambda row: (str(row.get("updated_at") or row.get("created_at") or ""), str(row.get("variant_id") or "")), reverse=True)
    return rows


def create_optimizer_run(
    *,
    variant_id: str,
    actor: str,
    lane: str,
    objective: str,
    baseline_ref: str = "",
    eval_profile: str = "",
    metadata: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    record = {
        "optimizer_run_id": new_id("optrun"),
        "variant_id": variant_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "actor": actor,
        "lane": lane,
        "objective": objective,
        "baseline_ref": baseline_ref,
        "eval_profile": eval_profile,
        "status": "queued",
        "runtime_status": "queued",
        "summary": "",
        "metrics": {},
        "output_refs": {},
        "trace_refs": {},
        "metadata": {
            "promotion_disabled": True,
            "approval_required": True,
            **dict(metadata or {}),
        },
    }
    return save_optimizer_run(record, root=root)


def save_optimizer_run(record: dict[str, Any], *, root: Optional[Path] = None) -> dict[str, Any]:
    payload = dict(record)
    payload["updated_at"] = now_iso()
    _run_path(str(payload["optimizer_run_id"]), root=root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_optimizer_run(run_id: str, *, root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    path = _run_path(run_id, root=root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_optimizer_runs(*, root: Optional[Path] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(optimizer_runs_dir(root=root).glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(key=lambda row: (str(row.get("updated_at") or row.get("created_at") or ""), str(row.get("optimizer_run_id") or "")), reverse=True)
    return rows


def summarize_optimizer_variants(*, root: Optional[Path] = None) -> dict[str, Any]:
    variants = list_optimizer_variants(root=root)
    variant_kind_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for row in variants:
        kind = str(row.get("variant_kind") or "unknown")
        status = str(row.get("status") or "unknown")
        variant_kind_counts[kind] = variant_kind_counts.get(kind, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "variant_count": len(variants),
        "variant_kind_counts": variant_kind_counts,
        "variant_status_counts": status_counts,
        "latest_variant": variants[0] if variants else None,
    }

