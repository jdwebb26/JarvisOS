#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.status import build_status
from runtime.integrations.openclaw_sessions import resolve_openclaw_root, sanitize_user_facing_assistant_reply
from scripts.preflight_lib import write_report


def _nonempty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        if value == "":
            continue
        return value
    return None


def _classify_runtime_host(host_name: str) -> str:
    normalized = str(host_name or "").strip().upper()
    if normalized == "NIMO":
        return "NIMO"
    if normalized in {"KOOLKID", "KOOLKIDCLUB"}:
        return "KOOLKID"
    if normalized in {"SNOWGLOBE_LOCAL", "SNOWGLOBE"}:
        return "SNOWGLOBE_LOCAL"
    if normalized == "LOCAL":
        return "LOCAL"
    return "unknown"


def _classify_runtime_host_from_url(base_url: str) -> str:
    parsed = urlparse(str(base_url or "").strip())
    host = (parsed.hostname or "").strip().lower()
    if host == "100.70.114.34":
        return "NIMO"
    if host == "100.84.23.108":
        return "KOOLKID"
    if host in {"127.0.0.1", "localhost", "::1"}:
        return "SNOWGLOBE_LOCAL"
    return "unknown"


def _load_openclaw_provider_runtime(*, root: Path, provider_id: str) -> dict[str, Any]:
    if not provider_id:
        return {}
    openclaw_root = resolve_openclaw_root(repo_root=root)
    if openclaw_root is None:
        return {}
    config_path = openclaw_root / "openclaw.json"
    if not config_path.exists():
        return {}
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    provider = (
        (((config.get("models") or {}).get("providers") or {}).get(provider_id))
        or {}
    )
    if not isinstance(provider, dict):
        return {}
    base_url = str(provider.get("baseUrl") or "").strip()
    api = str(provider.get("api") or "").strip()
    host_classification = _classify_runtime_host_from_url(base_url)
    return {
        "provider_id": provider_id,
        "base_url": base_url,
        "api": api,
        "host_classification": host_classification,
        "host_name": host_classification if host_classification != "unknown" else "",
    }


def _load_openclaw_agent_model_contract(*, root: Path, agent_id: str) -> dict[str, Any]:
    openclaw_root = resolve_openclaw_root(repo_root=root)
    if openclaw_root is None:
        return {}
    config_path = openclaw_root / "openclaw.json"
    if not config_path.exists():
        return {}
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    defaults_model = dict((((config.get("agents") or {}).get("defaults") or {}).get("model")) or {})
    agent_model: dict[str, Any] = {}
    for agent in ((config.get("agents") or {}).get("list") or []):
        if isinstance(agent, dict) and str(agent.get("id") or "") == agent_id:
            agent_model = dict(agent.get("model") or {})
            break
    effective = agent_model or defaults_model
    return {
        "primary": str(effective.get("primary") or ""),
        "fallbacks": list(effective.get("fallbacks") or []),
        "configured_fail_closed": not bool(list(effective.get("fallbacks") or [])),
    }


def _count_agent_auth_profiles(*, root: Path, agent_id: str) -> int:
    openclaw_root = resolve_openclaw_root(repo_root=root)
    if openclaw_root is None:
        return 0
    path = openclaw_root / "agents" / agent_id / "agent" / "auth-profiles.json"
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    profiles = payload.get("profiles") or {}
    if not isinstance(profiles, dict):
        return 0
    return len(profiles)


def _runtime_truth_phrase(*, discord_ready: bool, last_failure_category: str) -> str:
    if discord_ready:
        return "live"
    if last_failure_category:
        return f"degraded ({last_failure_category})"
    return "unproven"


