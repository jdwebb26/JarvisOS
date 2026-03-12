#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


def build_skill_scheduler_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    registry_summary = build_skill_registry_summary(root=root)
    readiness = approved_skill_scheduling_readiness(root=root)
    return {
        "registry_summary": registry_summary,
        "scheduler_readiness": readiness,
        "live_execution_enabled": False,
        "notes": [
            "B1 scaffold only. Approved skills are durable and searchable, but no new automatic skill execution is enabled.",
            "Skill candidates remain review/eval gated and cannot be auto-promoted.",
        ],
    }

