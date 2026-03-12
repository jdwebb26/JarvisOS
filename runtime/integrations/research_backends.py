#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Protocol

from runtime.integrations import searxng_client


ROOT = Path(__file__).resolve().parents[2]


class ResearchBackend(Protocol):
    backend_id: str

    def healthcheck(self) -> dict[str, Any]:
        ...

    def search(self, query_text: str, *, actor: str, lane: str) -> dict[str, Any]:
        ...


class SearXNGBackend:
    backend_id = "searxng"

    def __init__(self, *, configured_url: Optional[str] = None, root: Optional[Path] = None) -> None:
        self.configured_url = configured_url
        self.root = Path(root or ROOT).resolve()

    def healthcheck(self) -> dict[str, Any]:
        return searxng_client.healthcheck(configured_url=self.configured_url)

    def search(self, query_text: str, *, actor: str, lane: str) -> dict[str, Any]:
        return searxng_client.search(
            query_text,
            actor=actor,
            lane=lane,
            configured_url=self.configured_url,
            root=self.root,
        )


def list_research_backend_ids() -> list[str]:
    return ["searxng"]


def get_research_backend(
    backend_id: str,
    *,
    configured_url: Optional[str] = None,
    root: Optional[Path] = None,
) -> ResearchBackend:
    normalized = str(backend_id or "").strip().lower()
    if normalized == "searxng":
        return SearXNGBackend(configured_url=configured_url, root=root)
    raise ValueError(f"Unknown research backend: {backend_id}")


def list_research_backends(*, configured_url: Optional[str] = None, root: Optional[Path] = None) -> list[ResearchBackend]:
    return [get_research_backend(backend_id, configured_url=configured_url, root=root) for backend_id in list_research_backend_ids()]


def run_research_backend_healthchecks(*, configured_url: Optional[str] = None, root: Optional[Path] = None) -> dict[str, Any]:
    checks = [backend.healthcheck() for backend in list_research_backends(configured_url=configured_url, root=root)]
    return {
        "backend_count": len(checks),
        "healthy_backend_count": sum(1 for row in checks if row.get("healthy")),
        "latest_healthchecks": checks,
        "available_backend_ids": list_research_backend_ids(),
    }


def build_research_backend_summary(*, configured_url: Optional[str] = None, root: Optional[Path] = None) -> dict[str, Any]:
    health = run_research_backend_healthchecks(configured_url=configured_url, root=root)
    query_rows = searxng_client.list_research_queries(root=root)
    status_counts: dict[str, int] = {}
    for row in query_rows:
        status = str(row.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "research_backend_count": health["backend_count"],
        "healthy_research_backend_count": health["healthy_backend_count"],
        "available_backend_ids": health["available_backend_ids"],
        "latest_backend_healthchecks": health["latest_healthchecks"],
        "research_query_count": len(query_rows),
        "research_query_status_counts": status_counts,
        "latest_research_query": query_rows[0] if query_rows else None,
    }
