from pathlib import Path
from unittest.mock import patch

from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.integrations.lane_activation import (
    latest_lane_activation_result,
    list_lane_activation_results,
    record_lane_activation_attempt,
    record_lane_activation_result,
    summarize_lane_activation,
)
from scripts.operator_activate_external_lanes import activate_external_lanes
from scripts.preflight_lib import build_doctor_report


def test_lane_activation_result_persistence(tmp_path: Path):
    attempt = record_lane_activation_attempt(
        lane="shadowbroker",
        command_or_endpoint="https://shadowbroker.invalid",
        root=tmp_path,
    )
    result = record_lane_activation_result(
        activation_run_id=attempt["activation_run_id"],
        lane="shadowbroker",
        status="blocked",
        runtime_status="blocked_shadowbroker_not_configured",
        configured=False,
        healthy=False,
        command_or_endpoint="",
        operator_action_required="Configure ShadowBroker.",
        root=tmp_path,
    )
    latest = latest_lane_activation_result("shadowbroker", root=tmp_path)
    rows = list_lane_activation_results(root=tmp_path, lane="shadowbroker")

    assert result["activation_run_id"] == attempt["activation_run_id"]
    assert latest["runtime_status"] == "blocked_shadowbroker_not_configured"
    assert len(rows) == 1


def test_operator_activation_records_missing_config_honestly(tmp_path: Path):
    with patch("scripts.operator_activate_external_lanes.validate_shadowbroker_runtime", return_value={
        "configured": False,
        "status": "blocked_shadowbroker_not_configured",
        "reason": "missing",
        "base_url": "",
    }), patch("scripts.operator_activate_external_lanes.get_research_backend") as mock_backend, patch(
        "scripts.operator_activate_external_lanes.probe_hermes_runtime",
        return_value={"configured": False, "healthy": False, "runtime_status": "blocked_hermes_not_configured", "details": "missing", "command": []},
    ), patch(
        "scripts.operator_activate_external_lanes.probe_autoresearch_upstream_runtime",
        return_value={"configured": False, "healthy": False, "runtime_status": "blocked_upstream_not_configured", "details": "missing", "command": []},
    ):
        mock_backend.return_value.healthcheck.return_value = {
            "backend_id": "searxng",
            "status": "not_configured",
            "healthy": False,
            "configured_url": "",
            "details": "missing",
        }
        result = activate_external_lanes(root=tmp_path)

    summary = result["lane_activation_summary"]
    shadowbroker = next(row for row in summary["rows"] if row["lane"] == "shadowbroker")
    assert shadowbroker["latest_activation_status"] == "blocked"
    assert shadowbroker["latest_runtime_status"] == "blocked_shadowbroker_not_configured"
    assert shadowbroker["currently_live_on_this_machine"] is False


def test_operator_activation_records_mocked_healthy_results_and_visibility(tmp_path: Path):
    with patch("scripts.operator_activate_external_lanes.validate_shadowbroker_runtime", return_value={
        "configured": True,
        "status": "configured",
        "reason": "",
        "base_url": "https://shadowbroker.invalid",
    }), patch("scripts.operator_activate_external_lanes.fetch_shadowbroker_snapshot", return_value={
        "ok": True,
        "backend_status": "healthy",
        "snapshot": {
            "snapshot_id": "sb_snap_1",
            "evidence_bundle_ref": {"bundle_id": "bundle_1"},
        },
        "fetch_latency_ms": 42,
    }), patch("scripts.operator_activate_external_lanes.get_research_backend") as mock_backend, patch(
        "scripts.operator_activate_external_lanes.probe_hermes_runtime",
        return_value={
            "configured": True,
            "healthy": True,
            "runtime_status": "healthy",
            "details": "ok",
            "command": ["/usr/bin/hermes"],
            "request_path": "workspace/work/request.json",
            "result_path": "workspace/work/result.json",
        },
    ), patch(
        "scripts.operator_activate_external_lanes.probe_autoresearch_upstream_runtime",
        return_value={
            "configured": True,
            "healthy": True,
            "runtime_status": "healthy",
            "details": "ok",
            "command": ["/usr/bin/autoresearch"],
            "request_path": "workspace/work/request.json",
            "result_path": "workspace/work/result.json",
        },
    ):
        mock_backend.return_value.healthcheck.return_value = {
            "backend_id": "searxng",
            "status": "healthy",
            "healthy": True,
            "configured_url": "https://searx.invalid",
            "details": "ok",
        }
        activate_external_lanes(root=tmp_path)

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    doctor = build_doctor_report(tmp_path)

    lane_summary = status["lane_activation_summary"]
    assert lane_summary["live_lane_count"] == 4
    shadowbroker = next(row for row in lane_summary["rows"] if row["lane"] == "shadowbroker")
    assert shadowbroker["currently_live_on_this_machine"] is True
    assert shadowbroker["evidence_refs"]["snapshot_id"] == "sb_snap_1"
    assert snapshot["lane_activation_summary"]["live_lane_count"] == 4
    assert export_payload["lane_activation_summary"]["live_lane_count"] == 4
    assert doctor["lane_activation_summary"]["live_lane_count"] == 4


def test_summarize_lane_activation_can_merge_extension_labels(tmp_path: Path):
    attempt = record_lane_activation_attempt(
        lane="searxng",
        command_or_endpoint="https://searx.invalid",
        root=tmp_path,
    )
    record_lane_activation_result(
        activation_run_id=attempt["activation_run_id"],
        lane="searxng",
        status="degraded",
        runtime_status="unreachable",
        configured=True,
        healthy=False,
        command_or_endpoint="https://searx.invalid",
        operator_action_required="Inspect SearXNG.",
        root=tmp_path,
    )
    summary = summarize_lane_activation(
        root=tmp_path,
        extension_lane_status_summary={
            "rows": [
                {"lane": "searxng", "classification": "implemented_but_blocked_by_external_runtime"},
            ]
        },
    )
    searxng = next(row for row in summary["rows"] if row["lane"] == "searxng")
    assert searxng["classification"] == "implemented_but_blocked_by_external_runtime"
    assert searxng["latest_activation_status"] == "degraded"
