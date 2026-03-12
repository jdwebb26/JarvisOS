#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LANES = ["routing", "general", "heavy_reasoning", "coder", "flowstate", "multimodal"]
HEALTHY_STATUSES = {"healthy", "ok", "idle"}


def _state_dir(name: str, *, root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def backend_health_dir(*, root: Optional[Path] = None) -> Path:
    return _state_dir("backend_health", root=root)


def accelerators_dir(*, root: Optional[Path] = None) -> Path:
    return _state_dir("accelerators", root=root)


def _load_json_rows(folder: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(
        key=lambda row: (
            str(row.get("generated_at", "")),
            str(row.get("updated_at", "")),
            str(row.get("created_at", "")),
        ),
        reverse=True,
    )
    return rows


def write_backend_health_snapshot(
    payload: dict[str, Any],
    *,
    root: Optional[Path] = None,
    filename: str = "backend_health_bootstrap_seed.json",
) -> Path:
    path = backend_health_dir(root=root) / filename
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def write_accelerator_summary(
    payload: dict[str, Any],
    *,
    root: Optional[Path] = None,
    filename: str = "accelerator_summary_bootstrap_seed.json",
) -> Path:
    path = accelerators_dir(root=root) / filename
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def list_backend_health_snapshots(*, root: Optional[Path] = None) -> list[dict[str, Any]]:
    return _load_json_rows(backend_health_dir(root=root))


def list_accelerator_summaries(*, root: Optional[Path] = None) -> list[dict[str, Any]]:
    return _load_json_rows(accelerators_dir(root=root))


def ensure_runtime_5_2_prep_state(*, root: Optional[Path] = None) -> dict[str, list[str]]:
    resolved_root = Path(root or ROOT).resolve()
    seeded: list[str] = []

    if not any(backend_health_dir(root=resolved_root).glob("*.json")):
        write_backend_health_snapshot(
            {
                "snapshot_id": "backend_health_bootstrap_seed",
                "generated_at": "bootstrap_seed",
                "source": "bootstrap_seed",
                "notes": [
                    "5.2-prep scaffold only; replace with live backend health probes when routing-core work begins."
                ],
                "nodes": [
                    {
                        "node_id": "local-qwen-node",
                        "label": "local-qwen-node",
                        "status": "healthy",
                        "active": True,
                        "available_backends": ["qwen_policy_default"],
                        "accelerators": ["cpu"],
                        "notes": ["bootstrap_seed"],
                    }
                ],
                "lanes": [
                    {
                        "lane": lane,
                        "backend": "qwen_policy_default",
                        "status": "healthy",
                        "node_id": "local-qwen-node",
                        "notes": ["bootstrap_seed_qwen_first"],
                    }
                    for lane in DEFAULT_LANES
                ],
            },
            root=resolved_root,
        )
        seeded.append("state/backend_health/backend_health_bootstrap_seed.json")

    if not any(accelerators_dir(root=resolved_root).glob("*.json")):
        write_accelerator_summary(
            {
                "summary_id": "accelerator_summary_bootstrap_seed",
                "generated_at": "bootstrap_seed",
                "source": "bootstrap_seed",
                "notes": [
                    "5.2-prep scaffold only; replace with live accelerator inventory when backend/node health probes land."
                ],
                "accelerators": [
                    {
                        "accelerator_id": "cpu-local",
                        "kind": "cpu",
                        "status": "healthy",
                        "node_id": "local-qwen-node",
                        "allocated_lanes": list(DEFAULT_LANES),
                    }
                ],
            },
            root=resolved_root,
        )
        seeded.append("state/accelerators/accelerator_summary_bootstrap_seed.json")

    return {"seeded_files": seeded}


def build_backend_health_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    snapshots = list_backend_health_snapshots(root=root)
    latest = snapshots[0] if snapshots else {}
    lanes = list(latest.get("lanes") or [])
    nodes = list(latest.get("nodes") or [])

    lane_status_counts: dict[str, int] = {}
    for row in lanes:
        status = str(row.get("status") or "unknown")
        lane_status_counts[status] = lane_status_counts.get(status, 0) + 1

    unhealthy_lanes = [
        {
            "lane": row.get("lane"),
            "backend": row.get("backend"),
            "status": row.get("status", "unknown"),
            "node_id": row.get("node_id"),
            "notes": row.get("notes", []),
        }
        for row in lanes
        if str(row.get("status") or "unknown") not in HEALTHY_STATUSES
    ]

    return {
        "snapshot_count": len(snapshots),
        "latest_backend_health": latest or None,
        "lane_count": len(lanes),
        "node_count": len(nodes),
        "lane_status_counts": lane_status_counts,
        "healthy_lane_count": sum(1 for row in lanes if str(row.get("status") or "unknown") in HEALTHY_STATUSES),
        "unhealthy_lane_count": len(unhealthy_lanes),
        "unhealthy_lanes": unhealthy_lanes,
        "qwen_first_live_posture": True,
        "multi_model_ready_scaffolding": True,
    }


def build_accelerator_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    rows = list_accelerator_summaries(root=root)
    latest = rows[0] if rows else {}
    accelerators = list(latest.get("accelerators") or [])
    status_counts: dict[str, int] = {}
    for row in accelerators:
        status = str(row.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "summary_count": len(rows),
        "latest_accelerator_summary": latest or None,
        "accelerator_count": len(accelerators),
        "accelerator_status_counts": status_counts,
        "active_accelerator_count": sum(1 for row in accelerators if str(row.get("status") or "unknown") in HEALTHY_STATUSES),
        "accelerator_kinds": sorted({str(row.get("kind") or "unknown") for row in accelerators}),
    }


def build_active_nodes_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    backend_health = build_backend_health_summary(root=root)
    accelerator_summary = build_accelerator_summary(root=root)
    latest = backend_health.get("latest_backend_health") or {}
    nodes = list(latest.get("nodes") or [])
    active_nodes = [row for row in nodes if row.get("active", False)]
    return {
        "node_count": len(nodes),
        "active_node_count": len(active_nodes),
        "latest_nodes": active_nodes[:5],
        "backends_visible": sorted(
            {
                backend
                for row in active_nodes
                for backend in row.get("available_backends", [])
            }
        ),
        "accelerator_kinds": accelerator_summary.get("accelerator_kinds", []),
    }


def build_degraded_state_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    resolved_root = Path(root or ROOT).resolve()
    backend_health = build_backend_health_summary(root=resolved_root)
    degradation_events = _load_json_rows(_state_dir("degradation_events", root=resolved_root))
    latest_degradation = degradation_events[0] if degradation_events else None
    notes: list[str] = []
    if backend_health["snapshot_count"] == 0:
        notes.append("No backend health snapshot recorded yet.")
    if backend_health["unhealthy_lane_count"]:
        notes.append("One or more backend lanes are marked unhealthy.")
    if not notes:
        notes.append("No backend health degradation is currently reported in the 5.2-prep scaffold.")
    return {
        "degraded_backend_count": backend_health["unhealthy_lane_count"],
        "missing_backend_health": backend_health["snapshot_count"] == 0,
        "latest_degradation_event": latest_degradation,
        "notes": notes,
    }


def build_reroute_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    latest = (build_backend_health_summary(root=root).get("latest_backend_health") or {})
    lanes = list(latest.get("lanes") or [])
    reroute_candidates = [
        {
            "lane": row.get("lane"),
            "backend": row.get("backend"),
            "status": row.get("status"),
            "reroute_target": row.get("reroute_target"),
            "reroute_reason": row.get("reroute_reason"),
        }
        for row in lanes
        if row.get("reroute_target") or row.get("reroute_reason")
    ]
    return {
        "scaffolding_only": True,
        "reroute_event_count": len(reroute_candidates),
        "latest_reroute_candidate": reroute_candidates[0] if reroute_candidates else None,
        "notes": [
            "5.2-prep scaffolding only. Routing-core reroute logic remains deferred to later tickets."
        ],
    }


def build_runtime_5_2_prep_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    resolved_root = Path(root or ROOT).resolve()
    return {
        "active_nodes_summary": build_active_nodes_summary(root=resolved_root),
        "backend_health_summary": build_backend_health_summary(root=resolved_root),
        "accelerator_summary": build_accelerator_summary(root=resolved_root),
        "degraded_state_summary": build_degraded_state_summary(root=resolved_root),
        "reroute_summary": build_reroute_summary(root=resolved_root),
    }
