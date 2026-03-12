#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.degradation_policy import build_degradation_summary
from runtime.core.heartbeat_reports import build_node_health_summary
from runtime.core.task_lease import build_task_lease_summary
from runtime.skills.registry import build_skill_registry_summary
from runtime.skills.skill_store import list_skills


def approved_skill_scheduling_readiness(*, root: Optional[Path] = None) -> dict[str, Any]:
    skills = list_skills(root=root)
    schedule_ready = []
    blocked = []
    for row in skills:
        if row.status != "approved":
            blocked.append(
                {
                    "skill_id": row.skill_id,
                    "skill_name": row.skill_name,
                    "reason": f"status_{row.status}",
                }
            )
            continue
        schedule_ready.append(
            {
                "skill_id": row.skill_id,
                "skill_name": row.skill_name,
                "task_classes": list(row.task_classes),
                "allowed_backends": list(row.allowed_backends),
                "required_eval_profiles": list(row.required_eval_profiles),
            }
        )
    return {
        "approved_skill_count": len(skills),
        "schedule_ready_skill_count": len(schedule_ready),
        "blocked_skill_count": len(blocked),
        "schedule_ready_skills": schedule_ready[:10],
        "blocked_skills": blocked[:10],
        "approved_only_policy": True,
        "autopromotion_allowed": False,
    }


def list_overnight_schedule_ready_skills(*, root: Optional[Path] = None) -> list[dict[str, Any]]:
    readiness = approved_skill_scheduling_readiness(root=root)
    return [
        {
            **row,
            "approved_only": True,
            "candidate_excluded": True,
            "autopromotion_allowed": False,
        }
        for row in readiness["schedule_ready_skills"]
    ]


def build_overnight_skill_digest(*, root: Optional[Path] = None) -> dict[str, Any]:
    readiness = approved_skill_scheduling_readiness(root=root)
    registry_summary = build_skill_registry_summary(root=root)
    node_health = build_node_health_summary(root=root)
    degradation = build_degradation_summary(root=root)
    task_lease = build_task_lease_summary(root=root)
    overnight_ready = list_overnight_schedule_ready_skills(root=root)
    return {
        "approved_only_policy": True,
        "candidate_execution_enabled": False,
        "autopromotion_allowed": False,
        "live_execution_enabled": False,
        "schedule_ready_skill_count": readiness["schedule_ready_skill_count"],
        "excluded_skill_candidate_count": registry_summary["skill_candidate_summary"]["skill_candidate_count"],
        "approved_skill_count": registry_summary["approved_skill_count"],
        "schedule_ready_skills": overnight_ready[:10],
        "blocked_skills": readiness["blocked_skills"][:10],
        "node_health_summary": {
            "registered_node_count": node_health["registered_node_count"],
            "online_node_count": node_health["online_node_count"],
            "burst_online_count": node_health["burst_online_count"],
        },
        "degraded_posture_summary": {
            "active_degradation_mode_count": degradation.get("active_degradation_mode_count", 0),
            "operator_notification_required_event_count": degradation.get("operator_notification_required_event_count", 0),
            "latest_degradation_event": degradation.get("latest_degradation_event"),
        },
        "task_lease_summary": {
            "task_lease_count": task_lease["task_lease_count"],
            "active_task_lease_count": task_lease["active_task_lease_count"],
            "expired_task_lease_count": task_lease["expired_task_lease_count"],
            "requeued_task_lease_count": task_lease["requeued_task_lease_count"],
        },
        "notes": [
            "B2 readiness only. Overnight approved-skill execution remains disabled by default.",
            "Skill candidates are excluded from overnight scheduling and cannot run automatically.",
        ],
    }


def build_skill_scheduler_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    registry_summary = build_skill_registry_summary(root=root)
    readiness = approved_skill_scheduling_readiness(root=root)
    return {
        "registry_summary": registry_summary,
        "scheduler_readiness": readiness,
        "overnight_skill_digest": build_overnight_skill_digest(root=root),
        "live_execution_enabled": False,
        "notes": [
            "B1 scaffold only. Approved skills are durable and searchable, but no new automatic skill execution is enabled.",
            "Skill candidates remain review/eval gated and cannot be auto-promoted.",
        ],
    }
