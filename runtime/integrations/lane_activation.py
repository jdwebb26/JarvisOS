#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import new_id, now_iso


ROOT = Path(__file__).resolve().parents[2]
TARGET_LANES = [
    "shadowbroker",
    "searxng",
    "hermes_bridge",
    "autoresearch_upstream_bridge",
    "adaptation_lab_unsloth",
    "optimizer_dspy",
]


def lane_activation_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "lane_activation"
    path.mkdir(parents=True, exist_ok=True)
    return path


def lane_activation_runs_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "lane_activation_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def record_lane_activation_attempt(
    *,
    lane: str,
    command_or_endpoint: str,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    payload = {
        "activation_run_id": new_id("laneact"),
        "lane": str(lane),
        "started_at": timestamp,
        "completed_at": "",
        "status": "running",
        "runtime_status": "starting",
        "configured": False,
        "healthy": False,
        "command_or_endpoint": str(command_or_endpoint or ""),
        "evidence_refs": {},
        "error": "",
        "details": "",
        "operator_action_required": "",
    }
    return _write_json(lane_activation_runs_dir(root) / f"{payload['activation_run_id']}.json", payload)


def record_lane_activation_result(
    *,
    activation_run_id: str,
    lane: str,
    status: str,
    runtime_status: str,
    configured: bool,
    healthy: bool,
    command_or_endpoint: str,
    evidence_refs: Optional[dict[str, Any]] = None,
    error: str = "",
    details: str = "",
    operator_action_required: str = "",
    started_at: Optional[str] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    existing_path = lane_activation_runs_dir(root) / f"{activation_run_id}.json"
    existing: dict[str, Any] = {}
    if existing_path.exists():
        try:
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    payload = {
        "activation_run_id": activation_run_id,
        "lane": str(lane),
        "started_at": str(started_at or existing.get("started_at") or now_iso()),
        "completed_at": now_iso(),
        "status": str(status),
        "runtime_status": str(runtime_status),
        "configured": bool(configured),
        "healthy": bool(healthy),
        "command_or_endpoint": str(command_or_endpoint or existing.get("command_or_endpoint") or ""),
        "evidence_refs": dict(evidence_refs or {}),
        "error": str(error or ""),
        "details": str(details or ""),
        "operator_action_required": str(operator_action_required or ""),
    }
    _write_json(existing_path, payload)
    _write_json(lane_activation_dir(root) / f"{lane}.json", payload)
    return payload


def list_lane_activation_results(*, root: Optional[Path] = None, lane: Optional[str] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(lane_activation_runs_dir(root).glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if lane and str(row.get("lane") or "") != str(lane):
            continue
        rows.append(row)
    rows.sort(key=lambda row: str(row.get("completed_at") or row.get("started_at") or ""), reverse=True)
    return rows


def latest_lane_activation_result(lane: str, *, root: Optional[Path] = None) -> dict[str, Any] | None:
    path = lane_activation_dir(root) / f"{lane}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    rows = list_lane_activation_results(root=root, lane=lane)
    return rows[0] if rows else None


def summarize_lane_activation(
    *,
    root: Optional[Path] = None,
    extension_lane_status_summary: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    classification_map: dict[str, str] = {}
    for row in list((extension_lane_status_summary or {}).get("rows") or []):
        lane = str(row.get("lane") or "")
        if lane:
            classification_map[lane] = str(row.get("classification") or "")

    rows: list[dict[str, Any]] = []
    counts = {
        "live_lane_count": 0,
        "blocked_lane_count": 0,
        "degraded_lane_count": 0,
        "never_activated_count": 0,
    }
    for lane in TARGET_LANES:
        latest = latest_lane_activation_result(lane, root=root) or {}
        currently_live = bool(latest.get("configured")) and bool(latest.get("healthy")) and str(latest.get("status") or "") == "completed"
        if currently_live:
            counts["live_lane_count"] += 1
        elif latest:
            if str(latest.get("status") or "") == "blocked":
                counts["blocked_lane_count"] += 1
            elif str(latest.get("status") or "") == "degraded":
                counts["degraded_lane_count"] += 1
        else:
            counts["never_activated_count"] += 1
        rows.append(
            {
                "lane": lane,
                "classification": classification_map.get(lane, ""),
                "latest_activation_status": str(latest.get("status") or "not_run"),
                "latest_runtime_status": str(latest.get("runtime_status") or "not_run"),
                "latest_activation_timestamp": str(latest.get("completed_at") or latest.get("started_at") or ""),
                "configured": bool(latest.get("configured")),
                "healthy": bool(latest.get("healthy")),
                "currently_live_on_this_machine": currently_live,
                "command_or_endpoint": str(latest.get("command_or_endpoint") or ""),
                "operator_action_required": str(latest.get("operator_action_required") or ""),
                "error": str(latest.get("error") or ""),
                "details": str(latest.get("details") or ""),
                "evidence_refs": dict(latest.get("evidence_refs") or {}),
            }
        )
    return {
        "summary_kind": "lane_activation",
        "target_lane_count": len(TARGET_LANES),
        "rows": rows,
        **counts,
    }
