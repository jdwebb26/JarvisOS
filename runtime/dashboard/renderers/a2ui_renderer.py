#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.ui.a2ui_schema import new_component, new_view, validate_view_payload
from runtime.ui.component_catalog import get_component_catalog, validate_component_against_catalog


def ui_views_dir(root: Path) -> Path:
    path = root / "state" / "ui_views"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _approval_view(source_payload: dict[str, Any]) -> dict[str, Any]:
    counts = dict(source_payload.get("counts") or {})
    return new_view(
        "approval_card_view",
        title="Approvals",
        view_type="operator_card",
        components=[
            new_component(
                "approval_card",
                component_id="approval_card_primary",
                props={
                    "title": "Pending Reviews And Approvals",
                    "pending_count": int(counts.get("pending_reviews", 0)) + int(counts.get("pending_approvals", 0)),
                    "pending_reviews": int(counts.get("pending_reviews", 0)),
                    "pending_approvals": int(counts.get("pending_approvals", 0)),
                    "status": "attention" if int(counts.get("pending_reviews", 0)) + int(counts.get("pending_approvals", 0)) else "clear",
                },
            )
        ],
        metadata={"scaffolding_only": True, "trusted_only": True},
    )


def _task_summary_view(source_payload: dict[str, Any]) -> dict[str, Any]:
    counts = dict(source_payload.get("counts") or {})
    return new_view(
        "task_summary_card_view",
        title="Task Summary",
        view_type="operator_card",
        components=[
            new_component(
                "task_summary_card",
                component_id="task_summary_card_primary",
                props={
                    "title": "Task Posture",
                    "queued_count": int(counts.get("queued", 0)),
                    "blocked_count": int(counts.get("blocked", 0)),
                    "ready_to_ship_count": int(counts.get("ready_to_ship", 0)),
                    "running_count": int(counts.get("running", 0)),
                },
            )
        ],
        metadata={"scaffolding_only": True, "trusted_only": True},
    )


def _skill_readiness_view(source_payload: dict[str, Any]) -> dict[str, Any]:
    summary = dict(source_payload.get("skill_scheduler_summary") or {})
    registry = dict(summary.get("registry_summary") or {})
    readiness = dict(summary.get("scheduler_readiness") or {})
    candidate_summary = dict(registry.get("skill_candidate_summary") or {})
    return new_view(
        "skill_readiness_card_view",
        title="Skill Readiness",
        view_type="operator_card",
        components=[
            new_component(
                "skill_readiness_card",
                component_id="skill_readiness_card_primary",
                props={
                    "title": "Approved Skill Readiness",
                    "approved_skill_count": int(registry.get("approved_skill_count", 0)),
                    "schedule_ready_skill_count": int(readiness.get("schedule_ready_skill_count", 0)),
                    "candidate_count": int(candidate_summary.get("skill_candidate_count", 0)),
                    "approved_only_policy": bool(readiness.get("approved_only_policy", True)),
                    "autopromotion_allowed": bool(readiness.get("autopromotion_allowed", False)),
                },
            )
        ],
        metadata={"scaffolding_only": True, "trusted_only": True},
    )


def _degraded_state_view(source_payload: dict[str, Any]) -> dict[str, Any]:
    degraded = dict(source_payload.get("degradation_summary") or {})
    heartbeat = dict(source_payload.get("heartbeat_summary") or {})
    return new_view(
        "degraded_state_card_view",
        title="Degraded State",
        view_type="operator_card",
        components=[
            new_component(
                "degraded_state_card",
                component_id="degraded_state_card_primary",
                props={
                    "title": "Degraded Runtime Posture",
                    "overall_status": str(heartbeat.get("overall_heartbeat_status") or "unknown"),
                    "active_degradation_mode_count": int(degraded.get("active_degradation_mode_count", 0)),
                    "operator_notification_required_event_count": int(degraded.get("operator_notification_required_event_count", 0)),
                },
            )
        ],
        metadata={"scaffolding_only": True, "trusted_only": True},
    )


def build_operator_views(source_payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _approval_view(source_payload),
        _task_summary_view(source_payload),
        _skill_readiness_view(source_payload),
        _degraded_state_view(source_payload),
    ]


def render_declarative_view(view: dict[str, Any]) -> dict[str, Any]:
    errors = validate_view_payload(view)
    catalog = get_component_catalog()
    rendered_components: list[dict[str, Any]] = []
    for component in list(view.get("components") or []):
        component_errors = validate_component_against_catalog(component)
        if component_errors:
            errors.extend(component_errors)
            continue
        component_type = component["component_type"]
        rendered_components.append(
            {
                "component_id": component["component_id"],
                "component_type": component_type,
                "props": dict(component.get("props") or {}),
                "catalog_entry": catalog[component_type],
            }
        )
    return {
        "view_id": view.get("view_id"),
        "title": view.get("title"),
        "view_type": view.get("view_type"),
        "trusted_only": True,
        "render_status": "rendered" if not errors else "rejected",
        "components": rendered_components if not errors else [],
        "errors": errors,
        "metadata": dict(view.get("metadata") or {}),
    }


def render_operator_views(*, root: Path, source_name: str, source_payload: dict[str, Any]) -> dict[str, Any]:
    views = build_operator_views(source_payload)
    rendered = [render_declarative_view(view) for view in views]
    payload = {
        "source_name": source_name,
        "trusted_only": True,
        "catalog_component_types": sorted(get_component_catalog()),
        "views": rendered,
        "rendered_view_count": sum(1 for view in rendered if view["render_status"] == "rendered"),
        "rejected_view_count": sum(1 for view in rendered if view["render_status"] == "rejected"),
    }
    out_path = ui_views_dir(root) / f"{source_name}_views.json"
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload

