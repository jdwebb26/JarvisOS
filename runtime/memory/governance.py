#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.controls.control_store import assert_control_allows
from runtime.core.models import MemoryCandidateRecord, MemoryRetrievalRecord, RecordLifecycleState, new_id, now_iso
from runtime.core.review_store import latest_review_for_task
from runtime.core.approval_store import latest_approval_for_task
from runtime.core.models import ApprovalStatus, ReviewStatus
from runtime.core.task_events import append_event, make_event
from runtime.core.task_store import load_task


MEMORY_BACKEND_ID = "memory_spine"


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def memory_candidates_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("memory_candidates", root=root)


def memory_retrievals_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("memory_retrievals", root=root)


def _record_path(folder: Path, record_id: str) -> Path:
    return folder / f"{record_id}.json"


def save_memory_candidate(record: MemoryCandidateRecord, *, root: Optional[Path] = None) -> MemoryCandidateRecord:
    record.updated_at = now_iso()
    _record_path(memory_candidates_dir(root), record.memory_candidate_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_memory_candidate(memory_candidate_id: str, *, root: Optional[Path] = None) -> Optional[MemoryCandidateRecord]:
    path = _record_path(memory_candidates_dir(root), memory_candidate_id)
    if not path.exists():
        return None
    return MemoryCandidateRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_memory_candidates(
    *,
    root: Optional[Path] = None,
    task_id: Optional[str] = None,
    memory_type: Optional[str] = None,
    source_artifact_id: Optional[str] = None,
    source_trace_id: Optional[str] = None,
    source_eval_result_id: Optional[str] = None,
) -> list[MemoryCandidateRecord]:
    rows: list[MemoryCandidateRecord] = []
    for path in memory_candidates_dir(root).glob("*.json"):
        try:
            row = MemoryCandidateRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if task_id and row.task_id != task_id:
            continue
        if memory_type and row.memory_type != memory_type:
            continue
        if source_artifact_id and source_artifact_id not in row.source_artifact_ids:
            continue
        if source_trace_id and source_trace_id not in row.source_trace_ids:
            continue
        if source_eval_result_id and source_eval_result_id not in row.source_eval_result_ids:
            continue
        rows.append(row)
    rows.sort(key=lambda row: (row.confidence_score, row.updated_at), reverse=True)
    return rows


def list_memory_candidates_for_task(task_id: str, *, root: Optional[Path] = None) -> list[MemoryCandidateRecord]:
    return list_memory_candidates(root=root, task_id=task_id)


def save_memory_retrieval(record: MemoryRetrievalRecord, *, root: Optional[Path] = None) -> MemoryRetrievalRecord:
    record.updated_at = now_iso()
    _record_path(memory_retrievals_dir(root), record.memory_retrieval_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def list_memory_retrievals(*, root: Optional[Path] = None, task_id: Optional[str] = None) -> list[MemoryRetrievalRecord]:
    rows: list[MemoryRetrievalRecord] = []
    for path in memory_retrievals_dir(root).glob("*.json"):
        try:
            row = MemoryRetrievalRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if task_id and row.task_id != task_id:
            continue
        rows.append(row)
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _assert_memory_promotion_allowed(*, memory_candidate: MemoryCandidateRecord, root: Path) -> None:
    task = load_task(memory_candidate.task_id, root=root)
    if task is None:
        raise ValueError(f"Task not found for memory candidate: {memory_candidate.task_id}")

    assert_control_allows(
        action="promote_artifact",
        root=root,
        task_id=memory_candidate.task_id,
        subsystem=memory_candidate.execution_backend or MEMORY_BACKEND_ID,
    )

    if task.review_required:
        review = latest_review_for_task(task.task_id, root=root)
        if review is None or review.status != ReviewStatus.APPROVED.value:
            raise ValueError(f"Memory candidate {memory_candidate.memory_candidate_id} cannot be promoted without approved review.")

    if task.approval_required:
        approval = latest_approval_for_task(task.task_id, root=root)
        if approval is None or approval.status != ApprovalStatus.APPROVED.value:
            raise ValueError(f"Memory candidate {memory_candidate.memory_candidate_id} cannot be promoted without approved approval.")


def promote_memory_candidate(
    *,
    memory_candidate_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    reason: str = "",
    confidence_score: Optional[float] = None,
) -> MemoryCandidateRecord:
    root_path = Path(root or ROOT).resolve()
    record = load_memory_candidate(memory_candidate_id, root=root_path)
    if record is None:
        raise ValueError(f"Memory candidate not found: {memory_candidate_id}")
    if record.superseded_by_memory_candidate_id:
        raise ValueError(f"Memory candidate {memory_candidate_id} is superseded and cannot be promoted.")
    if record.contradiction_status == "contradicted":
        raise ValueError(f"Memory candidate {memory_candidate_id} is contradicted and cannot be promoted.")

    _assert_memory_promotion_allowed(memory_candidate=record, root=root_path)

    record.lifecycle_state = RecordLifecycleState.PROMOTED.value
    record.decision_status = "promoted"
    record.decision_reason = reason
    record.decided_at = now_iso()
    record.decided_by = actor
    record.promoted_at = record.decided_at
    record.promoted_by = actor
    if confidence_score is not None:
        record.confidence_score = _clamp_confidence(confidence_score)
    save_memory_candidate(record, root=root_path)

    append_event(
        make_event(
            task_id=record.task_id,
            event_type="memory_candidate_promoted",
            actor=actor,
            lane=lane,
            summary=f"Memory candidate promoted: {record.memory_candidate_id}",
            from_lifecycle_state=RecordLifecycleState.CANDIDATE.value,
            to_lifecycle_state=RecordLifecycleState.PROMOTED.value,
            execution_backend=record.execution_backend,
            details=reason or record.summary,
        ),
        root=root_path,
    )
    return record


def reject_memory_candidate(
    *,
    memory_candidate_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    reason: str = "",
) -> MemoryCandidateRecord:
    root_path = Path(root or ROOT).resolve()
    record = load_memory_candidate(memory_candidate_id, root=root_path)
    if record is None:
        raise ValueError(f"Memory candidate not found: {memory_candidate_id}")

    previous_state = record.lifecycle_state
    record.lifecycle_state = RecordLifecycleState.DEMOTED.value
    record.decision_status = "rejected"
    record.decision_reason = reason
    record.decided_at = now_iso()
    record.decided_by = actor
    save_memory_candidate(record, root=root_path)

    append_event(
        make_event(
            task_id=record.task_id,
            event_type="memory_candidate_rejected",
            actor=actor,
            lane=lane,
            summary=f"Memory candidate rejected: {record.memory_candidate_id}",
            from_lifecycle_state=previous_state,
            to_lifecycle_state=RecordLifecycleState.DEMOTED.value,
            execution_backend=record.execution_backend,
            details=reason or record.summary,
        ),
        root=root_path,
    )
    return record


def supersede_memory_candidate(
    *,
    memory_candidate_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    reason: str = "",
    superseded_by_memory_candidate_id: Optional[str] = None,
) -> MemoryCandidateRecord:
    root_path = Path(root or ROOT).resolve()
    record = load_memory_candidate(memory_candidate_id, root=root_path)
    if record is None:
        raise ValueError(f"Memory candidate not found: {memory_candidate_id}")

    previous_state = record.lifecycle_state
    record.lifecycle_state = RecordLifecycleState.SUPERSEDED.value
    record.decision_status = "superseded"
    record.decision_reason = reason
    record.decided_at = now_iso()
    record.decided_by = actor
    record.contradiction_status = "contradicted"
    record.contradiction_reason = reason or "Superseded by newer memory candidate."
    record.contradicted_at = now_iso()
    record.contradicted_by = actor
    record.superseded_by_memory_candidate_id = superseded_by_memory_candidate_id
    save_memory_candidate(record, root=root_path)

    append_event(
        make_event(
            task_id=record.task_id,
            event_type="memory_candidate_superseded",
            actor=actor,
            lane=lane,
            summary=f"Memory candidate superseded: {record.memory_candidate_id}",
            from_lifecycle_state=previous_state,
            to_lifecycle_state=RecordLifecycleState.SUPERSEDED.value,
            execution_backend=record.execution_backend,
            details=reason or record.summary,
        ),
        root=root_path,
    )
    return record


def retrieve_memory(
    *,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    promoted_only: bool = True,
    task_id: Optional[str] = None,
    memory_type: Optional[str] = None,
    source_artifact_id: Optional[str] = None,
    source_trace_id: Optional[str] = None,
    source_eval_result_id: Optional[str] = None,
    include_contradicted: bool = False,
) -> dict:
    root_path = Path(root or ROOT).resolve()
    rows = list_memory_candidates(
        root=root_path,
        task_id=task_id,
        memory_type=memory_type,
        source_artifact_id=source_artifact_id,
        source_trace_id=source_trace_id,
        source_eval_result_id=source_eval_result_id,
    )

    filtered: list[MemoryCandidateRecord] = []
    for row in rows:
        if promoted_only and row.lifecycle_state != RecordLifecycleState.PROMOTED.value:
            continue
        if not include_contradicted and (
            row.contradiction_status == "contradicted" or row.superseded_by_memory_candidate_id
        ):
            continue
        filtered.append(row)

    retrieval = MemoryRetrievalRecord(
        memory_retrieval_id=new_id("memget"),
        created_at=now_iso(),
        updated_at=now_iso(),
        actor=actor,
        lane=lane,
        promoted_only=promoted_only,
        task_id=task_id,
        memory_type=memory_type,
        source_artifact_id=source_artifact_id,
        source_trace_id=source_trace_id,
        source_eval_result_id=source_eval_result_id,
        include_contradicted=include_contradicted,
        returned_memory_candidate_ids=[row.memory_candidate_id for row in filtered],
        result_count=len(filtered),
    )
    save_memory_retrieval(retrieval, root=root_path)

    return {
        "retrieval": retrieval.to_dict(),
        "items": [row.to_dict() for row in filtered],
    }
