#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from runtime.core.models import new_id, now_iso
from runtime.world_ops.models import WorldEventRecord


def normalize_world_event(raw_event: dict[str, Any], *, feed_id: str, collected_at: str | None = None) -> dict[str, Any]:
    timestamp = now_iso()
    event = dict(raw_event or {})
    source_records = list(event.get("source_records") or [])
    result_records = list(event.get("result_records") or [])
    title = str(event.get("title") or event.get("headline") or event.get("name") or "").strip()
    summary = str(event.get("summary") or event.get("snippet") or event.get("description") or "").strip()
    region = str(event.get("region") or event.get("country") or event.get("location") or "").strip()
    event_type = str(event.get("event_type") or event.get("category") or event.get("kind") or "").strip()
    risk_posture = str(event.get("risk_posture") or event.get("severity") or "unknown").strip().lower() or "unknown"
    external_ref = str(event.get("external_ref") or event.get("url") or event.get("source_url") or title).strip()
    normalized = WorldEventRecord(
        event_id=str(event.get("event_id") or new_id("worldevt")),
        created_at=timestamp,
        updated_at=timestamp,
        collected_at=str(collected_at or event.get("collected_at") or timestamp),
        normalized_at=timestamp,
        feed_id=feed_id,
        status=str(event.get("status") or "normalized"),
        title=title,
        summary=summary,
        region=region,
        event_type=event_type,
        risk_posture=risk_posture,
        external_ref=external_ref,
        source_records=source_records,
        result_records=result_records,
        evidence_bundle_ref=event.get("evidence_bundle_ref"),
        raw_event=event,
        metadata=dict(event.get("metadata") or {}),
    )
    return normalized.to_dict()


def dedupe_world_events(events: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in list(events or []):
        key = (
            str(row.get("feed_id") or "").strip().lower(),
            str(row.get("external_ref") or "").strip().lower(),
            str(row.get("title") or "").strip().lower(),
            str(row.get("region") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    deduped.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    return deduped
