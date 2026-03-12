#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import ApprovedSkillRecord
from runtime.skills.skill_candidate import build_skill_candidate_summary
from runtime.skills.skill_store import list_skills


def search_skills(
    *,
    query: str = "",
    task_class: str = "",
    backend_runtime: str = "",
    root: Optional[Path] = None,
) -> list[ApprovedSkillRecord]:
    query_text = str(query or "").strip().lower()
    task_class_value = str(task_class or "").strip().lower()
    backend_runtime_value = str(backend_runtime or "").strip()
    rows: list[ApprovedSkillRecord] = []
    for row in list_skills(root=root):
        haystack = " ".join(
            [
                row.skill_name,
                row.description,
                " ".join(row.task_classes),
                " ".join(row.allowed_backends),
                " ".join(str(item) for item in (row.metadata or {}).get("tags", [])),
            ]
        ).lower()
        if query_text and query_text not in haystack:
            continue
        if task_class_value and task_class_value not in [item.lower() for item in row.task_classes]:
            continue
        if backend_runtime_value and backend_runtime_value not in row.allowed_backends:
            continue
        rows.append(row)
    return rows


def build_skill_registry_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    skills = list_skills(root=root)
    candidate_summary = build_skill_candidate_summary(root=root)
    task_class_counts: dict[str, int] = {}
    backend_counts: dict[str, int] = {}
    for row in skills:
        for task_class in row.task_classes:
            task_class_counts[task_class] = task_class_counts.get(task_class, 0) + 1
        for backend in row.allowed_backends:
            backend_counts[backend] = backend_counts.get(backend, 0) + 1
    return {
        "approved_skill_count": len(skills),
        "approved_skill_task_class_counts": task_class_counts,
        "approved_skill_backend_counts": backend_counts,
        "latest_approved_skill": skills[0].to_dict() if skills else None,
        "skill_candidate_summary": candidate_summary,
    }

