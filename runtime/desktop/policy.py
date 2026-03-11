#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from runtime.core.risk_tier import evaluate_risk_tier


ROOT = Path(__file__).resolve().parents[2]

_LOW_RISK_ACTIONS = {"open_app", "focus_window", "open_path"}
_MEDIUM_RISK_ACTIONS = {"type_text", "click_target"}
_HIGH_RISK_ACTIONS = {"bounded_shell"}

_ACTION_TO_RISK_ACTION = {
    "open_app": "open_dashboard",
    "focus_window": "show_status",
    "open_path": "open_dashboard",
    "type_text": "type_into_field",
    "click_target": "trigger_bounded_workflow",
    "bounded_shell": "bounded_shell",
}


def evaluate_desktop_action(
    action_type: str,
    *,
    target_app: str = "",
    target_path: str = "",
    action_params: Optional[dict[str, Any]] = None,
    root=None,
) -> dict:
    del root
    normalized = (action_type or "").strip()
    context = {
        "target_app": target_app,
        "target_path": target_path,
        "action_params": dict(action_params or {}),
    }

    if normalized not in _ACTION_TO_RISK_ACTION:
        return {
            "allowed": False,
            "risk_tier": "high",
            "review_required": True,
            "reason": "unsupported_desktop_action",
        }

    risk = evaluate_risk_tier(
        _ACTION_TO_RISK_ACTION[normalized],
        "desktop_executor",
        context,
    )

    if normalized in _HIGH_RISK_ACTIONS:
        return {
            "allowed": True,
            "risk_tier": risk["tier"],
            "review_required": True,
            "reason": "desktop_high_risk_requires_review",
        }

    return {
        "allowed": True,
        "risk_tier": risk["tier"],
        "review_required": False,
        "reason": risk["reason"],
    }
