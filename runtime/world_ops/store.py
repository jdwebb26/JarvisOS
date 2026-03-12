#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import now_iso
from runtime.researchlab.evidence_bundle import write_evidence_bundle
from runtime.world_ops.models import WorldEventRecord, WorldFeedRecord


ROOT = Path(__file__).resolve().parents[2]


def world_ops_feeds_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "world_ops_feeds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def world_ops_events_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "world_ops_events"
    path.mkdir(parents=True, exist_ok=True)
    return path


def world_ops_briefs_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "world_ops_briefs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def world_ops_snapshots_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "world_ops_snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _feed_path(feed_id: str, *, root: Optional[Path] = None) -> Path:
    return world_ops_feeds_dir(root) / f"{feed_id}.json"


def _event_path(event_id: str, *, root: Optional[Path] = None) -> Path:
    return world_ops_events_dir(root) / f"{event_id}.json"


def load_world_feed(feed_id: str, *, root: Optional[Path] = None) -> Optional[WorldFeedRecord]:
    path = _feed_path(feed_id, root=root)
    if not path.exists():
        return None
    return WorldFeedRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def register_world_feed(
    *,
    feed_id: str,
    label: str,
    purpose: str,
    ingestion_kind: str = "manual",
    configured_url: str = "",
    enabled: bool = True,
    collection_interval_hint: str = "",
    backend_ref: str = "",
    parser_ref: str = "",
    tags: list[str] | None = None,
    regions: list[str] | None = None,
    categories: list[str] | None = None,
    allowed_operations: list[str] | None = None,
    status: str = "active",
    owner: str = "",
    runtime_notes: str = "",
    metadata: dict[str, Any] | None = None,
    root: Optional[Path] = None,
) -> WorldFeedRecord:
    existing = load_world_feed(feed_id, root=root)
    timestamp = now_iso()
    record = WorldFeedRecord(
        feed_id=feed_id,
        created_at=existing.created_at if existing else timestamp,
        updated_at=timestamp,
        label=label,
        purpose=purpose,
        ingestion_kind=ingestion_kind,
        configured_url=configured_url,
        enabled=enabled if existing is None else bool(enabled),
        collection_interval_hint=collection_interval_hint,
        backend_ref=backend_ref,
        parser_ref=parser_ref,
        tags=list(tags or []),
        regions=list(regions or []),
        categories=list(categories or []),
        allowed_operations=list(allowed_operations or ["collect", "summarize"]),
        status=status,
        owner=owner,
        runtime_notes=runtime_notes,
        last_collection_status=existing.last_collection_status if existing else "",
        last_collected_at=existing.last_collected_at if existing else "",
        last_error=existing.last_error if existing else "",
        last_backend_health=dict(existing.last_backend_health if existing else {}),
        last_real_event_count=int(existing.last_real_event_count if existing else 0),
        metadata=dict(metadata or {}),
    )
    _feed_path(feed_id, root=root).write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return record


def list_world_feeds(*, root: Optional[Path] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(world_ops_feeds_dir(root).glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    return rows


def write_world_feed(record: WorldFeedRecord, *, root: Optional[Path] = None) -> WorldFeedRecord:
    _feed_path(record.feed_id, root=root).write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return record


def write_world_event(
    event: dict[str, Any],
    *,
    actor: str = "world_ops",
    lane: str = "world_ops",
    root: Optional[Path] = None,
) -> dict[str, Any]:
    payload = dict(event)
    if (payload.get("source_records") or payload.get("result_records")) and not payload.get("evidence_bundle_ref"):
        evidence = write_evidence_bundle(
            actor=actor,
            lane=lane,
            evidence_kind="world_ops",
            source_records=list(payload.get("source_records") or []),
            result_records=list(payload.get("result_records") or []),
            root=root,
            metadata={
                "feed_id": payload.get("feed_id"),
                "event_id": payload.get("event_id"),
                "world_ops": True,
            },
        )
        payload["evidence_bundle_ref"] = dict((evidence.get("ref") or {}))
    record = WorldEventRecord.from_dict(payload)
    record.updated_at = now_iso()
    _event_path(record.event_id, root=root).write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return record.to_dict()


def list_world_events(*, root: Optional[Path] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(world_ops_events_dir(root).glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    return rows
