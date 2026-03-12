#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]


def experiments_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "experiments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def experiment_path(experiment_id: str, *, root: Optional[Path] = None) -> Path:
    return experiments_dir(root) / f"{experiment_id}.json"


def frontier_path(root: Optional[Path] = None) -> Path:
    return experiments_dir(root) / "frontier.json"


def save_experiment_record(payload: dict[str, Any], *, root: Optional[Path] = None) -> dict[str, Any]:
    path = experiment_path(str(payload["experiment_id"]), root=root)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_experiment_record(experiment_id: str, *, root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    path = experiment_path(experiment_id, root=root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_experiment_records(
    *,
    root: Optional[Path] = None,
    status: Optional[str] = None,
    experiment_kind: Optional[str] = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(experiments_dir(root).glob("*.json")):
        if path.name == "frontier.json":
            continue
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if status and str(row.get("status") or "") != status:
            continue
        if experiment_kind and str(row.get("experiment_kind") or "") != experiment_kind:
            continue
        rows.append(row)
    rows.sort(key=lambda row: (str(row.get("updated_at") or row.get("created_at") or ""), str(row.get("experiment_id") or "")), reverse=True)
    return rows


def save_frontier_record(payload: dict[str, Any], *, root: Optional[Path] = None) -> dict[str, Any]:
    path = frontier_path(root=root)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_frontier_record(*, root: Optional[Path] = None) -> dict[str, Any]:
    path = frontier_path(root=root)
    if not path.exists():
        return {
            "frontier_version": "1",
            "promotion_disabled": True,
            "approval_required": True,
            "frontier_size": 0,
            "experiments": [],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "frontier_version": "1",
            "promotion_disabled": True,
            "approval_required": True,
            "frontier_size": 0,
            "experiments": [],
        }
    payload.setdefault("frontier_version", "1")
    payload.setdefault("promotion_disabled", True)
    payload.setdefault("approval_required", True)
    payload.setdefault("frontier_size", len(payload.get("experiments", [])))
    payload.setdefault("experiments", [])
    return payload


def build_experiment_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    rows = list_experiment_records(root=root)
    frontier = load_frontier_record(root=root)
    status_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    best_score: float | None = None
    for row in rows:
        status = str(row.get("status") or "unknown")
        kind = str(row.get("experiment_kind") or "unknown")
        decision = str(((row.get("keep_or_revert") or {}).get("decision")) or "pending")
        status_counts[status] = status_counts.get(status, 0) + 1
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        aggregate_score = (row.get("score_summary") or {}).get("aggregate_score")
        if isinstance(aggregate_score, (int, float)):
            if best_score is None or float(aggregate_score) > best_score:
                best_score = float(aggregate_score)
    return {
        "experiment_count": len(rows),
        "experiment_status_counts": status_counts,
        "experiment_kind_counts": kind_counts,
        "keep_or_revert_counts": decision_counts,
        "frontier_size": int(frontier.get("frontier_size", 0)),
        "latest_experiment": rows[0] if rows else None,
        "best_aggregate_score": best_score,
        "promotion_disabled": True,
        "approval_required": True,
        "frontier_record": frontier,
    }
