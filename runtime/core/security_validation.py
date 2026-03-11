#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.degradation_policy import list_degradation_policies
from runtime.core.a2a_policy import build_a2a_policy_summary, enforce_a2a_runtime_request
from runtime.core.mcp_policy import build_mcp_policy_summary, enforce_mcp_runtime_request
from runtime.core.plugin_policy import build_plugin_policy_summary, enforce_plugin_runtime_request
from runtime.core.risk_tier import evaluate_risk_tier


_INJECTION_PATTERNS = {
    "ignore previous instructions": "prompt_injection_ignore_instructions",
    "reveal system prompt": "prompt_injection_reveal_system_prompt",
    "exfiltrate": "data_exfiltration_language",
    "bypass approval": "approval_bypass_language",
}

_SAFE_DEGRADATION_PREFIXES = (
    "fail_closed",
    "text_fallback",
    "read_only",
    "require_text_confirm",
)

_SAFE_FALLBACK_PREFIXES = (
    "no_",
    "text_",
)

_DISCORD_MESSAGE_INTENTS = {"draft_message", "send_message", "post_message", "reply_message"}
_TRADING_EXECUTION_INTENTS = {"place_trade", "buy", "sell", "submit_order", "execute_trade"}
_LOCALHOST_HOSTS = {"127.0.0.1", "localhost", "::1"}
_URL_RE = re.compile(r"https?://([^/\s:]+)")
_MCP_HINTS = ("mcp", "model context protocol", "authenticated tool")
_PLUGIN_HINTS = ("plugin", "skill pack", "bundle")
_A2A_HINTS = ("a2a", "daemon")


def _severity_from_findings(findings: list[str]) -> str:
    if not findings:
        return "none"
    if any(
        finding in {
            "prompt_injection_ignore_instructions",
            "prompt_injection_reveal_system_prompt",
            "data_exfiltration_language",
            "approval_bypass_language",
            "trade_execution_route_flagged",
            "degradation_widens_privilege_surface",
        }
        for finding in findings
    ):
        return "high"
    return "medium"


def validate_tool_output_safety(
    output_text: str,
    *,
    source: str = "",
    root=None,
) -> dict:
    del root
    text = (output_text or "").strip().lower()
    findings = [label for pattern, label in _INJECTION_PATTERNS.items() if pattern in text]
    safe = not findings
    return {
        "safe": safe,
        "severity": _severity_from_findings(findings),
        "findings": findings,
        "reason": "tool_output_clear" if safe else "tool_output_flagged",
        "source": source,
    }


def validate_degradation_safety(
    *,
    subsystem: str,
    degradation_mode: str,
    fallback_action: str,
    root=None,
) -> dict:
    del root
    mode = (degradation_mode or "").strip()
    fallback = (fallback_action or "").strip()
    findings: list[str] = []

    if not mode.startswith(_SAFE_DEGRADATION_PREFIXES):
        findings.append("degradation_mode_not_fail_safe")
    if not fallback.startswith(_SAFE_FALLBACK_PREFIXES):
        findings.append("degradation_widens_privilege_surface")

    safe = not findings
    return {
        "safe": safe,
        "severity": _severity_from_findings(findings),
        "findings": findings,
        "reason": "degradation_fallback_safe" if safe else "degradation_fallback_flagged",
        "subsystem": subsystem,
        "degradation_mode": mode,
        "fallback_action": fallback,
    }


def validate_route_safety(
    *,
    subsystem: str,
    intent: str,
    query: str = "",
    root=None,
) -> dict:
    del root
    subsystem_name = (subsystem or "").strip().lower()
    normalized_intent = (intent or "").strip().lower()
    findings: list[str] = []

    if subsystem_name == "tradingview" and normalized_intent in _TRADING_EXECUTION_INTENTS:
        findings.append("trade_execution_route_flagged")
    elif subsystem_name == "discord" and normalized_intent in _DISCORD_MESSAGE_INTENTS:
        findings.append("message_send_like_route_requires_tighter_approval")
    query_safety = validate_tool_output_safety(query, source="voice_route_query")
    findings.extend(query_safety["findings"])

    action_type = {
        ("tradingview", "set_symbol"): "type_into_field",
        ("tradingview", "set_timeframe"): "type_into_field",
        ("tradingview", "capture_chart"): "inspect_page",
        ("discord", "draft_message"): "create_draft_artifact",
    }.get((subsystem_name, normalized_intent), "show_status")
    risk = evaluate_risk_tier(action_type, subsystem_name or "unknown", {"intent": normalized_intent, "query": query})

    safe = not findings
    return {
        "safe": safe,
        "severity": _severity_from_findings(findings),
        "findings": findings,
        "reason": "route_safe" if safe else "route_flagged",
        "subsystem": subsystem_name,
        "intent": normalized_intent,
        "risk_tier": risk["tier"],
    }


