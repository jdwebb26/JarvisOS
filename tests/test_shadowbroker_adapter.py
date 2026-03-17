from pathlib import Path
from unittest.mock import patch

from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.integrations.shadowbroker_adapter import (
    build_shadowbroker_brief,
    export_shadowbroker_operator_brief,
    fetch_shadowbroker_snapshot,
    summarize_shadowbroker_backend,
    summarize_shadowbroker_anomalies,
    validate_shadowbroker_runtime,
    build_shadowbroker_watchlist,
)
from scripts.operator_handoff_pack import build_operator_handoff_pack
from scripts.preflight_lib import build_doctor_report, render_doctor_report
from runtime.world_ops.store import list_world_events, register_world_feed


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


def test_shadowbroker_blocked_when_not_configured(tmp_path: Path):
    runtime = validate_shadowbroker_runtime()
    result = fetch_shadowbroker_snapshot(feed_id="shadowbroker_main", root=tmp_path)
    assert runtime["status"] == "blocked_shadowbroker_not_configured"
    assert result["ok"] is False
    assert result["backend_status"] == "blocked_shadowbroker_not_configured"


def test_shadowbroker_degraded_when_endpoint_unhealthy(tmp_path: Path):
    with patch(
        "runtime.integrations.shadowbroker_adapter._urlopen",
        side_effect=ConnectionRefusedError("connection refused"),
    ):
        result = fetch_shadowbroker_snapshot(
            feed_id="shadowbroker_main",
            metadata_override={"base_url": "https://shadowbroker.invalid", "verify_ssl": True},
            root=tmp_path,
        )
    assert result["ok"] is False
    assert result["backend_status"] == "degraded_shadowbroker_unreachable"


def test_shadowbroker_successful_normalized_snapshot_and_operator_visibility(tmp_path: Path):
    register_world_feed(
        feed_id="shadowbroker_main",
        label="ShadowBroker",
        purpose="osint",
        ingestion_kind="shadowbroker",
        backend_ref="shadowbroker",
        configured_url="https://shadowbroker.invalid",
        root=tmp_path,
    )

    def _fake_urlopen(url: str, *, headers: dict[str, str], timeout_seconds: float, verify_ssl: bool):
        if url.endswith("/healthz"):
            return _FakeResponse("{}", status=200)
        return _FakeResponse(
            """{
  "snapshot_id": "sb_snap_1",
  "events": [
    {
      "event_id": "sb_evt_1",
      "title": "Port disruption",
      "summary": "Shipping disruption detected.",
      "region": "global",
      "event_type": "supply_chain",
      "risk_posture": "medium",
      "url": "https://shadowbroker.invalid/e/1"
    }
  ]
}""",
            status=200,
        )

    with patch("runtime.integrations.shadowbroker_adapter._urlopen", side_effect=_fake_urlopen):
        result = fetch_shadowbroker_snapshot(
            feed_id="shadowbroker_main",
            metadata_override={"base_url": "https://shadowbroker.invalid", "api_key": "test-token"},
            root=tmp_path,
        )

    assert result["ok"] is True
    summary = summarize_shadowbroker_backend(root=tmp_path)
    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    assert summary["healthy"] is True
    assert summary["backend_status"] == "healthy"
    assert summary["recent_event_count"] == 1
    assert summary["evidence_bundle_count"] >= 1
    assert list_world_events(root=tmp_path)
    assert status["shadowbroker_summary"]["backend_status"] == "healthy"
    assert snapshot["shadowbroker_summary"]["recent_event_count"] == 1
    assert export_payload["shadowbroker_summary"]["evidence_bundle_count"] >= 1

    brief = build_shadowbroker_brief(root=tmp_path)
    exported = export_shadowbroker_operator_brief(root=tmp_path)
    watchlist = build_shadowbroker_watchlist(root=tmp_path)
    anomalies = summarize_shadowbroker_anomalies(root=tmp_path)
    doctor_report = build_doctor_report(root=tmp_path)
    doctor_text = render_doctor_report(doctor_report)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]

    assert brief["brief_id"]
    assert brief["markdown_path"]
    assert exported["brief_id"] != ""
    assert watchlist["watchlist_count"] == 1
    assert anomalies["anomaly_count"] == 0
    assert doctor_report["shadowbroker_summary"]["healthy"] is True
    assert "shadowbroker:" in doctor_text
    assert handoff["shadowbroker_summary"]["recent_event_count"] == 1
    assert handoff["shadowbroker_summary"]["latest_brief"]["brief_id"]


def test_shadowbroker_degraded_state_surfaces_in_doctor_snapshot_export(tmp_path: Path):
    doctor_report = build_doctor_report(root=tmp_path)
    doctor_text = render_doctor_report(doctor_report)
    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]

    assert status["shadowbroker_summary"]["configured"] is False
    assert snapshot["shadowbroker_summary"]["backend_status"] == "blocked_shadowbroker_not_configured"
    assert export_payload["shadowbroker_summary"]["healthy"] is False
    assert handoff["shadowbroker_summary"]["backend_status"] == "blocked_shadowbroker_not_configured"
    assert doctor_report["shadowbroker_summary"]["backend_status"] == "blocked_shadowbroker_not_configured"
    assert "shadowbroker:" in doctor_text
