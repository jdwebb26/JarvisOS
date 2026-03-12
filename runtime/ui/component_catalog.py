#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


TRUSTED_COMPONENT_CATALOG: dict[str, dict[str, Any]] = {
    "approval_card": {
        "required_props": {"title", "pending_count", "status"},
        "description": "Trusted approval/review summary card.",
    },
    "task_summary_card": {
        "required_props": {"title", "queued_count", "blocked_count", "ready_to_ship_count"},
        "description": "Trusted task summary card.",
    },
    "skill_readiness_card": {
        "required_props": {"title", "approved_skill_count", "schedule_ready_skill_count", "candidate_count", "approved_only_policy"},
        "description": "Trusted approved-skill readiness card.",
    },
    "degraded_state_card": {
        "required_props": {"title", "overall_status", "active_degradation_mode_count", "operator_notification_required_event_count"},
        "description": "Trusted degraded-state summary card.",
    },
}


def get_component_catalog() -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for key, value in TRUSTED_COMPONENT_CATALOG.items():
        row = dict(value)
        row["required_props"] = sorted(str(prop) for prop in value.get("required_props", set()))
        catalog[key] = row
    return catalog


def allowed_component_types() -> list[str]:
    return sorted(TRUSTED_COMPONENT_CATALOG)


def is_allowed_component_type(component_type: str) -> bool:
    return component_type in TRUSTED_COMPONENT_CATALOG


def validate_component_against_catalog(component: dict[str, Any]) -> list[str]:
    component_type = str(component.get("component_type") or "")
    if not is_allowed_component_type(component_type):
        return [f"unknown_component_type:{component_type or 'missing'}"]
    props = component.get("props", {})
    if not isinstance(props, dict):
        return ["component_props_not_dict"]
    required = set(TRUSTED_COMPONENT_CATALOG[component_type]["required_props"])
    missing = sorted(prop for prop in required if prop not in props)
    return [f"missing_required_prop:{name}" for name in missing]
