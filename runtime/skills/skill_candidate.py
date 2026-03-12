#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import SkillCandidateRecord, TaskClass, new_id, now_iso


def skill_candidates_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "skill_candidates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _record_path(skill_candidate_id: str, *, root: Optional[Path] = None) -> Path:
    return skill_candidates_dir(root=root) / f"{skill_candidate_id}.json"


def _fingerprint(*parts: str) -> str:
    basis = "||".join(part.strip() for part in parts if part).strip()
    if not basis:
        return ""
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def save_skill_candidate(record: SkillCandidateRecord, *, root: Optional[Path] = None) -> SkillCandidateRecord:
    record.updated_at = now_iso()
    _record_path(record.skill_candidate_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_skill_candidate(skill_candidate_id: str, *, root: Optional[Path] = None) -> Optional[SkillCandidateRecord]:
    path = _record_path(skill_candidate_id, root=root)
    if not path.exists():
        return None
    try:
        return SkillCandidateRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def list_skill_candidates(*, root: Optional[Path] = None) -> list[SkillCandidateRecord]:
    rows: list[SkillCandidateRecord] = []
    for path in sorted(skill_candidates_dir(root=root).glob("*.json")):
        try:
            rows.append(SkillCandidateRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: (row.updated_at, row.created_at), reverse=True)
    return rows


def create_skill_candidate_from_failure(
    *,
    actor: str,
    lane: str,
    skill_name: str,
    failure_summary: str,
    description: str = "",
    task_class: str = TaskClass.GENERAL.value,
    source_task_id: Optional[str] = None,
    source_trace_id: Optional[str] = None,
    source_eval_result_id: Optional[str] = None,
    source_refs: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> SkillCandidateRecord:
    normalized_task_class = TaskClass.coerce(str(task_class or TaskClass.GENERAL.value).strip().lower(), default=TaskClass.GENERAL).value
    timestamp = now_iso()
    failure_fingerprint = _fingerprint(skill_name, failure_summary, normalized_task_class, source_task_id or "", source_trace_id or "")
    record = SkillCandidateRecord(
        skill_candidate_id=new_id("skillcand"),
        created_at=timestamp,
        updated_at=timestamp,
        actor=actor,
        lane=lane,
        skill_name=skill_name,
        description=description or failure_summary,
        status="candidate",
        source_task_id=source_task_id,
        source_trace_id=source_trace_id,
        source_eval_result_id=source_eval_result_id,
        failure_fingerprint=failure_fingerprint,
        task_classes=[normalized_task_class],
        review_status="pending",
        eval_status="pending",
        source_refs={
            "failure_summary": failure_summary,
            **dict(source_refs or {}),
        },
        metadata={
            "candidate_origin": "failure_driven_scaffold",
            "autopromotion_allowed": False,
            **dict(metadata or {}),
        },
    )
    return save_skill_candidate(record, root=root)


def build_skill_candidate_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    rows = list_skill_candidates(root=root)
    status_counts: dict[str, int] = {}
    review_status_counts: dict[str, int] = {}
    eval_status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row.status] = status_counts.get(row.status, 0) + 1
        review_status_counts[row.review_status] = review_status_counts.get(row.review_status, 0) + 1
        eval_status_counts[row.eval_status] = eval_status_counts.get(row.eval_status, 0) + 1
    return {
        "skill_candidate_count": len(rows),
        "skill_candidate_status_counts": status_counts,
        "skill_candidate_review_status_counts": review_status_counts,
        "skill_candidate_eval_status_counts": eval_status_counts,
        "latest_skill_candidate": rows[0].to_dict() if rows else None,
    }