def _shadowbroker_truth_phrase(shadowbroker_summary: dict[str, Any], extension_lane_status_summary: dict[str, Any]) -> str:
    rows = list(extension_lane_status_summary.get("rows") or [])
    shadowbroker_row = next((row for row in rows if str(row.get("lane") or "") == "shadowbroker"), {})
    if shadowbroker_summary.get("configured") and shadowbroker_summary.get("healthy"):
        return "ShadowBroker integration exists in the repo and is live on this machine."
    backend_status = str(
        shadowbroker_summary.get("degraded_reason")
        or shadowbroker_summary.get("backend_status")
        or shadowbroker_row.get("reason")
        or "external runtime not proven"
    )
    return (
        "ShadowBroker integration exists in the repo, but machine-local live availability is "
        f"blocked, degraded, or unproven right now ({backend_status})."
    )


def _build_suggested_clean_reply(
    *,
    latest_user_query: str,
    latest_user_facing_reply: str,
    active_provider: Any,
    active_model: Any,
    active_backend: Any,
    active_host: Any,
    active_endpoint: Any,
    discord_ready: bool,
    last_failure_category: str,
    shadowbroker_summary: dict[str, Any],
    extension_lane_status_summary: dict[str, Any],
) -> str:
    query = str(latest_user_query or "").strip()
    normalized = query.lower()
    runtime_truth = _runtime_truth_phrase(discord_ready=discord_ready, last_failure_category=last_failure_category)
    runtime_parts = [
        str(part).strip()
        for part in [active_provider, active_model, active_backend]
        if str(part or "").strip()
    ]
    runtime_path = "/".join(runtime_parts[:2]) if len(runtime_parts) >= 2 else " ".join(runtime_parts)
    if "model" in normalized:
        runtime_detail = runtime_path or "the configured Jarvis Discord path"
        host_detail = str(active_host or "unknown host")
        endpoint_detail = str(active_endpoint or "unknown endpoint")
        return (
            f"Current Jarvis Discord runtime is {runtime_detail} on {host_detail} "
            f"at {endpoint_detail}. Live availability is {runtime_truth}."
        )
    if "shadowbroker" in normalized:
        return _shadowbroker_truth_phrase(shadowbroker_summary, extension_lane_status_summary)
    return str(latest_user_facing_reply or "").strip()


