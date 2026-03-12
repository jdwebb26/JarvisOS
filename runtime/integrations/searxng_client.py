#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import new_id, now_iso
from runtime.integrations.search_normalizer import dedupe_results


ROOT = Path(__file__).resolve().parents[2]


def research_queries_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "research_queries"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _query_path(query_id: str, *, root: Optional[Path] = None) -> Path:
    return research_queries_dir(root) / f"{query_id}.json"


def configured_searxng_url(*, configured_url: Optional[str] = None) -> str:
    return str(configured_url or os.environ.get("JARVIS_SEARXNG_URL") or "").strip()


def _save_query_record(payload: dict[str, Any], *, root: Optional[Path] = None) -> dict[str, Any]:
    _query_path(str(payload["query_id"]), root=root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def list_research_queries(*, root: Optional[Path] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(research_queries_dir(root).glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    return rows


def healthcheck(*, configured_url: Optional[str] = None, timeout_seconds: float = 1.0) -> dict[str, Any]:
    base_url = configured_searxng_url(configured_url=configured_url)
    if not base_url:
        return {
            "backend_id": "searxng",
            "status": "not_configured",
            "healthy": False,
            "configured_url": "",
            "details": "JARVIS_SEARXNG_URL is not configured.",
        }
    request = urllib.request.Request(base_url.rstrip("/") + "/healthz", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(getattr(response, "status", 200))
    except Exception as exc:
        return {
            "backend_id": "searxng",
            "status": "unreachable",
            "healthy": False,
            "configured_url": base_url,
            "details": f"{type(exc).__name__}: {exc}",
        }
    return {
        "backend_id": "searxng",
        "status": "healthy" if status_code < 400 else "unhealthy",
        "healthy": status_code < 400,
        "configured_url": base_url,
        "details": f"http_status={status_code}",
    }


def search(
    query_text: str,
    *,
    actor: str,
    lane: str,
    configured_url: Optional[str] = None,
    root: Optional[Path] = None,
    timeout_seconds: float = 3.0,
    max_results: int = 5,
) -> dict[str, Any]:
    base_url = configured_searxng_url(configured_url=configured_url)
    query_id = new_id("rq")
    payload = {
        "query_id": query_id,
        "backend_id": "searxng",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "actor": actor,
        "lane": lane,
        "query_text": query_text,
        "configured_url": base_url,
        "status": "failed",
        "result_count": 0,
        "results": [],
        "error": "",
    }
    if not query_text.strip():
        payload["error"] = "query_text is required"
        return _save_query_record(payload, root=root)
    if not base_url:
        payload["status"] = "not_configured"
        payload["error"] = "JARVIS_SEARXNG_URL is not configured."
        return _save_query_record(payload, root=root)

    params = urllib.parse.urlencode({"q": query_text, "format": "json"})
    url = base_url.rstrip("/") + "/search?" + params
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", 200))
        data = json.loads(body or "{}")
        results = dedupe_results(list((data.get("results") or [])[: max(int(max_results), 0)]))
        payload["status"] = "ok" if status_code < 400 else "failed"
        payload["result_count"] = len(results)
        payload["results"] = results
    except Exception as exc:
        payload["status"] = "unreachable"
        payload["error"] = f"{type(exc).__name__}: {exc}"
    payload["updated_at"] = now_iso()
    return _save_query_record(payload, root=root)
