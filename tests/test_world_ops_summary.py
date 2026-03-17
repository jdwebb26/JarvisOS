from pathlib import Path
from unittest.mock import patch

from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.integrations.shadowbroker_adapter import summarize_shadowbroker_backend
from scripts.operator_handoff_pack import build_operator_handoff_pack
from scripts.preflight_lib import build_doctor_report
from runtime.world_ops.collector import collect_world_feed
from runtime.world_ops.normalizer import dedupe_world_events, normalize_world_event
from runtime.world_ops.store import list_world_events, list_world_feeds, register_world_feed
from runtime.world_ops.summary import build_world_ops_brief, build_world_status_snapshot


class _FakeResponse:
    def __init__(self, body: str, *, status: int = 200) -> None:
        self._body = body.encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_world_feed_registration_and_listing(tmp_path: Path):
    register_world_feed(
        feed_id="world_news",
        label="World News",
        purpose="osint_monitoring",
        ingestion_kind="rss",
        configured_url="https://example.invalid/feed",
        tags=["osint", "news"],
        regions=["global"],
        categories=["geopolitics"],
        root=tmp_path,
    )
    feeds = list_world_feeds(root=tmp_path)
    assert len(feeds) == 1
    assert feeds[0]["feed_id"] == "world_news"
    assert feeds[0]["status"] == "active"
    assert feeds[0]["ingestion_kind"] == "rss"
    assert feeds[0]["enabled"] is True


def test_world_event_normalization_and_dedupe(tmp_path: Path):
    raw = {
        "title": "Example Event",
        "summary": "A normalized example",
        "region": "north_america",
        "event_type": "supply_chain",
        "risk_posture": "medium",
        "url": "https://example.invalid/event",
        "source_records": [{"url": "https://example.invalid/event", "title": "Example Event"}],
    }
    first = normalize_world_event(raw, feed_id="world_news")
    second = normalize_world_event(raw, feed_id="world_news")
    rows = dedupe_world_events([first, second])
    assert len(rows) == 1


def test_rss_collection_snapshot_brief_and_operator_visibility(tmp_path: Path):
    register_world_feed(
        feed_id="world_news",
        label="World News",
        purpose="osint_monitoring",
        ingestion_kind="rss",
        configured_url="https://example.invalid/rss.xml",
        parser_ref="xml.etree.ElementTree",
        tags=["osint"],
        regions=["global"],
        categories=["geopolitics"],
        root=tmp_path,
    )
    rss_body = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>Port disruption</title>
      <link>https://example.invalid/port</link>
      <description>Regional shipping delays reported.</description>
      <category>supply_chain</category>
    </item>
    <item>
      <title>Grid instability</title>
      <link>https://example.invalid/grid</link>
      <description>Localized power issues detected.</description>
      <category>infrastructure</category>
    </item>
  </channel>
