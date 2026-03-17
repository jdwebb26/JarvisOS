#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.request
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import now_iso
from runtime.researchlab.evidence_bundle import build_evidence_bundle_summary, write_evidence_bundle


ROOT = Path(__file__).resolve().parents[2]


def shadowbroker_snapshots_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "shadowbroker_snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def shadowbroker_events_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "shadowbroker_events"
    path.mkdir(parents=True, exist_ok=True)
    return path


def shadowbroker_backend_health_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "shadowbroker_backend_health"
    path.mkdir(parents=True, exist_ok=True)
    return path


def shadowbroker_briefs_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "shadowbroker_briefs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _bool_env(value: str | None, *, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _runtime_config(*, metadata_override: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    override = dict(metadata_override or {})
    base_url = str(override.get("base_url") or os.environ.get("JARVIS_SHADOWBROKER_BASE_URL") or "").strip()
    api_key = str(override.get("api_key") or os.environ.get("JARVIS_SHADOWBROKER_API_KEY") or "").strip()
    timeout_seconds = float(override.get("timeout_seconds") or os.environ.get("JARVIS_SHADOWBROKER_TIMEOUT_SECONDS") or 5.0)
    verify_ssl = _bool_env(
        str(override.get("verify_ssl")) if "verify_ssl" in override else os.environ.get("JARVIS_SHADOWBROKER_VERIFY_SSL"),
        default=True,
    )
    return {
        "base_url": base_url,
        "api_key": api_key,
        "timeout_seconds": timeout_seconds,
        "verify_ssl": verify_ssl,
    }


