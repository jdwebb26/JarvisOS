import json
from pathlib import Path
from unittest.mock import patch

from scripts.operator_discord_runtime_check import (
    build_operator_discord_runtime_check,
    render_operator_discord_runtime_check,
)
from scripts.preflight_lib import write_report


def test_operator_discord_runtime_check_reports_blocked_runtime_truth(tmp_path: Path) -> None:
    status = {
        "generated_at": "2026-03-12T20:00:00Z",
        "discord_live_ops_summary": {
            "latest_discord_task": None,
            "latest_discord_routing_refusal": {
                "failure_code": "routing_refused",
                "failure_reason": "No legal candidate survived policy filtering.",
            },
            "live_lane_diagnostic": {
                "route_selected": False,
                "backend_execution_attempted": False,
                "failure_category": "routing_refused",
                "failure_reason": "No legal candidate survived policy filtering.",
                "next_inspect": "Inspect routing_summary.latest_failed_routing_request.",
            },
        },
        "openclaw_discord_bridge_summary": {
            "latest_attempt": {
                "selected_provider_id": "lmstudio",
                "selected_model_name": "qwen/qwen3.5-9b",
            },
            "latest_failure": {
                "failure_class": "backend_timeout",
                "failure_reason": "request timed out",
            },
        },
        "openclaw_discord_session_summary": {
            "malformed_session_count": 1,
            "latest_malformed_session": {
                "session_id": "sess1",
                "operator_action_required": "Run `python3 scripts/repair_discord_sessions.py --repair-all-malformed --repair`.",
            },
        },
        "routing_control_plane_summary": {
            "latest_selected_route": None,
            "latest_route_state": "blocked",
            "latest_route_legality": "blocked",
        },
    }
    with patch("scripts.operator_discord_runtime_check.build_status", return_value=status):
        report = build_operator_discord_runtime_check(root=tmp_path)

    assert report["discord_ready"] is False
    assert report["active_provider_id"] == "lmstudio"
    assert report["active_model"] == "qwen/qwen3.5-9b"
    assert report["last_failure_category"] == "routing_refused"
    assert report["session_looks_healthy"] is False
    assert any("repair_discord_sessions.py" in action for action in report["operator_action_required"])
    rendered = render_operator_discord_runtime_check(report)
    assert "BLOCKED" in rendered
    assert "provider=lmstudio" in rendered
    assert "failure_category=routing_refused" in rendered


def test_operator_discord_runtime_check_reports_healthy_nimo_route_and_writes_record(tmp_path: Path) -> None:
    status = {
        "generated_at": "2026-03-12T20:05:00Z",
        "discord_live_ops_summary": {
            "latest_discord_task": {
                "provider_id": "qwen",
                "selected_model_name": "Qwen3.5-9B",
                "execution_backend": "qwen_executor",
                "selected_host_name": "NIMO",
            },
            "latest_discord_routing_refusal": None,
            "live_lane_diagnostic": {
                "route_selected": True,
                "backend_execution_attempted": True,
                "selected_provider_id": "qwen",
                "selected_model_name": "Qwen3.5-9B",
                "selected_backend": "qwen_executor",
                "selected_host_name": "NIMO",
                "failure_category": "",
                "failure_reason": "",
                "timeout_stage": "",
                "degraded_fallback_attempted": False,
                "degraded_fallback_blocked": False,
            },
        },
        "openclaw_discord_bridge_summary": {
            "latest_attempt": {
                "selected_provider_id": "qwen",
                "selected_model_name": "Qwen3.5-9B",
            },
            "latest_failure": None,
            "latest_successful_reply": {"source_message_id": "msg1"},
        },
        "openclaw_discord_session_summary": {
            "malformed_session_count": 0,
            "latest_malformed_session": None,
        },
        "routing_control_plane_summary": {
            "latest_selected_route": {
                "provider_id": "qwen",
                "model_name": "Qwen3.5-9B",
                "execution_backend": "qwen_executor",
                "host_name": "NIMO",
            },
            "latest_route_state": "selected",
            "latest_route_legality": "legal",
        },
    }
    with patch("scripts.operator_discord_runtime_check.build_status", return_value=status):
        report = build_operator_discord_runtime_check(root=tmp_path)
        write_report(tmp_path, "operator_discord_runtime_check.json", report)

    stored = json.loads((tmp_path / "state" / "logs" / "operator_discord_runtime_check.json").read_text(encoding="utf-8"))
    assert report["discord_ready"] is True
    assert report["active_provider_id"] == "qwen"
    assert report["active_model"] == "Qwen3.5-9B"
    assert report["active_backend_runtime"] == "qwen_executor"
    assert report["active_host_name"] == "NIMO"
    assert report["active_host_classification"] == "NIMO"
    assert stored["discord_ready"] is True