</rss>
"""
    with patch("urllib.request.urlopen", return_value=_FakeResponse(rss_body)):
        collected = collect_world_feed("world_news", root=tmp_path)
    assert collected["ok"] is True
    assert len(list_world_events(root=tmp_path)) == 2

    snapshot_record = build_world_status_snapshot(root=tmp_path)
    brief_record = build_world_ops_brief(root=tmp_path)
    status = build_status(tmp_path)
    operator_snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    doctor_report = build_doctor_report(root=tmp_path)

    assert snapshot_record["event_count"] == 2
    assert brief_record["brief_id"]
    assert status["world_ops_summary"]["active_feed_count"] == 1
    assert status["world_ops_summary"]["recent_event_count"] == 2
    assert status["world_ops_summary"]["recent_real_collected_event_count"] == 2
    assert status["world_ops_summary"]["latest_snapshot_timestamp"] == snapshot_record["updated_at"]
    assert status["world_ops_summary"]["latest_brief"]["brief_id"] == brief_record["brief_id"]
    assert status["world_ops_summary"]["feed_rows"][0]["ingestion_kind"] == "rss"
    assert status["world_ops_summary"]["feed_rows"][0]["last_collected_at"]
    assert status["world_ops_summary"]["event_types_summary"] == {"infrastructure": 1, "supply_chain": 1}
    assert operator_snapshot["world_ops_summary"]["active_feed_count"] == 1
    assert export_payload["world_ops_summary"]["recent_event_count"] == 2
    assert doctor_report["world_ops_summary"]["recent_event_count"] == 2
    assert list_world_events(root=tmp_path)[0]["evidence_bundle_ref"]


def test_world_ops_summary_marks_degraded_feeds_explicitly(tmp_path: Path):
    register_world_feed(
        feed_id="world_news",
        label="World News",
        purpose="osint_monitoring",
        root=tmp_path,
    )
    collect_world_feed("world_news", failure_reason="feed unreachable", root=tmp_path)
    status = build_status(tmp_path)
    assert status["world_ops_summary"]["degraded_feed_count"] == 1
    assert status["world_ops_summary"]["degraded_feeds"][0]["last_error"] == "feed unreachable"


def test_searxng_collection_handles_success_and_degraded_backend_states(tmp_path: Path):
    register_world_feed(
        feed_id="world_search",
        label="World Search",
        purpose="shipping disruption monitoring",
        ingestion_kind="searxng_search",
        configured_url="https://searx.invalid",
        backend_ref="searxng",
        categories=["osint_search_hit"],
        regions=["global"],
        metadata={"query_text": "shipping disruption", "max_results": 2},
        root=tmp_path,
    )
    with patch(
        "runtime.world_ops.collector.searxng_client.healthcheck",
        return_value={"backend_id": "searxng", "status": "healthy", "healthy": True, "details": "ok"},
    ), patch(
        "runtime.world_ops.collector.searxng_client.search",
        return_value={
            "query_id": "rq_test",
            "status": "ok",
            "results": [
                {
                    "url": "https://example.invalid/a",
                    "title": "Alert A",
                    "snippet": "first result",
                    "source": "example",
                },
                {
                    "url": "https://example.invalid/b",
                    "title": "Alert B",
                    "snippet": "second result",
                    "source": "example",
                },
            ],
        },
    ):
        result = collect_world_feed("world_search", root=tmp_path)
    assert result["ok"] is True
    assert len(list_world_events(root=tmp_path)) == 2
    status = build_status(tmp_path)
    assert status["world_ops_summary"]["feed_rows"][0]["backend_health"]["status"] == "healthy"

    with patch(
        "runtime.world_ops.collector.searxng_client.healthcheck",
        return_value={"backend_id": "searxng", "status": "unreachable", "healthy": False, "details": "connection refused"},
    ):
        degraded = collect_world_feed("world_search", root=tmp_path)
    assert degraded["ok"] is False
    status = build_status(tmp_path)
    operator_snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    assert status["world_ops_summary"]["degraded_feed_count"] == 1
    assert status["world_ops_summary"]["backend_health_counts"]["unreachable"] >= 1
    assert status["world_ops_summary"]["feed_rows"][0]["last_error"] == "connection refused"
    assert operator_snapshot["world_ops_summary"]["feed_rows"][0]["backend_health"]["status"] == "unreachable"
    assert export_payload["world_ops_summary"]["degraded_feed_count"] == 1


def test_world_ops_shadowbroker_compatibility_path_and_visibility(tmp_path: Path):
    register_world_feed(
        feed_id="shadowbroker_main",
        label="ShadowBroker",
        purpose="osint_monitoring",
        ingestion_kind="shadowbroker",
        configured_url="https://shadowbroker.invalid",
        backend_ref="shadowbroker",
        regions=["global"],
        categories=["threat_intel"],
        root=tmp_path,
    )

    def _fake_urlopen(url: str, *, headers: dict[str, str], timeout_seconds: float, verify_ssl: bool):
        if url.endswith("/healthz"):
            return _FakeResponse("{}", status=200)
        return _FakeResponse(
            """{
  "snapshot_id": "shadowbroker_snapshot_1",
  "events": [
    {
      "event_id": "shadow_event_1",
      "title": "Threat bulletin",
      "summary": "New regional risk bulletin.",
      "region": "europe",
      "event_type": "threat_intel",
      "risk_posture": "high",
      "url": "https://shadowbroker.invalid/e/1"
    }
  ]
}""",
            status=200,
        )

    with patch("runtime.integrations.shadowbroker_adapter._urlopen", side_effect=_fake_urlopen):
        result = collect_world_feed("shadowbroker_main", root=tmp_path)

    assert result["ok"] is True
    world_status = build_status(tmp_path)
    operator_snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    doctor_report = build_doctor_report(root=tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]
    shadowbroker_summary = summarize_shadowbroker_backend(root=tmp_path)

    assert world_status["world_ops_summary"]["ingestion_kind_counts"]["shadowbroker"] == 1
    assert world_status["shadowbroker_summary"]["backend_status"] == "healthy"
    assert world_status["shadowbroker_summary"]["recent_event_count"] == 1
    assert world_status["world_ops_summary"]["shadowbroker_watchlist"]["watchlist_count"] == 1
    assert operator_snapshot["shadowbroker_summary"]["event_type_counts"]["threat_intel"] == 1
    assert export_payload["shadowbroker_summary"]["region_counts"]["europe"] == 1
    assert doctor_report["shadowbroker_summary"]["healthy"] is True
    assert handoff["shadowbroker_summary"]["recent_event_count"] == 1
    assert shadowbroker_summary["evidence_bundle_count"] >= 1
