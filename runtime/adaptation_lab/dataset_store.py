#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import new_id, now_iso


ROOT = Path(__file__).resolve().parents[2]


def adaptation_datasets_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "adaptation_datasets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _dataset_path(dataset_id: str, *, root: Optional[Path] = None) -> Path:
    return adaptation_datasets_dir(root) / f"{dataset_id}.json"


def register_adaptation_dataset(
    *,
    label: str,
    absolute_path: str,
    dataset_kind: str,
    actor: str,
    lane: str,
    purpose: str = "",
    source_refs: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    payload = {
        "dataset_id": new_id("adaptds"),
        "created_at": timestamp,
        "updated_at": timestamp,
        "label": label,
        "absolute_path": absolute_path,
        "dataset_kind": dataset_kind,
        "purpose": purpose,
        "actor": actor,
        "lane": lane,
        "source_refs": dict(source_refs or {}),
        "metadata": dict(metadata or {}),
        "status": "registered",
        "schema_version": "v5.2",
    }
    _dataset_path(payload["dataset_id"], root=root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def list_adaptation_datasets(*, root: Optional[Path] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(adaptation_datasets_dir(root).glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    return rows


def load_adaptation_dataset(dataset_id: str, *, root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    path = _dataset_path(dataset_id, root=root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
