import json
from pathlib import Path
from unittest.mock import patch

from runtime.integrations.lane_activation import record_lane_activation_attempt, record_lane_activation_result
from scripts.operator_go_live_gate import build_operator_go_live_gate, render_operator_go_live_gate
from scripts.preflight_lib import write_report


def _write_green_reports(root: Path) -> None:
    write_report(
        root,
        "validate_report.json",
        {
            "ok": True,
            "root": str(root),
            "summary": {"pass": 1, "warn": 0, "fail": 0},
            "findings": [],
        },
    )
    write_report(
        root,
        "smoke_test_report.json",
        {
            "ok": True,
            "root": str(root),
            "steps": [{"name": "validate", "ok": True, "message": "ok"}],
        },
    )


def test_operator_go_live_gate_reports_all_blocked_default_posture(tmp_path: Path) -> None:
    _write_green_reports(tmp_path)
    report = build_operator_go_live_gate(root=tmp_path)

    assert report["overall_ready"] is False
    assert report["live_lanes"] == []
    assert "No extension lane is currently live on this machine." in report["blocking_reasons"]
    assert len(report["categories"]["BLOCKED BY EXTERNAL RUNTIME"]) >= 1
    assert len(report["categories"]["SCAFFOLD ONLY"]) >= 1
    assert len(report["categories"]["DEPRECATED ALIAS"]) >= 1


def test_operator_go_live_gate_reports_mocked_ready_posture_and_writes_record(tmp_path: Path) -> None:
    _write_green_reports(tmp_path)
    for lane in ("adaptation_lab_unsloth", "optimizer_dspy"):
        attempt = record_lane_activation_attempt(lane=lane, command_or_endpoint=f"proof:{lane}", root=tmp_path)
        record_lane_activation_result(
            activation_run_id=attempt["activation_run_id"],
            lane=lane,
            status="completed",
            runtime_status="completed",
            configured=True,
            healthy=True,
            command_or_endpoint=f"proof:{lane}",
            root=tmp_path,
        )

    report = build_operator_go_live_gate(root=tmp_path)
    write_report(tmp_path, "operator_go_live_gate.json", report)
    stored = json.loads((tmp_path / "state" / "logs" / "operator_go_live_gate.json").read_text(encoding="utf-8"))

    assert report["overall_ready"] is True
    assert len(report["live_lanes"]) >= 2
    assert stored["overall_ready"] is True
    rendered = render_operator_go_live_gate(report)
    assert "READY NOW" in rendered
    assert "adaptation_lab_unsloth" in rendered
    assert "optimizer_dspy" in rendered


def test_operator_go_live_gate_render_is_honest_about_blocked_config(tmp_path: Path) -> None:
    _write_green_reports(tmp_path)
    attempt = record_lane_activation_attempt(lane="adaptation_lab_unsloth", command_or_endpoint="proof", root=tmp_path)
    record_lane_activation_result(
        activation_run_id=attempt["activation_run_id"],
        lane="adaptation_lab_unsloth",
        status="blocked",
        runtime_status="blocked_missing_unsloth_tiny_model",
        configured=False,
        healthy=False,
        command_or_endpoint="proof",
        operator_action_required="Set JARVIS_UNSLOTH_TINY_MODEL.",
        root=tmp_path,
    )
    report = build_operator_go_live_gate(root=tmp_path)
    rendered = render_operator_go_live_gate(report)
    assert "BLOCKED BY CONFIG" in rendered
    assert "adaptation_lab_unsloth" in rendered


def test_operator_go_live_gate_marks_configured_but_unhealthy_shadowbroker_as_external_runtime(tmp_path: Path) -> None:
    _write_green_reports(tmp_path)
    status = {
        "generated_at": "2026-03-12T00:00:00Z",
        "routing_control_plane_summary": {
            "primary_runtime_posture": "healthy",
            "latest_route_state": "selected",
            "latest_route_legality": "legal",
            "burst_capacity_posture": "optional_capacity_loss",
            "fallback_blocked_for_safety": False,
        },
        "extension_lane_status_summary": {
            "rows": [
                {
                    "lane": "shadowbroker",
                    "classification": "implemented_but_blocked_by_external_runtime",
                    "reason": "degraded_shadowbroker_bad_payload: JSONDecodeError",
                }
            ]
        },
        "lane_activation_summary": {
            "rows": [
                {
                    "lane": "shadowbroker",
                    "latest_activation_status": "not_run",
                    "latest_runtime_status": "not_run",
                    "error": "",
                    "details": "",
                }
            ]
        },
        "local_model_lane_proof_summary": {"rows": []},
        "workspace_registry_summary": {
            "default_home_workspace_id": "jarvis_v5_runtime",
            "workspace_count": 1,
            "operator_approved_workspace_count": 1,
        },
        "shadowbroker_summary": {
            "configured": True,
            "healthy": False,
            "backend_status": "degraded_shadowbroker_bad_payload",
        },
        "research_backend_summary": {"latest_backend_healthchecks": []},
        "hermes_summary": {},
        "autoresearch_summary": {},
        "adaptation_lab_summary": {},
        "optimizer_summary": {},
    }
    with patch("scripts.operator_go_live_gate.build_status", return_value=status):
        report = build_operator_go_live_gate(root=tmp_path)

    assert report["categories"]["BLOCKED BY EXTERNAL RUNTIME"][0]["lane"] == "shadowbroker"
    assert report["categories"]["BLOCKED BY CONFIG"] == []
