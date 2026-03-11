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


_SAFE_AUTH_MODES = {"token", "oauth", "oauth2", "oauth2.1"}
_DANGEROUS_TOOL_TOKENS = {
    "secret",
    "exfiltrate",
    "bypass",
    "credential",
    "token_dump",
    "auth_override",
}


def _severity_from_findings(findings: list[str]) -> str:
    if not findings:
        return "none"
    if any(
        finding in {
            "missing_auth",
            "weak_or_unknown_auth_mode",
            "non_localhost_network_posture",
            "unauthenticated_tool_request",
            "dangerous_tool_name",
        }
        for finding in findings
    ):
        return "high"
    return "medium"


def validate_mcp_server_config(
    *,
    server_name: str,
    transport: str,
    auth_mode: str,
    declared_tools: list[str] | None = None,
    declared_scopes: list[str] | None = None,
    localhost_only: bool = True,
    root=None,
) -> dict:
    del root
    tools = list(declared_tools or [])
    scopes = list(declared_scopes or [])
    normalized_auth = (auth_mode or "").strip().lower()
    findings: list[str] = []

    if not normalized_auth:
        findings.append("missing_auth")
    elif normalized_auth not in _SAFE_AUTH_MODES:
        findings.append("weak_or_unknown_auth_mode")

    if not localhost_only:
        findings.append("non_localhost_network_posture")
    if not tools:
        findings.append("missing_declared_tools")
    if not scopes:
        findings.append("missing_declared_scopes")

    safe = not findings
    return {
        "allowed": safe,
        "findings": findings,
        "severity": _severity_from_findings(findings),
        "reason": "mcp_server_config_safe" if safe else "mcp_server_config_flagged",
        "server_name": server_name,
        "transport": transport,
        "auth_mode": auth_mode,
        "localhost_only": localhost_only,
        "declared_tools": tools,
        "declared_scopes": scopes,
    }


def validate_mcp_tool_request(
    *,
    server_name: str,
    tool_name: str,
    requested_scope: str = "",
    auth_present: bool = False,
    root=None,
) -> dict:
    del root
    normalized_tool = (tool_name or "").strip().lower()
    normalized_scope = (requested_scope or "").strip()
    findings: list[str] = []

    if not auth_present:
        findings.append("unauthenticated_tool_request")
    if not normalized_scope:
        findings.append("missing_requested_scope")
    if any(token in normalized_tool for token in _DANGEROUS_TOOL_TOKENS):
        findings.append("dangerous_tool_name")

    safe = not findings
    return {
        "allowed": safe,
        "findings": findings,
        "severity": _severity_from_findings(findings),
        "reason": "mcp_tool_request_safe" if safe else "mcp_tool_request_flagged",
        "server_name": server_name,
        "tool_name": tool_name,
        "requested_scope": requested_scope,
        "auth_present": auth_present,
    }


def build_mcp_policy_summary(root: Optional[Path] = None) -> dict:
    del root
    return {
        "mcp_policy_present": True,
        "supported_checks": [
            "server_config_auth_posture",
            "server_config_localhost_posture",
            "server_config_declared_tools",
            "server_config_declared_scopes",
            "tool_request_auth",
            "tool_request_scope",
            "tool_request_dangerous_name",
        ],
        "safe_defaults": {
            "localhost_only": True,
            "preferred_auth_modes": sorted(_SAFE_AUTH_MODES),
            "declared_tools_required": True,
            "declared_scopes_required": True,
        },
        "example_required_controls": [
            "explicit_operator_approval_before_activation",
            "least_privilege_scopes",
            "structured_capability_declaration",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the MCP authorization and conformance policy summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_mcp_policy_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