def build_operator_discord_runtime_check(*, root: Path) -> dict[str, Any]:
    status = build_status(root)
    discord_live_ops = dict(status.get("discord_live_ops_summary") or {})
    live_lane = dict(discord_live_ops.get("live_lane_diagnostic") or {})
    latest_task = dict(discord_live_ops.get("latest_discord_task") or {})
    latest_refusal = dict(discord_live_ops.get("latest_discord_routing_refusal") or {})
    bridge = dict(status.get("openclaw_discord_bridge_summary") or {})
    latest_attempt = dict(bridge.get("latest_attempt") or {})
    latest_bridge_failure = dict(bridge.get("latest_failure") or {})
    session_summary = dict(status.get("openclaw_discord_session_summary") or {})
    recent_sessions = list(session_summary.get("recent_discord_sessions") or [])
    latest_session = dict(recent_sessions[0] or {}) if recent_sessions else {}
    latest_malformed = dict(session_summary.get("latest_malformed_session") or {})
    routing_control = dict(status.get("routing_control_plane_summary") or {})
    latest_selected_route = dict(routing_control.get("latest_selected_route") or {})
    shadowbroker_summary = dict(status.get("shadowbroker_summary") or {})
    extension_lane_status_summary = dict(status.get("extension_lane_status_summary") or {})

    session_front_door_ingress = bool(latest_session.get("front_door_discord_ingress_detected"))
    session_front_door_reply = bool(latest_session.get("front_door_assistant_reply_detected"))
    session_gateway_execution_evidence = bool(latest_session.get("gateway_execution_evidence_detected"))
    session_source_owned_report = bool(latest_session.get("has_source_owned_system_prompt_report"))

    active_provider = _nonempty(
        live_lane.get("selected_provider_id"),
        latest_task.get("provider_id"),
        latest_attempt.get("selected_provider_id"),
        latest_session.get("selected_provider_id"),
        latest_session.get("provider_override"),
        latest_malformed.get("selected_provider_id"),
        latest_malformed.get("provider_override"),
    )
    active_model = _nonempty(
        live_lane.get("selected_model_name"),
        latest_task.get("selected_model_name"),
        latest_attempt.get("selected_model_name"),
        latest_session.get("selected_model_name"),
        latest_session.get("model_override"),
        latest_malformed.get("selected_model_name"),
        latest_malformed.get("model_override"),
    )
    provider_runtime = _load_openclaw_provider_runtime(root=root, provider_id=str(active_provider or ""))
    agent_model_contract = _load_openclaw_agent_model_contract(root=root, agent_id="jarvis")
    configured_auth_profile_count = _count_agent_auth_profiles(root=root, agent_id="jarvis")
    active_backend = _nonempty(
        live_lane.get("selected_backend"),
        latest_task.get("execution_backend"),
        latest_selected_route.get("execution_backend"),
        provider_runtime.get("api"),
    )
    active_host = _nonempty(
        live_lane.get("selected_host_name"),
        latest_task.get("selected_host_name"),
        latest_selected_route.get("host_name"),
        provider_runtime.get("host_name"),
    )
    active_endpoint = _nonempty(provider_runtime.get("base_url"))
    route_selected = bool(live_lane.get("route_selected") or session_gateway_execution_evidence)
    backend_execution_attempted = bool(live_lane.get("backend_execution_attempted") or session_gateway_execution_evidence)
    latest_attempt_present = bool(latest_attempt or (session_front_door_ingress and session_front_door_reply))
    last_failure_category = str(
        _nonempty(
            live_lane.get("failure_category"),
            latest_refusal.get("failure_code"),
            latest_bridge_failure.get("failure_class"),
        )
        or ""
    )
    last_failure_reason = str(
        _nonempty(
            live_lane.get("failure_reason"),
            latest_refusal.get("failure_reason"),
            latest_bridge_failure.get("failure_reason"),
        )
        or ""
    )
    session_looks_healthy = int(session_summary.get("malformed_session_count") or 0) == 0
    configured_fallbacks = list(agent_model_contract.get("fallbacks") or [])
    configured_fail_closed = bool(agent_model_contract.get("configured_fail_closed"))
    real_alternate_configured_path_present = bool(configured_fallbacks) or configured_auth_profile_count > 1
    generic_internal_retry_possible = bool(active_provider)

    blocking_reasons: list[str] = []
    required_actions: list[str] = []
    if not active_provider or not active_model or not active_backend:
        blocking_reasons.append("Active Discord provider/model/backend truth is incomplete.")
        required_actions.append("Run a fresh Discord request and inspect the resulting bridge/live-lane summaries.")
    if not (route_selected or backend_execution_attempted or latest_attempt_present):
        blocking_reasons.append("No fresh Discord route/execution evidence is present.")
        required_actions.append("Send one fresh Discord message and re-run `python3 scripts/operator_discord_runtime_check.py --json`.")
    if not session_looks_healthy:
        blocking_reasons.append("Malformed Discord session state detected.")
        required_actions.append(
            latest_malformed.get("operator_action_required")
            or "Run `python3 scripts/repair_discord_sessions.py --repair-all-malformed --repair`."
        )
    if last_failure_category:
        blocking_reasons.append(f"Latest Discord lane failure: {last_failure_category}.")
        required_actions.append(
            str(live_lane.get("next_inspect") or "Inspect discord_live_ops_summary and openclaw_discord_bridge_summary.")
        )
    if latest_bridge_failure and not last_failure_category:
        blocking_reasons.append(
            f"Latest mirrored OpenClaw Discord attempt failed: {latest_bridge_failure.get('failure_class') or 'unknown'}."
        )
        required_actions.append("Inspect the external OpenClaw Discord/gateway runtime for the latest failed attempt.")

    readiness_criteria = [
        {
            "name": "active_route_known",
            "ok": bool(active_provider and active_model and active_backend),
            "details": {
                "provider_id": active_provider,
                "model_name": active_model,
                "backend_runtime": active_backend,
                "endpoint": active_endpoint,
            },
        },
        {
            "name": "live_execution_evidence_present",
            "ok": bool(route_selected or backend_execution_attempted or latest_attempt_present),
            "details": {
                "route_selected": route_selected,
                "backend_execution_attempted": backend_execution_attempted,
                "bridge_attempt_present": latest_attempt_present,
                "session_front_door_ingress_detected": session_front_door_ingress,
                "session_gateway_execution_evidence_detected": session_gateway_execution_evidence,
                "session_source_owned_report_detected": session_source_owned_report,
            },
        },
        {
            "name": "session_state_healthy",
            "ok": session_looks_healthy,
            "details": {
                "malformed_session_count": session_summary.get("malformed_session_count", 0),
                "latest_malformed_session_id": latest_malformed.get("session_id"),
            },
        },
        {
            "name": "latest_discord_lane_not_failed",
            "ok": not bool(last_failure_category),
            "details": {
                "failure_category": last_failure_category,
                "failure_reason": last_failure_reason,
            },
        },
    ]
    discord_ready = all(bool(item["ok"]) for item in readiness_criteria)
    sanitized_latest_reply = sanitize_user_facing_assistant_reply(latest_session.get("latest_assistant_reply_raw") or "")
    latest_user_facing_reply = str(
        latest_session.get("latest_user_facing_reply")
        or sanitized_latest_reply.get("clean_text")
        or ""
    )
    suggested_clean_reply = _build_suggested_clean_reply(
        latest_user_query=str(latest_session.get("last_user_query") or ""),
        latest_user_facing_reply=latest_user_facing_reply,
        active_provider=active_provider,
        active_model=active_model,
        active_backend=active_backend,
        active_host=active_host,
        active_endpoint=active_endpoint,
        discord_ready=discord_ready,
        last_failure_category=last_failure_category,
        shadowbroker_summary=shadowbroker_summary,
        extension_lane_status_summary=extension_lane_status_summary,
    )

    return {
        "summary_kind": "operator_discord_runtime_check",
        "checked_at": status.get("generated_at"),
        "discord_ready": discord_ready,
        "readiness_criteria": readiness_criteria,
        "active_provider_id": active_provider,
        "active_model": active_model,
        "active_backend_runtime": active_backend,
        "active_endpoint": active_endpoint,
        "active_host_name": active_host,
        "active_host_classification": _classify_runtime_host(str(active_host or "")),
        "configured_primary_path": agent_model_contract.get("primary") or "",
        "configured_fallbacks": configured_fallbacks,
        "configured_fail_closed": configured_fail_closed,
        "configured_auth_profile_count": configured_auth_profile_count,
        "real_alternate_configured_path_present": real_alternate_configured_path_present,
        "generic_internal_retry_possible": generic_internal_retry_possible,
        "retry_truth": {
            "configured_fail_closed": configured_fail_closed,
            "configured_fallback_count": len(configured_fallbacks),
            "configured_auth_profile_count": configured_auth_profile_count,
            "real_alternate_configured_path_present": real_alternate_configured_path_present,
            "generic_internal_retry_possible": generic_internal_retry_possible,
            "interpretation": (
                "OpenClaw may still log generic internal retry/failover text before checking for another auth profile."
                if generic_internal_retry_possible and not real_alternate_configured_path_present
                else "A real alternate configured path exists."
                if real_alternate_configured_path_present
                else "No retry behavior is currently inferred."
            ),
        },
        "route_selected": route_selected,
        "backend_execution_attempted": backend_execution_attempted,
        "last_failure_category": last_failure_category,
        "last_failure_reason": last_failure_reason,
        "timeout_stage": live_lane.get("timeout_stage"),
        "degraded_fallback_attempted": bool(live_lane.get("degraded_fallback_attempted")),
        "degraded_fallback_blocked": bool(live_lane.get("degraded_fallback_blocked")),
        "session_looks_healthy": session_looks_healthy,
        "latest_user_query": str(latest_session.get("last_user_query") or ""),
        "latest_assistant_reply_raw": str(latest_session.get("latest_assistant_reply_raw") or ""),
        "latest_user_facing_reply": latest_user_facing_reply,
        "latest_assistant_reply_contaminated": bool(
            latest_session.get("latest_assistant_reply_contaminated")
            or sanitized_latest_reply.get("was_sanitized")
        ),
        "latest_assistant_reply_findings": list(
            latest_session.get("latest_assistant_reply_findings")
            or sanitized_latest_reply.get("removed_fragments")
            or []
        ),
        "suggested_clean_reply": suggested_clean_reply,
        "operator_action_required": required_actions,
        "blocking_reasons": blocking_reasons,
        "source_refs": {
            "discord_live_ops_summary": {
                "latest_discord_task": latest_task or None,
                "latest_discord_routing_refusal": latest_refusal or None,
                "live_lane_diagnostic": live_lane or None,
            },
            "openclaw_discord_bridge_summary": {
                "latest_attempt": latest_attempt or None,
                "latest_failure": latest_bridge_failure or None,
                "latest_successful_reply": bridge.get("latest_successful_reply"),
            },
            "openclaw_discord_session_summary": {
                "malformed_session_count": session_summary.get("malformed_session_count", 0),
                "latest_malformed_session": latest_malformed or None,
                "latest_session": latest_session or None,
                "session_front_door_ingress_detected": session_front_door_ingress,
                "session_gateway_execution_evidence_detected": session_gateway_execution_evidence,
            },
            "routing_control_plane_summary": {
                "latest_selected_route": latest_selected_route or None,
                "latest_route_state": routing_control.get("latest_route_state"),
                "latest_route_legality": routing_control.get("latest_route_legality"),
            },
        },
    }


