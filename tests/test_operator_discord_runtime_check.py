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
        "shadowbroker_summary": {
            "configured": True,
            "healthy": False,
            "backend_status": "degraded_shadowbroker_unreachable",
            "degraded_reason": "ConnectionRefusedError: refused",
        },
        "extension_lane_status_summary": {
            "rows": [
                {
                    "lane": "shadowbroker",
                    "classification": "implemented_but_blocked_by_external_runtime",
                    "reason": "ConnectionRefusedError: refused",
                }
            ]
        },
    }
    with (
        patch("scripts.operator_discord_runtime_check.build_status", return_value=status),
        patch(
            "scripts.operator_discord_runtime_check._load_openclaw_agent_model_contract",
            return_value={
                "primary": "lmstudio/qwen/qwen3.5-9b",
                "fallbacks": [],
                "configured_fail_closed": True,
            },
        ),
        patch("scripts.operator_discord_runtime_check._count_agent_auth_profiles", return_value=1),
    ):
        report = build_operator_discord_runtime_check(root=tmp_path)

    assert report["discord_ready"] is False
    assert report["active_provider_id"] == "lmstudio"
    assert report["active_model"] == "qwen/qwen3.5-9b"
    assert report["configured_fail_closed"] is True
    assert report["real_alternate_configured_path_present"] is False
    assert "generic internal retry/failover text" in report["retry_truth"]["interpretation"]
    assert report["last_failure_category"] == "routing_refused"
    assert report["session_looks_healthy"] is False
    assert any("repair_discord_sessions.py" in action for action in report["operator_action_required"])
    rendered = render_operator_discord_runtime_check(report)
    assert "BLOCKED" in rendered
    assert "provider=lmstudio" in rendered
    assert "real_alternate_path=False" in rendered
    assert "retry_truth:" in rendered
    assert "failure_category=routing_refused" in rendered


def test_operator_discord_runtime_check_suggests_truthful_shadowbroker_reply(tmp_path: Path) -> None:
    status = {
        "generated_at": "2026-03-12T20:03:00Z",
        "discord_live_ops_summary": {
            "latest_discord_task": {
                "provider_id": "lmstudio",
                "selected_model_name": "qwen/qwen3.5-9b",
                "execution_backend": "nimo",
                "selected_host_name": "NIMO",
            },
            "latest_discord_routing_refusal": None,
            "live_lane_diagnostic": {
                "route_selected": True,
                "backend_execution_attempted": True,
                "selected_provider_id": "lmstudio",
                "selected_model_name": "qwen/qwen3.5-9b",
                "selected_backend": "nimo",
                "selected_host_name": "NIMO",
                "failure_category": "backend_timeout",
                "failure_reason": "secondary internal step timed out",
            },
        },
        "openclaw_discord_bridge_summary": {
            "latest_attempt": {
                "selected_provider_id": "lmstudio",
                "selected_model_name": "qwen/qwen3.5-9b",
            },
            "latest_failure": {
                "failure_class": "backend_timeout",
                "failure_reason": "secondary internal step timed out",
            },
        },
        "openclaw_discord_session_summary": {
            "malformed_session_count": 0,
            "latest_malformed_session": None,
            "recent_discord_sessions": [
                {
                    "last_user_query": "do we have access to shadowbroker yet",
                    "latest_assistant_reply_raw": "</context>\n[MISSING] Expected at: /tmp/USER.md\nShadowBroker is not installed.",
                    "latest_user_facing_reply": "ShadowBroker is not installed.",
                    "latest_assistant_reply_contaminated": True,
                    "latest_assistant_reply_findings": ["</context>"],
                }
            ],
        },
        "routing_control_plane_summary": {
            "latest_selected_route": {
                "provider_id": "lmstudio",
                "model_name": "qwen/qwen3.5-9b",
                "execution_backend": "nimo",
                "host_name": "NIMO",
            },
            "latest_route_state": "selected",
            "latest_route_legality": "legal",
        },
        "shadowbroker_summary": {
            "configured": True,
            "healthy": False,
            "backend_status": "degraded_shadowbroker_unreachable",
            "degraded_reason": "ConnectionRefusedError: refused",
        },
        "extension_lane_status_summary": {
            "rows": [
                {
                    "lane": "shadowbroker",
                    "classification": "implemented_but_blocked_by_external_runtime",
                    "reason": "ConnectionRefusedError: refused",
                }
            ]
        },
    }
    with (
        patch("scripts.operator_discord_runtime_check.build_status", return_value=status),
        patch(
            "scripts.operator_discord_runtime_check._load_openclaw_agent_model_contract",
            return_value={
                "primary": "lmstudio/qwen/qwen3.5-9b",
                "fallbacks": [],
                "configured_fail_closed": True,
            },
        ),
        patch("scripts.operator_discord_runtime_check._count_agent_auth_profiles", return_value=1),
        patch(
            "scripts.operator_discord_runtime_check._load_openclaw_provider_runtime",
            return_value={
                "provider_id": "lmstudio",
                "base_url": "http://100.70.114.34:1234/v1",
                "api": "openai",
                "host_classification": "NIMO",
                "host_name": "NIMO",
            },
        ),
    ):
        report = build_operator_discord_runtime_check(root=tmp_path)

    assert report["latest_assistant_reply_contaminated"] is True
    assert "</context>" not in report["latest_user_facing_reply"]
    assert "not installed" not in report["suggested_clean_reply"].lower()
    assert "integration exists in the repo" in report["suggested_clean_reply"]
    assert "blocked, degraded, or unproven" in report["suggested_clean_reply"]


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
        "shadowbroker_summary": {
            "configured": True,
            "healthy": True,
            "backend_status": "healthy",
            "degraded_reason": "",
        },
        "extension_lane_status_summary": {
            "rows": [
                {
                    "lane": "shadowbroker",
                    "classification": "live_and_usable",
                    "reason": "ShadowBroker is configured and healthy.",
                }
            ]
        },
    }
    with (
        patch("scripts.operator_discord_runtime_check.build_status", return_value=status),
        patch(
            "scripts.operator_discord_runtime_check._load_openclaw_agent_model_contract",
            return_value={
                "primary": "qwen/Qwen3.5-9B",
                "fallbacks": [],
                "configured_fail_closed": True,
            },
        ),
        patch("scripts.operator_discord_runtime_check._count_agent_auth_profiles", return_value=1),
    ):
        report = build_operator_discord_runtime_check(root=tmp_path)
        write_report(tmp_path, "operator_discord_runtime_check.json", report)

    stored = json.loads((tmp_path / "state" / "logs" / "operator_discord_runtime_check.json").read_text(encoding="utf-8"))
    assert report["discord_ready"] is True
    assert report["active_provider_id"] == "qwen"
    assert report["active_model"] == "Qwen3.5-9B"
    assert report["active_backend_runtime"] == "qwen_executor"
    assert report["active_host_name"] == "NIMO"
    assert report["active_host_classification"] == "NIMO"
    assert report["configured_fail_closed"] is True
    assert report["real_alternate_configured_path_present"] is False
    assert stored["discord_ready"] is True


