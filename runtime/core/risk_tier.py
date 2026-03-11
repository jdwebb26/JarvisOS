#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_RISK_TIER_POLICY = {
    "high_risk_requires_text_confirmation": True,
    "medium_risk_voice_allowed": True,
    "low_risk_auto_execute": False,
}

LOW_RISK_ACTIONS = {
    "show_status",
    "inspect_page",
    "open_dashboard",
    "read_logs",
    "recall_memory",
    "navigate_allowlisted_page",
}

MEDIUM_RISK_ACTIONS = {
    "create_draft_artifact",
    "open_authenticated_tool",
    "type_into_field",
    "trigger_bounded_workflow",
}

HIGH_RISK_ACTIONS = {
    "bounded_shell",
    "mutate_files",
    "delete_files",
    "push_code",
    "send_external_message",
    "change_credentials",
    "trading_action",
    "irreversible_change",
}

TEXT_CONFIRMED_SOURCES = {"text", "cli", "dashboard", "operator_text", "review"}
VOICE_SOURCES = {"voice", "dictation"}


def load_risk_tier_policy(*, root: Optional[Path] = None) -> dict[str, bool]:
    root_path = Path(root or ROOT).resolve()
    path = root_path / "config" / "policies.yaml"
    policy = dict(DEFAULT_RISK_TIER_POLICY)
    if not path.exists():
        return policy

    in_section = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" ") and stripped.endswith(":"):
            in_section = stripped[:-1] == "risk_tier_policy"
            continue
        if not in_section:
            continue
        if not line.startswith("  "):
            continue
        if ":" not in stripped:
            continue
        key, value = [part.strip() for part in stripped.split(":", 1)]
        if key not in policy:
            continue
        lowered = value.lower()
        if lowered == "true":
            policy[key] = True
        elif lowered == "false":
            policy[key] = False
    return policy


def evaluate_risk_tier(action_type: str, subsystem: str, context: Optional[dict[str, Any]] = None) -> dict[str, str]:
    action = (action_type or "").strip()
    subsystem_name = (subsystem or "").strip()
    context_data = dict(context or {})

    if action in HIGH_RISK_ACTIONS:
        return {
            "tier": "high",
            "required_confirmation_level": "text_required",
            "reason": f"high_risk_action:{action}",
        }
    if action in MEDIUM_RISK_ACTIONS:
        return {
            "tier": "medium",
            "required_confirmation_level": "voice_ok",
            "reason": f"medium_risk_action:{action}",
        }
    if action in LOW_RISK_ACTIONS:
        return {
            "tier": "low",
            "required_confirmation_level": "none",
            "reason": f"low_risk_action:{action}",
        }

    if context_data.get("sensitive") or context_data.get("destructive"):
        return {
            "tier": "high",
            "required_confirmation_level": "text_required",
            "reason": f"high_risk_context:{action or subsystem_name or 'unspecified'}",
        }
    if context_data.get("authenticated") or context_data.get("writes_state"):
        return {
            "tier": "medium",
            "required_confirmation_level": "voice_ok",
            "reason": f"medium_risk_context:{action or subsystem_name or 'unspecified'}",
        }

    if subsystem_name in {"browser_backend", "voice_pipeline", "desktop_executor"}:
        return {
            "tier": "medium",
            "required_confirmation_level": "voice_ok",
            "reason": f"medium_risk_subsystem:{subsystem_name}",
        }

    return {
        "tier": "low",
        "required_confirmation_level": "none",
        "reason": f"default_low_risk:{action or subsystem_name or 'unspecified'}",
    }


def requires_operator_confirmation(
    tier: str,
    input_source: str,
    policy: Optional[dict[str, bool]] = None,
) -> bool:
    effective_policy = dict(DEFAULT_RISK_TIER_POLICY)
    if policy:
        effective_policy.update(policy)

    source = (input_source or "").strip().lower()

    if tier == "high":
        if effective_policy.get("high_risk_requires_text_confirmation", True):
            return source not in TEXT_CONFIRMED_SOURCES
        return False

    if tier == "medium":
        if source in TEXT_CONFIRMED_SOURCES:
            return False
        if source in VOICE_SOURCES:
            return not effective_policy.get("medium_risk_voice_allowed", True)
        return True

    if tier == "low":
        if source in TEXT_CONFIRMED_SOURCES or source in VOICE_SOURCES:
            return False
        return not effective_policy.get("low_risk_auto_execute", False)

    raise ValueError(f"Unsupported risk tier: {tier}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate bounded risk tier and confirmation requirements.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--action-type", required=True, help="Action type to classify")
    parser.add_argument("--subsystem", default="", help="Subsystem name")
    parser.add_argument("--input-source", default="system", help="Input source for confirmation check")
    args = parser.parse_args()

    policy = load_risk_tier_policy(root=Path(args.root).resolve())
    tier_result = evaluate_risk_tier(args.action_type, args.subsystem, {})
    requires_confirmation = requires_operator_confirmation(
        tier_result["tier"],
        args.input_source,
        policy=policy,
    )
    print(
        json.dumps(
            {
                "risk_tier_policy": policy,
                "evaluation": tier_result,
                "requires_operator_confirmation": requires_confirmation,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
