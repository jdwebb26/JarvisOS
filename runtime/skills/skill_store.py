#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import ApprovedSkillRecord, now_iso
from runtime.core.models import new_id


def skills_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "skills"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _record_path(skill_id: str, *, root: Optional[Path] = None) -> Path:
    return skills_dir(root=root) / f"{skill_id}.json"


def create_skill(
    *,
    actor: str,
    lane: str,
    skill_name: str,
    description: str = "",
    task_classes: Optional[list[str]] = None,
    allowed_backends: Optional[list[str]] = None,
    required_eval_profiles: Optional[list[str]] = None,
    source_refs: Optional[dict] = None,
    metadata: Optional[dict] = None,
    root: Optional[Path] = None,
) -> ApprovedSkillRecord:
    timestamp = now_iso()
    record = ApprovedSkillRecord(
        skill_id=new_id("skill"),
        created_at=timestamp,
        updated_at=timestamp,
        actor=actor,
        lane=lane,
        skill_name=skill_name,
        description=description,
        status="approved",
        task_classes=list(task_classes or []),
        allowed_backends=list(allowed_backends or []),
        required_eval_profiles=list(required_eval_profiles or []),
        source_refs=dict(source_refs or {}),
        metadata={"autopromotion_allowed": False, **dict(metadata or {})},
    )
    return save_skill(record, root=root)


def save_skill(record: ApprovedSkillRecord, *, root: Optional[Path] = None) -> ApprovedSkillRecord:
    record.updated_at = now_iso()
    _record_path(record.skill_id, root=root).write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return record


def load_skill(skill_id: str, *, root: Optional[Path] = None) -> Optional[ApprovedSkillRecord]:
    path = _record_path(skill_id, root=root)
    if not path.exists():
        return None
    try:
        return ApprovedSkillRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def list_skills(*, root: Optional[Path] = None) -> list[ApprovedSkillRecord]:
    rows: list[ApprovedSkillRecord] = []
    for path in sorted(skills_dir(root=root).glob("*.json")):
        try:
            rows.append(ApprovedSkillRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: (row.updated_at, row.created_at), reverse=True)
    return rows