def test_operator_discord_runtime_check_suggests_runtime_truth_for_model_question(tmp_path: Path) -> None:
    status = {
        "generated_at": "2026-03-12T20:05:00Z",
        "discord_live_ops_summary": {
            "latest_discord_task": {
                "provider_id": "lmstudio",
                "selected_model_name": "qwen/qwen3.5-9b",
                "execution_backend": "nimo",
                "selected_host_name": "NIMO",
            },
            "latest_discord_routing_refusal": None,
            "live_lane_diagnostic": {
                "route_selected": True,
                "backend_execution_attempted": True,
                "selected_provider_id": "lmstudio",
                "selected_model_name": "qwen/qwen3.5-9b",
                "selected_backend": "nimo",
                "selected_host_name": "NIMO",
                "failure_category": "",
                "failure_reason": "",
            },
        },
        "openclaw_discord_bridge_summary": {
            "latest_attempt": {
                "selected_provider_id": "lmstudio",
                "selected_model_name": "qwen/qwen3.5-9b",
            },
            "latest_failure": None,
        },
        "openclaw_discord_session_summary": {
            "malformed_session_count": 0,
            "latest_malformed_session": None,
            "recent_discord_sessions": [
                {
                    "last_user_query": "whats your model",
                    "latest_assistant_reply_raw": "<system_status>\nMy model is unknown.",
                }
            ],
        },
        "routing_control_plane_summary": {
            "latest_selected_route": {
                "provider_id": "lmstudio",
                "model_name": "qwen/qwen3.5-9b",
                "execution_backend": "nimo",
                "host_name": "NIMO",
            },
            "latest_route_state": "selected",
            "latest_route_legality": "legal",
        },
        "shadowbroker_summary": {},
        "extension_lane_status_summary": {"rows": []},
    }
    with (
        patch("scripts.operator_discord_runtime_check.build_status", return_value=status),
        patch(
            "scripts.operator_discord_runtime_check._load_openclaw_agent_model_contract",
            return_value={
                "primary": "lmstudio/qwen/qwen3.5-9b",
                "fallbacks": [],
                "configured_fail_closed": True,
            },
        ),
        patch("scripts.operator_discord_runtime_check._count_agent_auth_profiles", return_value=1),
        patch(
            "scripts.operator_discord_runtime_check._load_openclaw_provider_runtime",
            return_value={
                "provider_id": "lmstudio",
                "base_url": "http://100.70.114.34:1234/v1",
                "api": "openai",
                "host_classification": "NIMO",
                "host_name": "NIMO",
            },
        ),
    ):
        report = build_operator_discord_runtime_check(root=tmp_path)

    assert report["suggested_clean_reply"].startswith("Current Jarvis Discord runtime is")
    assert "lmstudio/qwen/qwen3.5-9b" in report["suggested_clean_reply"]
    assert "NIMO" in report["suggested_clean_reply"]
    assert "http://100.70.114.34:1234/v1" in report["suggested_clean_reply"]