def validate_shadowbroker_runtime(*, metadata_override: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    config = _runtime_config(metadata_override=metadata_override)
    if not config["base_url"]:
        return {
            "configured": False,
            "status": "blocked_shadowbroker_not_configured",
            "reason": "JARVIS_SHADOWBROKER_BASE_URL is not configured.",
            **config,
        }
    parsed = urlparse(config["base_url"])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {
            "configured": False,
            "status": "blocked_shadowbroker_invalid_config",
            "reason": "JARVIS_SHADOWBROKER_BASE_URL must be a valid http(s) URL.",
            **config,
        }
    if float(config["timeout_seconds"]) <= 0:
        return {
            "configured": False,
            "status": "blocked_shadowbroker_invalid_config",
            "reason": "JARVIS_SHADOWBROKER_TIMEOUT_SECONDS must be greater than zero.",
            **config,
        }
    return {
        "configured": True,
        "status": "configured",
        "reason": "",
        **config,
    }


def _urlopen(url: str, *, headers: dict[str, str], timeout_seconds: float, verify_ssl: bool):
    request = urllib.request.Request(url, method="GET", headers=headers)
    context = None
    if not verify_ssl:
        context = ssl._create_unverified_context()
    return urllib.request.urlopen(request, timeout=timeout_seconds, context=context)


def _write_json(folder: Path, record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    (folder / f"{record_id}.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _persist_backend_health(
    *,
    status: str,
    configured: bool,
    healthy: bool,
    base_url: str,
    degraded_reason: str,
    timeout_seconds: float | None,
    latency_ms: int | None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    payload = {
        "backend_id": "shadowbroker",
        "created_at": timestamp,
        "updated_at": timestamp,
        "configured": configured,
        "status": status,
        "healthy": healthy,
        "base_url": base_url,
        "degraded_reason": degraded_reason,
        "timeout_seconds": timeout_seconds,
        "latency_ms": latency_ms,
    }
    return _write_json(shadowbroker_backend_health_dir(root), "latest", payload)


def _list_json(folder: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    return rows


def _latest_json(folder: Path) -> dict[str, Any] | None:
    rows = _list_json(folder)
    return rows[0] if rows else None


def _age_seconds(timestamp: str | None) -> int | None:
    if not timestamp:
        return None
    try:
        normalized = str(timestamp).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
    except Exception:
        return None


def healthcheck_shadowbroker(
    *,
    metadata_override: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    runtime = validate_shadowbroker_runtime(metadata_override=metadata_override)
    timestamp = now_iso()
    started = time.monotonic()
    payload = {
        "backend_id": "shadowbroker",
        "created_at": timestamp,
        "updated_at": timestamp,
        "configured": runtime["configured"],
        "status": runtime["status"],
        "healthy": False,
        "base_url": runtime["base_url"],
        "degraded_reason": runtime["reason"],
        "timeout_seconds": runtime["timeout_seconds"],
        "latency_ms": None,
    }
    if not runtime["configured"]:
        return _write_json(shadowbroker_backend_health_dir(root), "latest", payload)
    headers = {"User-Agent": "jarvis-shadowbroker/1.0"}
    if runtime["api_key"]:
        headers["Authorization"] = f"Bearer {runtime['api_key']}"
    try:
        with _urlopen(
            runtime["base_url"].rstrip("/") + "/healthz",
            headers=headers,
            timeout_seconds=float(runtime["timeout_seconds"]),
            verify_ssl=bool(runtime["verify_ssl"]),
        ) as response:
            status_code = int(getattr(response, "status", 200))
        payload["latency_ms"] = int((time.monotonic() - started) * 1000)
        payload["status"] = "healthy" if status_code < 400 else "degraded_shadowbroker_unreachable"
        payload["healthy"] = status_code < 400
        payload["degraded_reason"] = "" if payload["healthy"] else f"http_status={status_code}"
    except Exception as exc:
        payload["latency_ms"] = int((time.monotonic() - started) * 1000)
        payload["status"] = "degraded_shadowbroker_unreachable"
        payload["healthy"] = False
        payload["degraded_reason"] = f"{type(exc).__name__}: {exc}"
    return _write_json(shadowbroker_backend_health_dir(root), "latest", payload)


def normalize_shadowbroker_events(
    payload: dict[str, Any],
    *,
    feed_id: str,
    collected_at: Optional[str] = None,
) -> list[dict[str, Any]]:
    timestamp = collected_at or now_iso()
    raw_events = list(payload.get("events") or [])
    normalized: list[dict[str, Any]] = []
    for row in raw_events:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("headline") or row.get("event_id") or "").strip()
        summary = str(row.get("summary") or row.get("description") or "").strip()
        external_ref = str(row.get("url") or row.get("external_ref") or row.get("event_id") or title).strip()
        source_records = list(row.get("source_records") or [])
        if not source_records and (row.get("url") or title):
            source_records = [
                {
                    "url": str(row.get("url") or ""),
                    "title": title,
                    "snippet": summary,
                    "source_type": "shadowbroker",
                }
            ]
        normalized.append(
            {
                "event_id": str(row.get("event_id") or f"{feed_id}_{abs(hash((title, external_ref)))}"),
                "created_at": timestamp,
                "updated_at": timestamp,
                "collected_at": timestamp,
                "normalized_at": timestamp,
                "feed_id": feed_id,
                "status": "available",
                "title": title or "shadowbroker_event",
                "summary": summary,
                "region": str(row.get("region") or "global"),
                "event_type": str(row.get("event_type") or row.get("category") or "shadowbroker_signal"),
                "risk_posture": str(row.get("risk_posture") or "unknown"),
                "external_ref": external_ref,
                "source_records": source_records,
                "result_records": list(row.get("result_records") or []),
                "raw_event": dict(row),
                "metadata": {
                    "backend_id": "shadowbroker",
                    "feed_id": feed_id,
                },
            }
        )
    return normalized


def build_shadowbroker_evidence_bundle(
    *,
    actor: str,
    lane: str,
    feed_id: str,
    snapshot_payload: dict[str, Any],
    normalized_events: list[dict[str, Any]],
    root: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    source_records: list[dict[str, Any]] = []
    result_records: list[dict[str, Any]] = []
    for row in normalized_events:
        source_records.extend(list(row.get("source_records") or []))
        result_records.extend(list(row.get("result_records") or []))
    if not source_records and not result_records:
        return None
    return write_evidence_bundle(
        actor=actor,
        lane=lane,
        evidence_kind="shadowbroker",
        source_records=source_records,
        result_records=result_records,
        root=root,
        metadata={
            "feed_id": feed_id,
            "snapshot_id": snapshot_payload.get("snapshot_id"),
            "backend_id": "shadowbroker",
        },
    )


def persist_shadowbroker_snapshot(
    *,
    actor: str,
    lane: str,
    feed_id: str,
    snapshot_payload: dict[str, Any],
    normalized_events: list[dict[str, Any]],
    root: Optional[Path] = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    evidence = build_shadowbroker_evidence_bundle(
        actor=actor,
        lane=lane,
        feed_id=feed_id,
        snapshot_payload=snapshot_payload,
        normalized_events=normalized_events,
        root=root,
    )
    payload = {
        "snapshot_id": str(snapshot_payload.get("snapshot_id") or f"shadowbroker_{feed_id}_{timestamp}"),
        "created_at": timestamp,
        "updated_at": timestamp,
        "actor": actor,
        "lane": lane,
        "feed_id": feed_id,
        "backend_id": "shadowbroker",
        "status": "available",
        "event_count": len(normalized_events),
        "payload": dict(snapshot_payload),
        "evidence_bundle_ref": dict((evidence or {}).get("ref") or {}) or None,
    }
    snapshot = _write_json(shadowbroker_snapshots_dir(root), payload["snapshot_id"], payload)
    for row in normalized_events:
        event_payload = dict(row)
        event_payload["snapshot_id"] = snapshot["snapshot_id"]
        event_payload["evidence_bundle_ref"] = dict((evidence or {}).get("ref") or {}) or event_payload.get("evidence_bundle_ref")
        _write_json(shadowbroker_events_dir(root), str(event_payload.get("event_id") or now_iso()), event_payload)
    return snapshot


def fetch_shadowbroker_snapshot(
    *,
    feed_id: str,
    metadata_override: Optional[dict[str, Any]] = None,
    actor: str = "world_ops",
    lane: str = "world_ops",
    root: Optional[Path] = None,
) -> dict[str, Any]:
    health = healthcheck_shadowbroker(metadata_override=metadata_override, root=root)
    if not health.get("configured"):
        return {
            "ok": False,
            "backend_status": str(health.get("status") or "blocked_shadowbroker_not_configured"),
            "degraded_reason": health.get("degraded_reason", ""),
            "health": health,
            "normalized_events": [],
        }
    if not health.get("healthy"):
        return {
            "ok": False,
            "backend_status": "degraded_shadowbroker_unreachable",
            "degraded_reason": health.get("degraded_reason", ""),
            "health": health,
            "normalized_events": [],
        }
    runtime = _runtime_config(metadata_override=metadata_override)
    started = time.monotonic()
    headers = {"User-Agent": "jarvis-shadowbroker/1.0"}
    if runtime["api_key"]:
        headers["Authorization"] = f"Bearer {runtime['api_key']}"
    try:
        with _urlopen(
            runtime["base_url"].rstrip("/") + "/snapshot",
            headers=headers,
            timeout_seconds=float(runtime["timeout_seconds"]),
            verify_ssl=bool(runtime["verify_ssl"]),
        ) as response:
            body = response.read().decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", 200))
        if status_code >= 400:
            persisted = _persist_backend_health(
                status="degraded_shadowbroker_unreachable",
                configured=True,
                healthy=False,
                base_url=runtime["base_url"],
                degraded_reason=f"http_status={status_code}",
                timeout_seconds=float(runtime["timeout_seconds"]),
                latency_ms=int((time.monotonic() - started) * 1000),
                root=root,
            )
            return {
                "ok": False,
                "backend_status": "degraded_shadowbroker_unreachable",
                "degraded_reason": f"http_status={status_code}",
                "health": persisted,
                "normalized_events": [],
            }
        payload = json.loads(body or "{}")
    except json.JSONDecodeError as exc:
        persisted = _persist_backend_health(
            status="degraded_shadowbroker_bad_payload",
            configured=True,
            healthy=False,
            base_url=runtime["base_url"],
            degraded_reason=f"{type(exc).__name__}: {exc}",
            timeout_seconds=float(runtime["timeout_seconds"]),
            latency_ms=int((time.monotonic() - started) * 1000),
            root=root,
        )
        return {
            "ok": False,
            "backend_status": "degraded_shadowbroker_bad_payload",
            "degraded_reason": f"{type(exc).__name__}: {exc}",
            "health": persisted,
            "normalized_events": [],
        }
    except Exception as exc:
        persisted = _persist_backend_health(
            status="degraded_shadowbroker_unreachable",
            configured=True,
            healthy=False,
            base_url=runtime["base_url"],
            degraded_reason=f"{type(exc).__name__}: {exc}",
            timeout_seconds=float(runtime["timeout_seconds"]),
            latency_ms=int((time.monotonic() - started) * 1000),
            root=root,
        )
        return {
            "ok": False,
            "backend_status": "degraded_shadowbroker_unreachable",
            "degraded_reason": f"{type(exc).__name__}: {exc}",
            "health": persisted,
            "normalized_events": [],
        }

    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        persisted = _persist_backend_health(
            status="degraded_shadowbroker_bad_payload",
            configured=True,
            healthy=False,
            base_url=runtime["base_url"],
            degraded_reason="ShadowBroker payload must be an object with an events list.",
            timeout_seconds=float(runtime["timeout_seconds"]),
            latency_ms=int((time.monotonic() - started) * 1000),
            root=root,
        )
        return {
            "ok": False,
            "backend_status": "degraded_shadowbroker_bad_payload",
            "degraded_reason": "ShadowBroker payload must be an object with an events list.",
            "health": persisted,
            "normalized_events": [],
        }
    normalized_events = normalize_shadowbroker_events(payload, feed_id=feed_id)
    snapshot = persist_shadowbroker_snapshot(
        actor=actor,
        lane=lane,
        feed_id=feed_id,
        snapshot_payload=payload,
        normalized_events=normalized_events,
        root=root,
    )
    fetch_latency_ms = int((time.monotonic() - started) * 1000)
    snapshot["fetch_latency_ms"] = fetch_latency_ms
    _write_json(shadowbroker_snapshots_dir(root), snapshot["snapshot_id"], snapshot)
    persisted_health = _persist_backend_health(
        status="healthy",
        configured=True,
        healthy=True,
        base_url=runtime["base_url"],
        degraded_reason="",
        timeout_seconds=float(runtime["timeout_seconds"]),
        latency_ms=fetch_latency_ms,
        root=root,
    )
    return {
        "ok": True,
        "backend_status": "healthy",
        "degraded_reason": "",
        "health": persisted_health,
        "snapshot": snapshot,
        "normalized_events": normalized_events,
        "fetch_latency_ms": fetch_latency_ms,
    }


def summarize_shadowbroker_anomalies(*, root: Optional[Path] = None) -> dict[str, Any]:
    event_rows = _list_json(shadowbroker_events_dir(root))
    anomalies = [
        row
        for row in event_rows
        if str(row.get("risk_posture") or "").lower() in {"high", "critical"}
    ]
    return {
        "anomaly_count": len(anomalies[:25]),
        "latest_anomaly": anomalies[0] if anomalies else None,
        "anomalies": anomalies[:10],
    }


def build_shadowbroker_watchlist(*, root: Optional[Path] = None) -> dict[str, Any]:
    event_rows = _list_json(shadowbroker_events_dir(root))
    watchlist: list[dict[str, Any]] = []
    for row in event_rows[:25]:
        watchlist.append(
            {
                "event_id": row.get("event_id"),
                "title": row.get("title"),
                "region": row.get("region"),
                "event_type": row.get("event_type"),
                "risk_posture": row.get("risk_posture"),
                "evidence_linked": bool(row.get("evidence_bundle_ref")),
                "external_ref": row.get("external_ref"),
            }
        )
    return {
        "watchlist_count": len(watchlist),
        "watchlist_items": watchlist[:10],
    }


def build_shadowbroker_brief(*, root: Optional[Path] = None) -> dict[str, Any]:
    summary = summarize_shadowbroker_backend(root=root)
    anomalies = summarize_shadowbroker_anomalies(root=root)
    watchlist = build_shadowbroker_watchlist(root=root)
    timestamp = now_iso()
    title = "ShadowBroker Operator Brief"
    lines = [
        f"# {title}",
        "",
        f"- generated_at: {timestamp}",
        f"- configured: {summary.get('configured')}",
        f"- healthy: {summary.get('healthy')}",
        f"- backend_status: {summary.get('backend_status')}",
        f"- recent_event_count: {summary.get('recent_event_count', 0)}",
        f"- evidence_linked_event_count: {summary.get('evidence_linked_event_count', 0)}",
        "",
        "## Event Types",
    ]
    for key, value in (summary.get("event_type_counts") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Regions")
    for key, value in (summary.get("region_counts") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Watchlist")
    for row in watchlist.get("watchlist_items", []):
        lines.append(
            f"- {row.get('title')}: type={row.get('event_type')} region={row.get('region')} risk={row.get('risk_posture')} evidence={row.get('evidence_linked')}"
        )
    lines.append("")
    lines.append("## Anomalies")
    for row in anomalies.get("anomalies", []):
        lines.append(
            f"- {row.get('title')}: type={row.get('event_type')} region={row.get('region')} risk={row.get('risk_posture')}"
        )
    brief_id = f"shadowbrief_{timestamp.replace(':', '').replace('-', '')}"
    markdown_path = shadowbroker_briefs_dir(root) / f"{brief_id}.md"
    json_path = shadowbroker_briefs_dir(root) / f"{brief_id}.json"
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = {
        "brief_id": brief_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "title": title,
        "status": "available" if summary.get("configured") else "blocked",
        "markdown_path": str(markdown_path),
        "summary": (
            f"recent_events={summary.get('recent_event_count', 0)} "
            f"anomalies={anomalies.get('anomaly_count', 0)}"
        ),
        "backend_status": summary.get("backend_status"),
        "watchlist_count": watchlist.get("watchlist_count", 0),
        "anomaly_count": anomalies.get("anomaly_count", 0),
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def export_shadowbroker_operator_brief(*, root: Optional[Path] = None) -> dict[str, Any]:
    return build_shadowbroker_brief(root=root)


def summarize_shadowbroker_backend(*, root: Optional[Path] = None) -> dict[str, Any]:
    health_rows = _list_json(shadowbroker_backend_health_dir(root))
    snapshot_rows = _list_json(shadowbroker_snapshots_dir(root))
    event_rows = _list_json(shadowbroker_events_dir(root))
    latest_brief = _latest_json(shadowbroker_briefs_dir(root))
    latest_health = health_rows[0] if health_rows else validate_shadowbroker_runtime()
    latest_snapshot = snapshot_rows[0] if snapshot_rows else None
    event_type_counts: dict[str, int] = {}
    region_counts: dict[str, int] = {}
    evidence_linked_event_count = 0
    for row in event_rows[:100]:
        event_type = str(row.get("event_type") or "uncategorized")
        region = str(row.get("region") or "global")
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
        region_counts[region] = region_counts.get(region, 0) + 1
        if row.get("evidence_bundle_ref"):
            evidence_linked_event_count += 1
    evidence_bundle_count = build_evidence_bundle_summary(root=root).get("evidence_kind_counts", {}).get("shadowbroker", 0)
    configured = bool(latest_health.get("configured")) if isinstance(latest_health, dict) else False
    healthy = bool(latest_health.get("healthy")) if isinstance(latest_health, dict) else False
    backend_status = str(latest_health.get("status") or "blocked_shadowbroker_not_configured")
    latest_snapshot_timestamp = (latest_snapshot or {}).get("updated_at") or (latest_snapshot or {}).get("created_at")
    latest_snapshot_age_seconds = _age_seconds(latest_snapshot_timestamp)
    latency_summary = {
        "latest_latency_ms": (latest_health or {}).get("latency_ms"),
        "timeout_seconds": (latest_health or {}).get("timeout_seconds"),
        "last_fetch_latency_ms": (latest_snapshot or {}).get("fetch_latency_ms"),
    }
    return {
        "summary_kind": "shadowbroker_sidecar",
        "authoritative_runtime": "external_shadowbroker",
        "mirrored_only": True,
        "configured": configured,
        "healthy": healthy,
        "backend_status": backend_status,
        "latest_snapshot_timestamp": latest_snapshot_timestamp,
        "latest_snapshot_age_seconds": latest_snapshot_age_seconds,
        "recent_event_count": len(event_rows[:25]),
        "event_type_counts": event_type_counts,
        "region_counts": region_counts,
        "degraded_reason": str((latest_health or {}).get("degraded_reason") or ""),
        "evidence_bundle_count": evidence_bundle_count,
        "evidence_linked_event_count": evidence_linked_event_count,
        "backend_latency_summary": latency_summary,
        "latest_snapshot": latest_snapshot,
        "latest_brief": latest_brief,
        "watchlist": build_shadowbroker_watchlist(root=root),
        "anomalies": summarize_shadowbroker_anomalies(root=root),
        "latest_backend_health": latest_health,
    }
