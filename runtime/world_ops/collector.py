#!/usr/bin/env python3
from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import now_iso
from runtime.integrations.search_normalizer import build_source_records
from runtime.integrations import searxng_client
from runtime.integrations.shadowbroker_adapter import fetch_shadowbroker_snapshot
from runtime.world_ops.normalizer import dedupe_world_events, normalize_world_event
from runtime.world_ops.store import list_world_events, load_world_feed, write_world_event, write_world_feed


def _fetch_text(url: str, *, timeout_seconds: float = 5.0) -> str:
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "jarvis-world-ops/1.0"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8", errors="replace")


def _child_text(node: ET.Element, name: str) -> str:
    child = node.find(name)
    return (child.text or "").strip() if child is not None and child.text else ""


def _parse_rss_items(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    rows: list[dict[str, Any]] = []
    channel = root.find("channel")
    if channel is not None:
        for item in channel.findall("item"):
            title = _child_text(item, "title")
            link = _child_text(item, "link")
            summary = _child_text(item, "description")
            category = _child_text(item, "category")
            rows.append(
                {
                    "title": title,
                    "summary": summary,
                    "event_type": category,
                    "external_ref": link or title,
                    "url": link,
                    "source_records": [{"url": link, "title": title, "snippet": summary}] if link or title else [],
                }
            )
    return rows


def _parse_atom_items(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    rows: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ns):
        title = _child_text(entry, "{http://www.w3.org/2005/Atom}title")
        summary = _child_text(entry, "{http://www.w3.org/2005/Atom}summary") or _child_text(entry, "{http://www.w3.org/2005/Atom}content")
        link_node = entry.find("atom:link", ns)
        link = str(link_node.get("href") or "").strip() if link_node is not None else ""
        rows.append(
            {
                "title": title,
                "summary": summary,
                "external_ref": link or title,
                "url": link,
                "source_records": [{"url": link, "title": title, "snippet": summary}] if link or title else [],
            }
        )
    return rows


def _collect_from_xml_feed(feed) -> list[dict[str, Any]]:
    if not feed.configured_url:
        raise ValueError("configured_url is required for rss/atom ingestion")
    xml_text = _fetch_text(feed.configured_url)
    if feed.ingestion_kind == "atom":
        return _parse_atom_items(xml_text)
    return _parse_rss_items(xml_text)


def _collect_from_searxng(feed, *, root: Optional[Path] = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    backend_health = searxng_client.healthcheck(configured_url=feed.configured_url)
    if not backend_health.get("healthy"):
        return [], backend_health
    query_text = str((feed.metadata or {}).get("query_text") or feed.purpose or feed.label).strip()
    response = searxng_client.search(
        query_text,
        actor="world_ops",
        lane="world_ops",
        configured_url=feed.configured_url,
        max_results=int((feed.metadata or {}).get("max_results") or 5),
        root=root,
    )
    if str(response.get("status") or "") != "ok":
        return [], {
            "backend_id": "searxng",
            "status": str(response.get("status") or "failed"),
            "healthy": False,
            "details": str(response.get("error") or response.get("status") or "search failed"),
        }
    rows: list[dict[str, Any]] = []
    for item in list(response.get("results") or []):
        rows.append(
            {
                "title": str(item.get("title") or "").strip(),
                "summary": str(item.get("snippet") or "").strip(),
                "event_type": str((feed.categories or ["search_result"])[0]),
                "risk_posture": str((feed.metadata or {}).get("default_risk_posture") or "unknown"),
                "region": str((feed.regions or ["global"])[0]),
                "external_ref": str(item.get("url") or item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "source_records": build_source_records([item], backend_id="searxng", query_text=query_text),
                "metadata": {"query_text": query_text, "backend_id": "searxng"},
            }
        )
    return rows, backend_health


def collect_world_feed(
    feed_id: str,
    *,
    actor: str = "world_ops",
    lane: str = "world_ops",
    raw_items: list[dict[str, Any]] | None = None,
    failure_reason: str = "",
    root: Optional[Path] = None,
) -> dict[str, Any]:
    feed = load_world_feed(feed_id, root=root)
    if feed is None:
        raise ValueError(f"Unknown world feed: {feed_id}")
    timestamp = now_iso()
    if not feed.enabled:
        feed.status = "disabled"
        feed.updated_at = timestamp
        feed.last_collection_status = "disabled"
        write_world_feed(feed, root=root)
        return {"ok": False, "feed_id": feed_id, "status": "disabled", "written_event_ids": []}
    if failure_reason:
        feed.status = "degraded"
        feed.updated_at = timestamp
        feed.last_collection_status = "unavailable"
        feed.last_error = failure_reason
        write_world_feed(feed, root=root)
        return {
            "ok": False,
            "feed_id": feed_id,
            "status": "unavailable",
            "failure_reason": failure_reason,
            "written_event_ids": [],
        }

    backend_health: dict[str, Any] = {}
    collected_items = list(raw_items or [])
    if not collected_items and feed.ingestion_kind in {"rss", "atom"}:
        try:
            collected_items = _collect_from_xml_feed(feed)
        except Exception as exc:
            feed.status = "degraded"
            feed.updated_at = timestamp
            feed.last_collection_status = "unavailable"
            feed.last_error = f"{type(exc).__name__}: {exc}"
            write_world_feed(feed, root=root)
            return {
                "ok": False,
                "feed_id": feed_id,
                "status": "unavailable",
                "failure_reason": feed.last_error,
                "written_event_ids": [],
            }
    elif not collected_items and feed.ingestion_kind == "searxng_search":
        collected_items, backend_health = _collect_from_searxng(feed, root=root)
        if backend_health and not backend_health.get("healthy"):
            feed.status = "degraded"
            feed.updated_at = timestamp
            feed.last_collection_status = str(backend_health.get("status") or "unavailable")
            feed.last_error = str(backend_health.get("details") or backend_health.get("status") or "backend unavailable")
            feed.last_backend_health = dict(backend_health)
            write_world_feed(feed, root=root)
            return {
                "ok": False,
                "feed_id": feed_id,
                "status": "degraded",
                "failure_reason": feed.last_error,
                "backend_health": backend_health,
                "written_event_ids": [],
            }
    elif not collected_items and feed.ingestion_kind == "shadowbroker":
        shadowbroker = fetch_shadowbroker_snapshot(
            feed_id=feed_id,
            metadata_override={
                "base_url": feed.configured_url or "",
                **dict(feed.metadata or {}),
            },
            actor=actor,
            lane=lane,
            root=root,
        )
        backend_health = dict(shadowbroker.get("health") or {})
        if not shadowbroker.get("ok"):
            feed.status = "degraded"
            feed.updated_at = timestamp
            feed.last_collection_status = str(shadowbroker.get("backend_status") or "degraded")
            feed.last_error = str(shadowbroker.get("degraded_reason") or shadowbroker.get("backend_status") or "shadowbroker unavailable")
            feed.last_backend_health = dict(backend_health)
            write_world_feed(feed, root=root)
            return {
                "ok": False,
                "feed_id": feed_id,
                "status": "degraded",
                "failure_reason": feed.last_error,
                "backend_health": backend_health,
                "written_event_ids": [],
            }
        collected_items = list(shadowbroker.get("normalized_events") or [])

    existing = list_world_events(root=root)
    normalized = [normalize_world_event(item, feed_id=feed_id, collected_at=timestamp) for item in list(raw_items or [])]
    if feed.ingestion_kind == "shadowbroker":
        normalized = list(collected_items)
    elif collected_items is not raw_items:
        normalized = [normalize_world_event(item, feed_id=feed_id, collected_at=timestamp) for item in collected_items]
    deduped = dedupe_world_events(existing + normalized)
    existing_ids = {str(row.get("event_id") or "") for row in existing}
    written: list[str] = []
    for row in deduped:
        event_id = str(row.get("event_id") or "")
        if event_id in existing_ids:
            continue
        stored = write_world_event(row, actor=actor, lane=lane, root=root)
        written.append(str(stored.get("event_id") or ""))
    feed.status = "active"
    feed.updated_at = timestamp
    feed.last_collection_status = "ok"
    feed.last_collected_at = timestamp
    feed.last_error = ""
    feed.last_backend_health = dict(backend_health)
    feed.last_real_event_count = len(written)
    write_world_feed(feed, root=root)
    return {
        "ok": True,
        "feed_id": feed_id,
        "status": "ok",
        "normalized_count": len(normalized),
        "backend_health": backend_health,
        "written_event_ids": written,
    }
