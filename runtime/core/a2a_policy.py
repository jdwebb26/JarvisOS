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


_SAFE_AUTH_MODES = {"token", "oauth", "oauth2", "oauth2.1", "mutual_tls"}
_DANGEROUS_ACTION_TOKENS = {
    "exfiltrate",
    "bypass",
    "secret",
    "dump",
    "approval_override",
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
            "irreversible_daemon_session_posture",
            "unauthenticated_a2a_request",
            "unbound_session_posture",
            "dangerous_action_name",
        }
        for finding in findings
    ):
        return "high"
    return "medium"


def validate_daemon_descriptor(
    *,
    daemon_name: str,
    transport: str,
    auth_mode: str,
    declared_actions: list[str] | None = None,
    declared_scopes: list[str] | None = None,
    localhost_only: bool = True,
    reversible_sessions: bool = True,
    root=None,
) -> dict:
    del root
    actions = list(declared_actions or [])
    scopes = list(declared_scopes or [])
    normalized_auth = (auth_mode or "").strip().lower()
    findings: list[str] = []

    if not normalized_auth:
        findings.append("missing_auth")
    elif normalized_auth not in _SAFE_AUTH_MODES:
        findings.append("weak_or_unknown_auth_mode")
    if not localhost_only:
        findings.append("non_localhost_network_posture")
    if not actions:
        findings.append("missing_declared_actions")
    if not scopes:
        findings.append("missing_declared_scopes")
    if not reversible_sessions:
        findings.append("irreversible_daemon_session_posture")

    safe = not findings
    return {
        "allowed": safe,
        "findings": findings,
        "severity": _severity_from_findings(findings),
        "reason": "daemon_descriptor_safe" if safe else "daemon_descriptor_flagged",
        "daemon_name": daemon_name,
        "transport": transport,
        "auth_mode": auth_mode,
        "localhost_only": localhost_only,
        "reversible_sessions": reversible_sessions,
        "declared_actions": actions,
        "declared_scopes": scopes,
    }


def validate_a2a_request(
    *,
    source_daemon: str,
    target_daemon: str,
    action_name: str,
    requested_scope: str = "",
    auth_present: bool = False,
    session_bound: bool = True,
    root=None,
) -> dict:
    del root
    normalized_action = (action_name or "").strip().lower()
    normalized_scope = (requested_scope or "").strip()
    findings: list[str] = []

    if not auth_present:
        findings.append("unauthenticated_a2a_request")
    if not normalized_scope:
        findings.append("missing_requested_scope")
    if not session_bound:
        findings.append("unbound_session_posture")
    if any(token in normalized_action for token in _DANGEROUS_ACTION_TOKENS):
        findings.append("dangerous_action_name")

    safe = not findings
    return {
        "allowed": safe,
        "findings": findings,
        "severity": _severity_from_findings(findings),
        "reason": "a2a_request_safe" if safe else "a2a_request_flagged",
        "source_daemon": source_daemon,
        "target_daemon": target_daemon,
        "action_name": action_name,
        "requested_scope": requested_scope,
        "auth_present": auth_present,
        "session_bound": session_bound,
    }


def build_a2a_policy_summary(root: Optional[Path] = None) -> dict:
    del root
    return {
        "a2a_policy_present": True,
        "supported_checks": [
            "daemon_descriptor_auth_posture",
            "daemon_descriptor_localhost_posture",
            "daemon_descriptor_declared_actions",
            "daemon_descriptor_declared_scopes",
            "daemon_descriptor_reversible_sessions",
            "a2a_request_auth",
            "a2a_request_scope",
            "a2a_request_session_binding",
            "a2a_request_dangerous_action_name",
        ],
        "safe_defaults": {
            "localhost_only": True,
            "reversible_sessions": True,
            "preferred_auth_modes": sorted(_SAFE_AUTH_MODES),
            "declared_actions_required": True,
            "declared_scopes_required": True,
        },
        "example_required_controls": [
            "authenticated_daemon_requests",
            "session_bound_requests",
            "least_privilege_scopes",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the A2A-aware daemon interface policy summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_a2a_policy_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
