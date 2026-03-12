#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import new_id, now_iso
from runtime.integrations.shadowbroker_adapter import (
    build_shadowbroker_watchlist,
    summarize_shadowbroker_anomalies,
    summarize_shadowbroker_backend,
)
from runtime.world_ops.models import WorldOpsBriefRecord, WorldStatusSnapshotRecord
from runtime.world_ops.store import list_world_events, list_world_feeds, world_ops_briefs_dir, world_ops_snapshots_dir


def summarize_world_risk_posture(events: list[dict[str, Any]] | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in list(events or []):
        key = str(row.get("risk_posture") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def summarize_world_regions(events: list[dict[str, Any]] | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in list(events or []):
        key = str(row.get("region") or "unassigned")
        counts[key] = counts.get(key, 0) + 1
    return counts


def summarize_world_event_types(events: list[dict[str, Any]] | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in list(events or []):
        key = str(row.get("event_type") or "uncategorized")
        counts[key] = counts.get(key, 0) + 1
    return counts


def build_world_status_snapshot(*, actor: str = "world_ops", root: Optional[Path] = None) -> dict[str, Any]:
    events = list_world_events(root=root)
    feeds = list_world_feeds(root=root)
    timestamp = now_iso()
    record = WorldStatusSnapshotRecord(
        snapshot_id=new_id("worldsnap"),
        created_at=timestamp,
        updated_at=timestamp,
        actor=actor,
        status="available",
        event_count=len(events),
        degraded_feed_count=sum(1 for row in feeds if str(row.get("status") or "") == "degraded"),
        risk_posture_summary=summarize_world_risk_posture(events),
        region_summary=summarize_world_regions(events),
        event_type_summary=summarize_world_event_types(events),
        latest_event_ids=[str(row.get("event_id") or "") for row in events[:10]],
    )
    path = world_ops_snapshots_dir(root) / f"{record.snapshot_id}.json"
    path.write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return record.to_dict()


def build_world_ops_brief(*, actor: str = "world_ops", root: Optional[Path] = None) -> dict[str, Any]:
    snapshot = build_world_status_snapshot(actor=actor, root=root)
    events = list_world_events(root=root)
    title = "World Ops Brief"
    summary = f"{len(events[:10])} recent world events across {len(summarize_world_regions(events))} regions."
    brief_id = new_id("worldbrief")
    timestamp = now_iso()
    markdown_path = world_ops_briefs_dir(root) / f"{brief_id}.md"
    markdown = [
        f"# {title}",
        "",
        f"- generated_at: {timestamp}",
        f"- recent_event_count: {len(events)}",
        f"- degraded_feed_count: {snapshot['degraded_feed_count']}",
        "",
        "## Risk Posture",
    ]
    for key, value in summarize_world_risk_posture(events).items():
        markdown.append(f"- {key}: {value}")
    markdown.append("")
    markdown.append("## Regions")
    for key, value in summarize_world_regions(events).items():
        markdown.append(f"- {key}: {value}")
    markdown.append("")
    markdown.append("## Latest Events")
    for row in events[:5]:
        markdown.append(f"- {row.get('title') or row.get('event_id')}: {row.get('summary') or ''}")
    markdown_path.write_text("\n".join(markdown) + "\n", encoding="utf-8")
    record = WorldOpsBriefRecord(
        brief_id=brief_id,
        created_at=timestamp,
        updated_at=timestamp,
        actor=actor,
        title=title,
        status="available",
        markdown_path=str(markdown_path),
        summary=summary,
        snapshot_id=str(snapshot.get("snapshot_id") or ""),
        latest_event_ids=list(snapshot.get("latest_event_ids") or []),
    )
    json_path = world_ops_briefs_dir(root) / f"{brief_id}.json"
    json_path.write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return record.to_dict()


def _latest_json(folder: Path) -> dict[str, Any] | None:
    rows: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    if not rows:
        return None
    rows.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    return rows[0]


def build_world_ops_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    events = list_world_events(root=root)
    feeds = list_world_feeds(root=root)
    shadowbroker_summary = summarize_shadowbroker_backend(root=root)
    latest_snapshot = _latest_json(world_ops_snapshots_dir(root))
    latest_brief = _latest_json(world_ops_briefs_dir(root))
    degraded_feeds = [row for row in feeds if str(row.get("status") or "") == "degraded"]
    active_feeds = [row for row in feeds if str(row.get("status") or "") == "active"]
    backend_health_counts: dict[str, int] = {}
    ingestion_kind_counts: dict[str, int] = {}
    feed_rows: list[dict[str, Any]] = []
    for row in feeds:
        backend_health = dict(row.get("last_backend_health") or {})
        backend_status = str(backend_health.get("status") or row.get("last_collection_status") or "unknown")
        backend_health_counts[backend_status] = backend_health_counts.get(backend_status, 0) + 1
        ingestion_kind = str(row.get("ingestion_kind") or "manual")
        ingestion_kind_counts[ingestion_kind] = ingestion_kind_counts.get(ingestion_kind, 0) + 1
        feed_rows.append(
            {
                "feed_id": row.get("feed_id"),
                "label": row.get("label"),
                "ingestion_kind": ingestion_kind,
                "enabled": bool(row.get("enabled", True)),
                "status": row.get("status"),
                "last_collected_at": row.get("last_collected_at"),
                "last_error": row.get("last_error"),
                "backend_ref": row.get("backend_ref", ""),
                "backend_health": backend_health,
                "last_real_event_count": int(row.get("last_real_event_count") or 0),
            }
        )
    return {
        "summary_kind": "world_ops_sidecar",
        "authoritative_runtime": "jarvis_repo_sidecar",
        "sidecar_only": True,
        "active_feed_count": len(active_feeds),
        "degraded_feed_count": len(degraded_feeds),
        "recent_event_count": len(events[:25]),
        "recent_real_collected_event_count": sum(int(row.get("last_real_event_count") or 0) for row in feeds),
        "latest_snapshot_timestamp": (latest_snapshot or {}).get("updated_at") or (latest_snapshot or {}).get("created_at"),
        "latest_brief": latest_brief,
        "latest_event": events[0] if events else None,
        "regions_summary": summarize_world_regions(events),
        "event_types_summary": summarize_world_event_types(events),
        "risk_posture_summary": summarize_world_risk_posture(events),
        "backend_health_counts": backend_health_counts,
        "ingestion_kind_counts": ingestion_kind_counts,
        "feed_rows": feed_rows[:20],
        "recent_events": events[:10],
        "degraded_feeds": degraded_feeds[:10],
        "shadowbroker_backend": shadowbroker_summary,
        "shadowbroker_watchlist": build_shadowbroker_watchlist(root=root),
        "shadowbroker_anomalies": summarize_shadowbroker_anomalies(root=root),
        "shadowbroker_brief": shadowbroker_summary.get("latest_brief"),
    }