def test_operator_discord_runtime_check_accepts_true_front_door_session_evidence_when_transient_logs_are_missing(tmp_path: Path) -> None:
    status = {
        "generated_at": "2026-03-14T06:10:00Z",
        "discord_live_ops_summary": {
            "latest_discord_task": None,
            "latest_discord_routing_refusal": None,
            "live_lane_diagnostic": {
                "route_selected": False,
                "backend_execution_attempted": False,
                "selected_provider_id": None,
                "selected_model_name": None,
                "selected_backend": None,
                "selected_host_name": None,
                "failure_category": "",
                "failure_reason": "",
            },
        },
        "openclaw_discord_bridge_summary": {
            "latest_attempt": None,
            "latest_failure": None,
            "latest_successful_reply": None,
        },
        "openclaw_discord_session_summary": {
            "malformed_session_count": 0,
            "latest_malformed_session": None,
            "recent_discord_sessions": [
                {
                    "session_key": "agent:jarvis:discord:channel:777",
                    "selected_provider_id": "lmstudio",
                    "selected_model_name": "qwen3.5-35b-a3b",
                    "last_user_query": "Conversation info (untrusted metadata): ... reply with only: pong",
                    "latest_assistant_reply_raw": "pong",
                    "latest_user_facing_reply": "pong",
                    "front_door_discord_ingress_detected": True,
                    "front_door_assistant_reply_detected": True,
                    "gateway_execution_evidence_detected": True,
                    "has_source_owned_system_prompt_report": True,
                    "tool_exposure_mode": "none",
                    "tool_exposure_reason": "no_tools",
                    "latest_prompt_budget": {
                        "estimated_total_tokens": 6032,
                        "safe_threshold_tokens": 144000,
                        "hard_threshold_tokens": 164000,
                        "over_safe_threshold": False,
                        "over_hard_threshold": False,
                        "raw_user_turn_window": 6,
                        "user_turns_in_session": 3,
                        "metadata_wrapper_tokens": 1,
                        "raw_tool_output_tokens": 2,
                        "retrieved_memory_tokens": 0,
                        "rolling_session_summary_tokens": 427,
                        "preflight_compaction": {"requested": False, "reason": "none", "compacted": False},
                    },
                    "rolling_summary_stats": {"summary_id": "", "chars": 1707, "refreshed_at": "2026-03-14T06:06:58Z"},
                    "retrieval_stats": {"episodic_count": 0, "semantic_count": 0, "used_tokens": 0, "remaining_budget_tokens": 1200},
                }
            ],
        },
        "routing_control_plane_summary": {
            "latest_selected_route": None,
            "latest_route_state": "unknown",
            "latest_route_legality": "unknown",
        },
        "shadowbroker_summary": {},
        "extension_lane_status_summary": {"rows": []},
    }
    with (
        patch("scripts.operator_discord_runtime_check.build_status", return_value=status),
        patch(
            "scripts.operator_discord_runtime_check._load_openclaw_agent_model_contract",
            return_value={
                "primary": "lmstudio/qwen/qwen3.5-9b",
                "fallbacks": [],
                "configured_fail_closed": True,
            },
        ),
        patch("scripts.operator_discord_runtime_check._count_agent_auth_profiles", return_value=2),
        patch(
            "scripts.operator_discord_runtime_check._load_openclaw_provider_runtime",
            return_value={
                "provider_id": "lmstudio",
                "base_url": "http://100.70.114.34:1234/v1",
                "api": "openai-completions",
                "host_classification": "NIMO",
                "host_name": "NIMO",
            },
        ),
    ):
        report = build_operator_discord_runtime_check(root=tmp_path)

    readiness = {row["name"]: row for row in report["readiness_criteria"]}
    assert readiness["live_execution_evidence_present"]["ok"] is True
    assert readiness["live_execution_evidence_present"]["details"]["route_selected"] is True
    assert readiness["live_execution_evidence_present"]["details"]["backend_execution_attempted"] is True
    assert readiness["live_execution_evidence_present"]["details"]["bridge_attempt_present"] is True
    assert report["route_selected"] is True
    assert report["backend_execution_attempted"] is True
    assert "No fresh Discord route/execution evidence is present." not in report["blocking_reasons"]
