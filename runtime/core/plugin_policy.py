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


_SAFE_PLUGIN_KINDS = {"skill", "plugin", "bundle"}
_SAFE_PORTABILITY_MODES = {"portable", "repo_local", "runtime_local"}
_DANGEROUS_CAPABILITY_TOKENS = {
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
            "approval_not_required",
            "irreversible_plugin_posture",
            "missing_operator_approval",
            "irreversible_activation_posture",
            "suspicious_capability_name",
            "unknown_plugin_kind",
        }
        for finding in findings
    ):
        return "high"
    return "medium"


def validate_plugin_descriptor(
    *,
    plugin_id: str,
    plugin_kind: str,
    declared_capabilities: list[str] | None = None,
    declared_scopes: list[str] | None = None,
    approval_required: bool = True,
    reversible: bool = True,
    portability_mode: str = "",
    root=None,
) -> dict:
    del root
    capabilities = list(declared_capabilities or [])
    scopes = list(declared_scopes or [])
    normalized_kind = (plugin_kind or "").strip().lower()
    normalized_portability = (portability_mode or "").strip().lower()
    findings: list[str] = []

    if not capabilities:
        findings.append("missing_declared_capabilities")
    if not scopes:
        findings.append("missing_declared_scopes")
    if not approval_required:
        findings.append("approval_not_required")
    if not reversible:
        findings.append("irreversible_plugin_posture")
    if not normalized_portability:
        findings.append("missing_portability_mode")
    elif normalized_portability not in _SAFE_PORTABILITY_MODES:
        findings.append("unknown_portability_mode")
    if not normalized_kind or normalized_kind not in _SAFE_PLUGIN_KINDS:
        findings.append("unknown_plugin_kind")

    safe = not findings
    return {
        "allowed": safe,
        "findings": findings,
        "severity": _severity_from_findings(findings),
        "reason": "plugin_descriptor_safe" if safe else "plugin_descriptor_flagged",
        "plugin_id": plugin_id,
        "plugin_kind": plugin_kind,
        "declared_capabilities": capabilities,
        "declared_scopes": scopes,
        "approval_required": approval_required,
        "reversible": reversible,
        "portability_mode": portability_mode,
    }


def validate_plugin_activation_request(
    *,
    plugin_id: str,
    requested_capability: str,
    requested_scope: str = "",
    operator_approved: bool = False,
    reversible: bool = True,
    root=None,
) -> dict:
    del root
    normalized_capability = (requested_capability or "").strip().lower()
    normalized_scope = (requested_scope or "").strip()
    findings: list[str] = []

    if not operator_approved:
        findings.append("missing_operator_approval")
    if not normalized_scope:
        findings.append("missing_requested_scope")
    if not reversible:
        findings.append("irreversible_activation_posture")
    if any(token in normalized_capability for token in _DANGEROUS_CAPABILITY_TOKENS):
        findings.append("suspicious_capability_name")

    safe = not findings
    return {
        "allowed": safe,
        "findings": findings,
        "severity": _severity_from_findings(findings),
        "reason": "plugin_activation_safe" if safe else "plugin_activation_flagged",
        "plugin_id": plugin_id,
        "requested_capability": requested_capability,
        "requested_scope": requested_scope,
        "operator_approved": operator_approved,
        "reversible": reversible,
    }


def build_plugin_policy_summary(root: Optional[Path] = None) -> dict:
    del root
    return {
        "plugin_policy_present": True,
        "supported_checks": [
            "descriptor_declared_capabilities",
            "descriptor_declared_scopes",
            "descriptor_approval_required",
            "descriptor_reversible",
            "descriptor_portability_mode",
            "activation_operator_approval",
            "activation_requested_scope",
            "activation_suspicious_capability_name",
        ],
        "safe_defaults": {
            "approval_required": True,
            "reversible": True,
            "allowed_portability_modes": sorted(_SAFE_PORTABILITY_MODES),
            "declared_capabilities_required": True,
            "declared_scopes_required": True,
        },
        "example_required_controls": [
            "explicit_operator_approval_before_activation",
            "declared_capabilities_and_scopes",
            "policy_scoped_reversible_activation",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the skills/plugins approval and portability policy summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_plugin_policy_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
