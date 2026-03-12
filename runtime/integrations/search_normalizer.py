#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


def normalize_search_results(results: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in list(results or []):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("link") or "").strip()
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("snippet") or item.get("content") or item.get("summary") or "").strip()
        source = str(item.get("source") or item.get("engine") or item.get("domain") or "").strip()
        if not url and not title and not snippet:
            continue
        rows.append(
            {
                "url": url,
                "title": title,
                "snippet": snippet,
                "source": source,
                "published_at": str(item.get("published_at") or item.get("publishedDate") or "").strip(),
                "raw": dict(item),
            }
        )
    return rows


def dedupe_results(results: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for row in normalize_search_results(results):
        key = (str(row.get("url") or "").strip().lower(), str(row.get("title") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def build_source_records(
    results: list[dict[str, Any]] | None,
    *,
    backend_id: str,
    query_text: str = "",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(dedupe_results(results), start=1):
        rows.append(
            {
                "source_id": f"{backend_id}_src_{index}",
                "backend_id": backend_id,
                "query_text": query_text,
                "url": row.get("url", ""),
                "title": row.get("title", ""),
                "snippet": row.get("snippet", ""),
                "source": row.get("source", ""),
                "published_at": row.get("published_at", ""),
            }
        )
    return rows
