#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import HeartbeatReportRecord, HeartbeatStatus, NodeRole, NodeStatus, new_id, now_iso
from runtime.core.node_registry import (
    ensure_default_nodes,
    get_node,
    list_nodes,
    save_node,
    worker_heartbeats_dir,
)


def heartbeat_reports_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "heartbeat_reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _heartbeat_path(node_name: str, *, root: Optional[Path] = None) -> Path:
    safe_name = str(node_name or "unknown").strip().lower().replace(" ", "_")
    return worker_heartbeats_dir(root=root) / f"{safe_name}.json"


def _path(heartbeat_report_id: str, *, root: Optional[Path] = None) -> Path:
    return heartbeat_reports_dir(root) / f"{heartbeat_report_id}.json"


def _parse_iso(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def heartbeat_is_stale(heartbeat: dict[str, Any] | None, *, stale_after_seconds: int = 300) -> bool:
    if not heartbeat:
        return True
    observed_at = _parse_iso(str(heartbeat.get("observed_at") or heartbeat.get("updated_at") or ""))
    if observed_at is None:
        return True
    age_seconds = (datetime.now(timezone.utc) - observed_at.astimezone(timezone.utc)).total_seconds()
    return age_seconds > stale_after_seconds


def write_node_heartbeat(
    *,
    node_name: str,
    status: str = HeartbeatStatus.HEALTHY.value,
    actor: str = "system",
    lane: str = "heartbeat",
    current_task_count: int = 0,
    backend_summary: Optional[list[str]] = None,
    model_family_summary: Optional[list[str]] = None,
    capability_summary: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
    observed_at: Optional[str] = None,
) -> dict[str, Any]:
    ensure_default_nodes(root=root)
    node = get_node(node_name, root=root)
    if node is None:
        raise ValueError(f"Node not found: {node_name}")
    timestamp = observed_at or now_iso()
    effective_node_status = node.status
    if status == HeartbeatStatus.UNREACHABLE.value:
        effective_node_status = NodeStatus.UNREACHABLE.value
    elif status == HeartbeatStatus.DEGRADED.value:
        effective_node_status = NodeStatus.DEGRADED.value
    elif status == HeartbeatStatus.STOPPED.value:
        effective_node_status = NodeStatus.STOPPED.value
    elif status == HeartbeatStatus.HEALTHY.value:
        effective_node_status = NodeStatus.HEALTHY.value
    payload = {
        "node_name": node.node_name,
        "node_role": node.node_role,
        "node_status": effective_node_status,
        "heartbeat_status": status,
        "observed_at": timestamp,
        "updated_at": now_iso(),
        "actor": actor,
        "lane": lane,
        "current_task_count": int(current_task_count),
        "available_backends": list(backend_summary if backend_summary is not None else node.available_backends),
        "accelerator_refs": list(node.accelerator_refs or []),
        "model_family_summary": list(model_family_summary if model_family_summary is not None else (node.metadata or {}).get("model_family_summary", [])),
        "capability_summary": dict(capability_summary or {}),
        "metadata": dict(metadata or {}),
        "scaffolding_only": bool((node.metadata or {}).get("scaffolding_only", False)),
    }
    _heartbeat_path(node_name, root=root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    node.metadata = {
        **dict(node.metadata or {}),
        "last_seen_at": timestamp,
        "last_heartbeat_status": status,
        "last_current_task_count": int(current_task_count),
    }
    node.status = effective_node_status
    save_node(node, root=root)
    return payload


def read_node_heartbeat(node_name: str, *, root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    path = _heartbeat_path(node_name, root=root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_node_heartbeats(*, root: Optional[Path] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(worker_heartbeats_dir(root=root).glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(key=lambda row: str(row.get("observed_at") or row.get("updated_at") or ""), reverse=True)
    return rows


def list_online_nodes(*, root: Optional[Path] = None, stale_after_seconds: int = 300) -> list[dict[str, Any]]:
    online: list[dict[str, Any]] = []
    for node in list_nodes(root=root):
        heartbeat = read_node_heartbeat(node.node_name, root=root)
        if heartbeat_is_stale(heartbeat, stale_after_seconds=stale_after_seconds):
            continue
        if str((heartbeat or {}).get("heartbeat_status")) == HeartbeatStatus.STOPPED.value:
            continue
        online.append(
            {
                "node_name": node.node_name,
                "node_role": node.node_role,
                "node_status": node.status,
                "heartbeat_status": (heartbeat or {}).get("heartbeat_status"),
                "last_seen_at": (heartbeat or {}).get("observed_at"),
                "available_backends": (heartbeat or {}).get("available_backends", []),
                "model_family_summary": (heartbeat or {}).get("model_family_summary", []),
            }
        )
    return online


def build_node_health_summary(*, root: Optional[Path] = None, stale_after_seconds: int = 300) -> dict[str, Any]:
    ensure_default_nodes(root=root)
    nodes = list_nodes(root=root)
    heartbeats = {str(row.get("node_name")): row for row in list_node_heartbeats(root=root)}
    online_nodes = list_online_nodes(root=root, stale_after_seconds=stale_after_seconds)
    status_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    stale_nodes: list[dict[str, Any]] = []
    node_rows: list[dict[str, Any]] = []
    for node in nodes:
        role_counts[node.node_role] = role_counts.get(node.node_role, 0) + 1
        heartbeat = heartbeats.get(node.node_name)
        stale = heartbeat_is_stale(heartbeat, stale_after_seconds=stale_after_seconds)
        derived_status = node.status
        if stale:
            derived_status = NodeStatus.UNREACHABLE.value if node.node_role == NodeRole.PRIMARY.value else NodeStatus.STOPPED.value
        status_counts[derived_status] = status_counts.get(derived_status, 0) + 1
        row = {
            "node_name": node.node_name,
            "node_role": node.node_role,
            "registered_status": node.status,
            "effective_status": derived_status,
            "heartbeat_status": (heartbeat or {}).get("heartbeat_status"),
            "last_seen_at": (heartbeat or {}).get("observed_at") or (node.metadata or {}).get("last_seen_at"),
            "stale_heartbeat": stale,
            "available_backends": list((heartbeat or {}).get("available_backends", node.available_backends)),
            "accelerator_refs": list(node.accelerator_refs or []),
            "model_family_summary": list((heartbeat or {}).get("model_family_summary", (node.metadata or {}).get("model_family_summary", []))),
            "capability_summary": dict((heartbeat or {}).get("capability_summary", {})),
            "optional": bool((node.metadata or {}).get("optional", False)),
            "scaffolding_only": bool((node.metadata or {}).get("scaffolding_only", False)),
        }
        node_rows.append(row)
        if stale:
            stale_nodes.append(
                {
                    "node_name": node.node_name,
                    "node_role": node.node_role,
                    "last_seen_at": row["last_seen_at"],
                    "optional": row["optional"],
                }
            )
    primary_online = [row for row in online_nodes if row.get("node_role") == NodeRole.PRIMARY.value]
    burst_online = [row for row in online_nodes if row.get("node_role") == NodeRole.BURST.value]
    return {
        "registered_node_count": len(nodes),
        "online_node_count": len(online_nodes),
        "stale_heartbeat_count": len(stale_nodes),
        "node_role_counts": role_counts,
        "node_status_counts": status_counts,
        "primary_online_count": len(primary_online),
        "burst_online_count": len(burst_online),
        "online_nodes": online_nodes,
        "stale_nodes": stale_nodes,
        "nodes": node_rows,
        "latest_primary_node": primary_online[0] if primary_online else next((row for row in node_rows if row["node_role"] == NodeRole.PRIMARY.value), None),
        "latest_burst_nodes": burst_online[:5],
        "stale_after_seconds": stale_after_seconds,
    }


def save_heartbeat_report(record: HeartbeatReportRecord, *, root: Optional[Path] = None) -> HeartbeatReportRecord:
    record.updated_at = now_iso()
    _path(record.heartbeat_report_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def list_heartbeat_reports(*, root: Optional[Path] = None) -> list[HeartbeatReportRecord]:
    rows: list[HeartbeatReportRecord] = []
    for path in heartbeat_reports_dir(root).glob("*.json"):
        try:
            rows.append(HeartbeatReportRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: (row.updated_at, row.created_at), reverse=True)
    return rows


def list_latest_heartbeat_reports_by_subsystem(*, root: Optional[Path] = None) -> list[HeartbeatReportRecord]:
    latest: dict[str, HeartbeatReportRecord] = {}
    for row in list_heartbeat_reports(root=root):
        current = latest.get(row.subsystem_name)
        if current is None or (row.updated_at, row.created_at) > (current.updated_at, current.created_at):
            latest[row.subsystem_name] = row
    return sorted(latest.values(), key=lambda row: row.subsystem_name)


def build_heartbeat_report_summary(*, root: Optional[Path] = None) -> dict:
    ensure_default_nodes(root=root)
    all_rows = list_heartbeat_reports(root=root)
    latest = list_latest_heartbeat_reports_by_subsystem(root=root)
    node_health_summary = build_node_health_summary(root=root)
    counts: dict[str, int] = {}
    for row in latest:
        counts[row.status] = counts.get(row.status, 0) + 1
    overall_status = HeartbeatStatus.HEALTHY.value
    if counts.get(HeartbeatStatus.UNREACHABLE.value):
        overall_status = HeartbeatStatus.UNREACHABLE.value
    elif counts.get(HeartbeatStatus.STOPPED.value):
        overall_status = HeartbeatStatus.STOPPED.value
    elif counts.get(HeartbeatStatus.DEGRADED.value):
        overall_status = HeartbeatStatus.DEGRADED.value
    return {
        "heartbeat_report_count": len(list_heartbeat_reports(root=root)),
        "latest_subsystem_heartbeat_count": len(latest),
        "heartbeat_status_counts": counts,
        "overall_heartbeat_status": overall_status,
        "node_registry_summary": {
            "registered_node_count": node_health_summary["registered_node_count"],
            "node_role_counts": node_health_summary["node_role_counts"],
            "node_status_counts": node_health_summary["node_status_counts"],
            "latest_primary_node": node_health_summary["latest_primary_node"],
        },
        "node_health_summary": node_health_summary,
        "latest_heartbeats": [row.to_dict() for row in latest],
        "latest_heartbeat_report": all_rows[0].to_dict() if all_rows else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current durable HeartbeatReport summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_heartbeat_report_summary(root=Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
