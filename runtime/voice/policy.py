#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Optional

from runtime.core.risk_tier import evaluate_risk_tier, load_risk_tier_policy, requires_operator_confirmation


ROOT = Path(__file__).resolve().parents[2]


VOICE_COMMAND_ACTION_MAP = {
    "show status": "show_status",
    "open dashboard": "open_dashboard",
    "read logs": "read_logs",
    "recall memory": "recall_memory",
    "create draft artifact": "create_draft_artifact",
    "open authenticated tool": "open_authenticated_tool",
    "type into field": "type_into_field",
    "trigger bounded workflow": "trigger_bounded_workflow",
    "send external message": "send_external_message",
    "change credentials": "change_credentials",
    "delete files": "delete_files",
    "mutate files": "mutate_files",
    "push code": "push_code",
    "trading action": "trading_action",
    "irreversible change": "irreversible_change",
}


def classify_voice_action_type(normalized_command: str) -> str:
    command = (normalized_command or "").strip().lower()
    if command in VOICE_COMMAND_ACTION_MAP:
        return VOICE_COMMAND_ACTION_MAP[command]
    parts = command.split()
    return "_".join(parts) if parts else "show_status"


def evaluate_voice_command_policy(
    normalized_command: str,
    *,
    speaker_confidence: float = 0.0,
    input_source: str = "voice",
    root=None,
) -> dict:
    del speaker_confidence
    resolved_root = Path(root or ROOT).resolve()
    action_type = classify_voice_action_type(normalized_command)
    risk = evaluate_risk_tier(action_type, "voice_pipeline", {"normalized_command": normalized_command})
    policy = load_risk_tier_policy(root=resolved_root)
    requires_confirmation = requires_operator_confirmation(
        risk["tier"],
        input_source,
        policy=policy,
    )
    confirmation_reason = "none"
    if requires_confirmation:
        if risk["tier"] == "high":
            confirmation_reason = "high_risk_requires_text_confirmation"
        elif risk["tier"] == "medium":
            confirmation_reason = "medium_risk_confirmation_required"
        else:
            confirmation_reason = "low_risk_auto_execute_disabled"

    return {
        "action_type": action_type,
        "risk_tier": risk["tier"],
        "requires_confirmation": requires_confirmation,
        "confirmation_reason": confirmation_reason,
        "allowed": True,
        "reason": risk["reason"],
    }