def validate_localhost_config_posture(*, root=None) -> dict:
    root_path = Path(root or ROOT).resolve()
    findings: list[str] = []
    checked_files: list[str] = []
    non_localhost_endpoints: list[str] = []

    for rel in ("config/models.yaml", "config/app.yaml"):
        path = root_path / rel
        if not path.exists():
            continue
        checked_files.append(rel)
        text = path.read_text(encoding="utf-8")
        for match in _URL_RE.findall(text):
            host = (match or "").strip().lower()
            if host and host not in _LOCALHOST_HOSTS:
                non_localhost_endpoints.append(host)
        if "0.0.0.0" in text:
            findings.append("wildcard_bind_posture")

    if non_localhost_endpoints:
        findings.append("non_localhost_endpoint_configured")

    safe = not findings
    return {
        "safe": safe,
        "severity": _severity_from_findings(findings),
        "findings": findings,
        "reason": "localhost_config_safe" if safe else "localhost_config_flagged",
        "checked_files": checked_files,
        "non_localhost_endpoints": sorted(set(non_localhost_endpoints)),
    }


def validate_runtime_policy_request(
    normalized_command: str,
    *,
    action_type: str = "",
    root=None,
) -> dict:
    command = (normalized_command or "").strip().lower()
    action = (action_type or "").strip().lower()

    if action == "open_authenticated_tool" or any(token in command for token in _MCP_HINTS):
        enforcement = enforce_mcp_runtime_request(
            server_name="voice_runtime",
            transport="voice_gateway",
            auth_mode="",
            tool_name=action or command or "authenticated_tool",
            requested_scope="",
            auth_present=False,
            declared_tools=[],
            declared_scopes=[],
            localhost_only=True,
            root=root,
        )
        return {
            "safe": enforcement["allowed"],
            "policy_surface": "mcp",
            "reason": enforcement["reason"],
            "findings": enforcement["findings"],
            "enforcement": enforcement,
        }

    if any(token in command for token in _PLUGIN_HINTS):
        enforcement = enforce_plugin_runtime_request(
            plugin_id="voice_runtime_plugin",
            plugin_kind="plugin",
            requested_capability=command,
            requested_scope="",
            operator_approved=False,
            reversible=True,
            portability_mode="runtime_local",
            declared_capabilities=[],
            declared_scopes=[],
            approval_required=True,
            root=root,
        )
        return {
            "safe": enforcement["allowed"],
            "policy_surface": "plugin",
            "reason": enforcement["reason"],
            "findings": enforcement["findings"],
            "enforcement": enforcement,
        }

    if any(token in command for token in _A2A_HINTS):
        enforcement = enforce_a2a_runtime_request(
            daemon_name="voice_runtime",
            transport="voice_gateway",
            auth_mode="",
            source_daemon="jarvis",
            target_daemon="unspecified",
            action_name=command or action or "daemon_request",
            requested_scope="",
            auth_present=False,
            session_bound=False,
            declared_actions=[],
            declared_scopes=[],
            localhost_only=True,
            reversible_sessions=True,
            root=root,
        )
        return {
            "safe": enforcement["allowed"],
            "policy_surface": "a2a",
            "reason": enforcement["reason"],
            "findings": enforcement["findings"],
            "enforcement": enforcement,
        }

    return {
        "safe": True,
        "policy_surface": "none",
        "reason": "no_runtime_policy_surface_triggered",
        "findings": [],
        "enforcement": None,
    }


def build_security_validation_summary(root: Optional[Path] = None) -> dict:
    root_path = Path(root or ROOT).resolve()
    degradation_checks = [
        validate_degradation_safety(
            subsystem=row.subsystem,
            degradation_mode=row.degradation_mode,
            fallback_action=row.fallback_action,
            root=root_path,
        )
        for row in list_degradation_policies(root=root_path)
    ]
    degradation_flag_count = sum(1 for row in degradation_checks if not row["safe"])
    localhost_posture = validate_localhost_config_posture(root=root_path)
    return {
        "validation_layer_present": True,
        "supported_checks": [
            "tool_output_safety",
            "degradation_safety",
            "route_safety",
            "localhost_config_posture",
            "runtime_policy_request_gating",
            "mcp_policy",
            "plugin_policy",
            "a2a_policy",
        ],
        "degradation_policy_count_checked": len(degradation_checks),
        "degradation_policy_flag_count": degradation_flag_count,
        "localhost_config_posture": localhost_posture,
        "a2a_policy_summary": build_a2a_policy_summary(root=root_path),
        "mcp_policy_summary": build_mcp_policy_summary(root=root_path),
        "plugin_policy_summary": build_plugin_policy_summary(root=root_path),
        "latest_example_findings": [row["findings"] for row in degradation_checks if row["findings"]][:3],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the security validation summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_security_validation_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
