#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.degradation_policy import list_degradation_policies
from runtime.core.a2a_policy import build_a2a_policy_summary
from runtime.core.mcp_policy import build_mcp_policy_summary
from runtime.core.plugin_policy import build_plugin_policy_summary
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
    return {
        "validation_layer_present": True,
        "supported_checks": [
            "tool_output_safety",
            "degradation_safety",
            "route_safety",
            "mcp_policy",
            "plugin_policy",
            "a2a_policy",
        ],
        "degradation_policy_count_checked": len(degradation_checks),
        "degradation_policy_flag_count": degradation_flag_count,
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
