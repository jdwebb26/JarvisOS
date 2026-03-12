#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.status import build_status
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
    if normalized == "LOCAL":
        return "LOCAL"
    return "unknown"


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
    latest_malformed = dict(session_summary.get("latest_malformed_session") or {})
    routing_control = dict(status.get("routing_control_plane_summary") or {})
    latest_selected_route = dict(routing_control.get("latest_selected_route") or {})

    active_provider = _nonempty(
        live_lane.get("selected_provider_id"),
        latest_task.get("provider_id"),
        latest_attempt.get("selected_provider_id"),
        latest_malformed.get("selected_provider_id"),
        latest_malformed.get("provider_override"),
    )
    active_model = _nonempty(
        live_lane.get("selected_model_name"),
        latest_task.get("selected_model_name"),
        latest_attempt.get("selected_model_name"),
        latest_malformed.get("selected_model_name"),
        latest_malformed.get("model_override"),
    )
    active_backend = _nonempty(
        live_lane.get("selected_backend"),
        latest_task.get("execution_backend"),
        latest_selected_route.get("execution_backend"),
    )
    active_host = _nonempty(
        live_lane.get("selected_host_name"),
        latest_task.get("selected_host_name"),
        latest_selected_route.get("host_name"),
    )
    route_selected = bool(live_lane.get("route_selected"))
    backend_execution_attempted = bool(live_lane.get("backend_execution_attempted"))
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

    blocking_reasons: list[str] = []
    required_actions: list[str] = []
    if not active_provider or not active_model or not active_backend:
        blocking_reasons.append("Active Discord provider/model/backend truth is incomplete.")
        required_actions.append("Run a fresh Discord request and inspect the resulting bridge/live-lane summaries.")
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

    return {
        "summary_kind": "operator_discord_runtime_check",
        "checked_at": status.get("generated_at"),
        "discord_ready": discord_ready,
        "readiness_criteria": readiness_criteria,
        "active_provider_id": active_provider,
        "active_model": active_model,
        "active_backend_runtime": active_backend,
        "active_host_name": active_host,
        "active_host_classification": _classify_runtime_host(str(active_host or "")),
        "route_selected": route_selected,
        "backend_execution_attempted": backend_execution_attempted,
        "last_failure_category": last_failure_category,
        "last_failure_reason": last_failure_reason,
        "timeout_stage": live_lane.get("timeout_stage"),
        "degraded_fallback_attempted": bool(live_lane.get("degraded_fallback_attempted")),
        "degraded_fallback_blocked": bool(live_lane.get("degraded_fallback_blocked")),
        "session_looks_healthy": session_looks_healthy,
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
            "lane_state: "
            f"route_selected={report.get('route_selected')} "
            f"backend_execution_attempted={report.get('backend_execution_attempted')} "
            f"failure_category={report.get('last_failure_category') or 'none'} "
            f"timeout_stage={report.get('timeout_stage') or 'none'} "
            f"fallback_blocked={report.get('degraded_fallback_blocked')}"
        ),
        (
            "session_state: "
            f"healthy={report.get('session_looks_healthy')} "
            f"malformed_count={((report.get('source_refs') or {}).get('openclaw_discord_session_summary') or {}).get('malformed_session_count', 0)}"
        ),
    ]
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