def render_operator_discord_runtime_check(report: dict[str, Any]) -> str:
    lines = [
        f"operator_discord_runtime_check: {'HEALTHY' if report.get('discord_ready') else 'BLOCKED'}",
        f"checked_at: {report.get('checked_at') or 'unknown'}",
        (
            "active_runtime: "
            f"provider={report.get('active_provider_id') or 'unknown'} "
            f"model={report.get('active_model') or 'unknown'} "
            f"backend={report.get('active_backend_runtime') or 'unknown'} "
            f"host={report.get('active_host_name') or 'unknown'} "
            f"host_class={report.get('active_host_classification') or 'unknown'}"
        ),
        (
            "configured_path: "
            f"primary={report.get('configured_primary_path') or 'unknown'} "
            f"fallbacks={len(report.get('configured_fallbacks') or [])} "
            f"auth_profiles={report.get('configured_auth_profile_count') or 0} "
            f"real_alternate_path={report.get('real_alternate_configured_path_present')}"
        ),
        (
            "lane_state: "
            f"route_selected={report.get('route_selected')} "
            f"backend_execution_attempted={report.get('backend_execution_attempted')} "
            f"failure_category={report.get('last_failure_category') or 'none'} "
            f"timeout_stage={report.get('timeout_stage') or 'none'} "
            f"fallback_blocked={report.get('degraded_fallback_blocked')}"
        ),
        f"retry_truth: {((report.get('retry_truth') or {}).get('interpretation')) or 'unknown'}",
        (
            "session_state: "
            f"healthy={report.get('session_looks_healthy')} "
            f"malformed_count={((report.get('source_refs') or {}).get('openclaw_discord_session_summary') or {}).get('malformed_session_count', 0)}"
        ),
        (
            "reply_sanitizer: "
            f"contaminated={report.get('latest_assistant_reply_contaminated')} "
            f"findings={len(report.get('latest_assistant_reply_findings') or [])}"
        ),
    ]
    if report.get("suggested_clean_reply"):
        lines.append(f"clean_reply: {report.get('suggested_clean_reply')}")
    for reason in list(report.get("blocking_reasons") or []):
        lines.append(f"- blocker: {reason}")
    for action in list(report.get("operator_action_required") or []):
        lines.append(f"  next: {action}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check live Discord runtime truth using existing Jarvis/OpenClaw summaries.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    args = parser.parse_args()

    report = build_operator_discord_runtime_check(root=ROOT)
    write_report(ROOT, "operator_discord_runtime_check.json", report)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_operator_discord_runtime_check(report))
    return 0 if report.get("discord_ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
