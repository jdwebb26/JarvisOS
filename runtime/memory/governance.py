#!/usr/bin/env python3
from __future__ import annotations

import json
import argparse
import sys
import re
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.controls.control_store import assert_control_allows
from runtime.core.models import (
    ApprovalStatus,
    MemoryCandidateRecord,
    MemoryEntryRecord,
    MemoryEligibilityStatus,
    MemoryPromotionDecisionRecord,
    MemoryProvenanceRecord,
    MemoryRejectionDecisionRecord,
    MemoryRetrievalRecord,
    MemoryRevocationDecisionRecord,
    MemoryValidationRecord,
    RecordLifecycleState,
    ReviewStatus,
    new_id,
    now_iso,
)
from runtime.core.provenance_store import save_memory_provenance
from runtime.core.review_store import latest_review_for_task
from runtime.core.approval_store import latest_approval_for_task
from runtime.core.task_events import append_event, make_event
from runtime.core.task_store import load_task


MEMORY_BACKEND_ID = "memory_spine"
TOKEN_CHAR_RATIO = 4


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def memory_candidates_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("memory_candidates", root=root)


def memory_retrievals_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("memory_retrievals", root=root)


def memory_entries_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("memory_entries", root=root)


def memory_validations_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("memory_validations", root=root)


def memory_promotion_decisions_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("memory_promotion_decisions", root=root)


def memory_rejection_decisions_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("memory_rejection_decisions", root=root)


def memory_revocation_decisions_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("memory_revocation_decisions", root=root)


def _record_path(folder: Path, record_id: str) -> Path:
    return folder / f"{record_id}.json"


def save_memory_candidate(record: MemoryCandidateRecord, *, root: Optional[Path] = None) -> MemoryCandidateRecord:
    record.updated_at = now_iso()
    _record_path(memory_candidates_dir(root), record.memory_candidate_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def save_memory_entry(record: MemoryEntryRecord, *, root: Optional[Path] = None) -> MemoryEntryRecord:
    record.updated_at = now_iso()
    _record_path(memory_entries_dir(root), record.memory_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def save_memory_validation(record: MemoryValidationRecord, *, root: Optional[Path] = None) -> MemoryValidationRecord:
    record.updated_at = now_iso()
    _record_path(memory_validations_dir(root), record.memory_validation_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def save_memory_promotion_decision(
    record: MemoryPromotionDecisionRecord,
    *,
    root: Optional[Path] = None,
) -> MemoryPromotionDecisionRecord:
    record.updated_at = now_iso()
    _record_path(memory_promotion_decisions_dir(root), record.memory_promotion_decision_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def save_memory_rejection_decision(
    record: MemoryRejectionDecisionRecord,
    *,
    root: Optional[Path] = None,
) -> MemoryRejectionDecisionRecord:
    record.updated_at = now_iso()
    _record_path(memory_rejection_decisions_dir(root), record.memory_rejection_decision_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def save_memory_revocation_decision(
    record: MemoryRevocationDecisionRecord,
    *,
    root: Optional[Path] = None,
) -> MemoryRevocationDecisionRecord:
    record.updated_at = now_iso()
    _record_path(memory_revocation_decisions_dir(root), record.memory_revocation_decision_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_memory_candidate(memory_candidate_id: str, *, root: Optional[Path] = None) -> Optional[MemoryCandidateRecord]:
    path = _record_path(memory_candidates_dir(root), memory_candidate_id)
    if not path.exists():
        return None
    return MemoryCandidateRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def load_memory_entry(memory_id: str, *, root: Optional[Path] = None) -> Optional[MemoryEntryRecord]:
    path = _record_path(memory_entries_dir(root), memory_id)
    if not path.exists():
        return None
    return MemoryEntryRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def load_memory_entry_by_candidate_id(
    memory_candidate_id: str,
    *,
    root: Optional[Path] = None,
) -> Optional[MemoryEntryRecord]:
    for row in list_memory_entries(root=root):
        if row.memory_candidate_id == memory_candidate_id:
            return row
    return None


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


def list_memory_entries(
    *,
    root: Optional[Path] = None,
    task_id: Optional[str] = None,
    memory_class: Optional[str] = None,
    structural_type: Optional[str] = None,
) -> list[MemoryEntryRecord]:
    rows: list[MemoryEntryRecord] = []
    for path in memory_entries_dir(root).glob("*.json"):
        try:
            row = MemoryEntryRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if task_id and row.task_id != task_id:
            continue
        if memory_class and row.memory_class != memory_class:
            continue
        if structural_type and row.structural_type != structural_type:
            continue
        rows.append(row)
    rows.sort(key=lambda row: (row.confidence_score, row.updated_at), reverse=True)
    return rows


def list_memory_candidates_for_task(task_id: str, *, root: Optional[Path] = None) -> list[MemoryCandidateRecord]:
    return list_memory_candidates(root=root, task_id=task_id)


def list_memory_validations(*, root: Optional[Path] = None) -> list[MemoryValidationRecord]:
    rows: list[MemoryValidationRecord] = []
    for path in memory_validations_dir(root).glob("*.json"):
        try:
            rows.append(MemoryValidationRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def list_memory_promotion_decisions(*, root: Optional[Path] = None) -> list[MemoryPromotionDecisionRecord]:
    rows: list[MemoryPromotionDecisionRecord] = []
    for path in memory_promotion_decisions_dir(root).glob("*.json"):
        try:
            rows.append(MemoryPromotionDecisionRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def list_memory_rejection_decisions(*, root: Optional[Path] = None) -> list[MemoryRejectionDecisionRecord]:
    rows: list[MemoryRejectionDecisionRecord] = []
    for path in memory_rejection_decisions_dir(root).glob("*.json"):
        try:
            rows.append(MemoryRejectionDecisionRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def list_memory_revocation_decisions(*, root: Optional[Path] = None) -> list[MemoryRevocationDecisionRecord]:
    rows: list[MemoryRevocationDecisionRecord] = []
    for path in memory_revocation_decisions_dir(root).glob("*.json"):
        try:
            rows.append(MemoryRevocationDecisionRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


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


def _candidate_eligibility(*, memory_candidate: MemoryCandidateRecord, root: Path) -> tuple[str, str]:
    task = load_task(memory_candidate.task_id, root=root)
    if task is None:
        return MemoryEligibilityStatus.INELIGIBLE.value, f"Task not found for memory candidate: {memory_candidate.task_id}"

    if memory_candidate.superseded_by_memory_candidate_id or memory_candidate.contradiction_status == "contradicted":
        return MemoryEligibilityStatus.INELIGIBLE.value, "Memory candidate is contradicted or superseded."
    if memory_candidate.decision_status == "revoked":
        return MemoryEligibilityStatus.REVOKED_UPSTREAM.value, memory_candidate.decision_reason or "Memory candidate was revoked."
    if task.review_required:
        review = latest_review_for_task(task.task_id, root=root)
        if review is None or review.status != ReviewStatus.APPROVED.value:
            return MemoryEligibilityStatus.REVIEW_REQUIRED.value, "approved review required before memory promotion."
    if task.approval_required:
        approval = latest_approval_for_task(task.task_id, root=root)
        if approval is None or approval.status != ApprovalStatus.APPROVED.value:
            return MemoryEligibilityStatus.APPROVAL_REQUIRED.value, "approved approval required before memory promotion."
    return MemoryEligibilityStatus.ELIGIBLE.value, ""


def _derive_memory_class(record: MemoryCandidateRecord) -> str:
    explicit = (record.source_provenance_refs or {}).get("memory_class")
    if explicit:
        return str(explicit)
    memory_type = record.memory_type.lower()
    if "preference" in memory_type:
        return "operator_preference_memory"
    if "decision" in memory_type:
        return "decision_memory"
    if "research" in memory_type or "claim" in memory_type or "eval" in memory_type:
        return "research_claim_memory"
    if "risk" in memory_type:
        return "risk_memory"
    return "artifact_memory"


def _derive_structural_type(record: MemoryCandidateRecord) -> str:
    explicit = (record.source_provenance_refs or {}).get("structural_type")
    if explicit:
        return str(explicit)
    memory_type = record.memory_type.lower()
    if "digest" in memory_type:
        return "episodic"
    if "procedure" in memory_type or "playbook" in memory_type:
        return "procedural"
    return "semantic"


def _derive_approval_requirement(task) -> str:
    if task.approval_required:
        return "approval_required"
    if task.review_required:
        return "review_required"
    return "none"


def _derive_review_state(*, task, candidate: MemoryCandidateRecord) -> str:
    if candidate.decision_status == "revoked":
        return "revoked"
    if candidate.superseded_by_memory_candidate_id:
        return "superseded"
    if task.approval_required or task.review_required:
        return "approved"
    return "not_required"


def _build_memory_entry(*, candidate: MemoryCandidateRecord, task, actor: str, lane: str) -> MemoryEntryRecord:
    ts = candidate.promoted_at or now_iso()
    return MemoryEntryRecord(
        memory_id=new_id("ment"),
        memory_candidate_id=candidate.memory_candidate_id,
        task_id=candidate.task_id,
        created_at=ts,
        updated_at=ts,
        actor=actor,
        lane=lane,
        memory_class=_derive_memory_class(candidate),
        structural_type=_derive_structural_type(candidate),
        source_refs={
            "artifact_ids": list(candidate.source_artifact_ids),
            "trace_ids": list(candidate.source_trace_ids),
            "eval_result_ids": list(candidate.source_eval_result_ids),
            "candidate_ids": list(candidate.source_candidate_ids),
            "output_ids": list(candidate.source_output_ids),
            "task_event_ids": list(candidate.source_task_event_ids),
            "provenance_refs": dict(candidate.source_provenance_refs),
        },
        approval_requirement=_derive_approval_requirement(task),
        confidence_score=candidate.confidence_score,
        confidence_decay_days=int((candidate.source_provenance_refs or {}).get("confidence_decay_days", 30)),
        last_retrieved_at=None,
        contradiction_check={
            "status": candidate.contradiction_status,
            "reason": candidate.contradiction_reason,
            "contradicted_at": candidate.contradicted_at,
            "contradicted_by": candidate.contradicted_by,
        },
        superseded_by=candidate.superseded_by_memory_candidate_id,
        review_state=_derive_review_state(task=task, candidate=candidate),
        memory_type=candidate.memory_type,
        title=candidate.title,
        summary=candidate.summary,
        content=candidate.content,
        lifecycle_state=RecordLifecycleState.PROMOTED.value,
        execution_backend=candidate.execution_backend or MEMORY_BACKEND_ID,
    )


def _upsert_memory_entry_for_candidate(
    *,
    candidate: MemoryCandidateRecord,
    actor: str,
    lane: str,
    root: Path,
) -> MemoryEntryRecord:
    task = load_task(candidate.task_id, root=root)
    if task is None:
        raise ValueError(f"Task not found for memory candidate: {candidate.task_id}")
    record = load_memory_entry_by_candidate_id(candidate.memory_candidate_id, root=root)
    if record is None:
        record = _build_memory_entry(candidate=candidate, task=task, actor=actor, lane=lane)
    else:
        record.actor = actor
        record.lane = lane
        record.memory_class = _derive_memory_class(candidate)
        record.structural_type = _derive_structural_type(candidate)
        record.source_refs = {
            "artifact_ids": list(candidate.source_artifact_ids),
            "trace_ids": list(candidate.source_trace_ids),
            "eval_result_ids": list(candidate.source_eval_result_ids),
            "candidate_ids": list(candidate.source_candidate_ids),
            "output_ids": list(candidate.source_output_ids),
            "task_event_ids": list(candidate.source_task_event_ids),
            "provenance_refs": dict(candidate.source_provenance_refs),
        }
        record.approval_requirement = _derive_approval_requirement(task)
        record.confidence_score = candidate.confidence_score
        record.confidence_decay_days = int((candidate.source_provenance_refs or {}).get("confidence_decay_days", 30))
        record.contradiction_check = {
            "status": candidate.contradiction_status,
            "reason": candidate.contradiction_reason,
            "contradicted_at": candidate.contradicted_at,
            "contradicted_by": candidate.contradicted_by,
        }
        record.superseded_by = candidate.superseded_by_memory_candidate_id
        record.review_state = _derive_review_state(task=task, candidate=candidate)
        record.memory_type = candidate.memory_type
        record.title = candidate.title
        record.summary = candidate.summary
        record.content = candidate.content
        record.lifecycle_state = candidate.lifecycle_state
        record.execution_backend = candidate.execution_backend or MEMORY_BACKEND_ID
    return save_memory_entry(record, root=root)


def record_memory_validation(
    *,
    memory_candidate_id: str,
    task_id: str,
    actor: str,
    lane: str,
    validator_kind: str,
    status: str,
    summary: str,
    details: str = "",
    evidence_refs: Optional[dict] = None,
    root: Optional[Path] = None,
) -> MemoryValidationRecord:
    validation = save_memory_validation(
        MemoryValidationRecord(
            memory_validation_id=new_id("mval"),
            memory_candidate_id=memory_candidate_id,
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            validator_kind=validator_kind,
            status=status,
            summary=summary,
            details=details,
            evidence_refs=evidence_refs or {},
        ),
        root=root,
    )
    candidate = load_memory_candidate(memory_candidate_id, root=root)
    if candidate is not None:
        if validation.memory_validation_id not in candidate.validation_record_ids:
            candidate.validation_record_ids.append(validation.memory_validation_id)
        candidate.latest_validation_id = validation.memory_validation_id
        save_memory_candidate(candidate, root=root)
    return validation


def register_memory_candidate(
    *,
    record: MemoryCandidateRecord,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
) -> MemoryCandidateRecord:
    root_path = Path(root or ROOT).resolve()
    task = load_task(record.task_id, root=root_path)
    provider_id = ((task.backend_metadata if task else {}) or {}).get("routing", {}).get("provider_id")
    assert_control_allows(
        action="memory_write",
        root=root_path,
        task_id=record.task_id,
        subsystem=record.execution_backend or MEMORY_BACKEND_ID,
        provider_id=provider_id,
        actor=actor,
        lane=lane,
    )
    eligibility_status, eligibility_reason = _candidate_eligibility(memory_candidate=record, root=root_path)
    record.eligibility_status = eligibility_status
    record.eligibility_reason = eligibility_reason
    save_memory_candidate(record, root=root_path)
    save_memory_provenance(
        MemoryProvenanceRecord(
            memory_provenance_id=new_id("memprov"),
            memory_candidate_id=record.memory_candidate_id,
            task_id=record.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            memory_type=record.memory_type,
            decision_kind="candidate",
            source_refs={
                "source_artifact_ids": list(record.source_artifact_ids),
                "source_trace_ids": list(record.source_trace_ids),
                "source_eval_result_ids": list(record.source_eval_result_ids),
                "source_provenance_refs": dict(record.source_provenance_refs),
            },
            replay_input={
                "memory_candidate_id": record.memory_candidate_id,
                "task_id": record.task_id,
                "memory_type": record.memory_type,
            },
        ),
        root=root_path,
    )
    validation = record_memory_validation(
        memory_candidate_id=record.memory_candidate_id,
        task_id=record.task_id,
        actor=actor,
        lane=lane,
        validator_kind="memory_candidate_registration",
        status="passed" if eligibility_status == MemoryEligibilityStatus.ELIGIBLE.value else "pending",
        summary="Memory candidate registered under candidate-first discipline.",
        details=eligibility_reason or record.summary,
        evidence_refs={
            "source_artifact_ids": list(record.source_artifact_ids),
            "source_trace_ids": list(record.source_trace_ids),
            "source_eval_result_ids": list(record.source_eval_result_ids),
            "source_provenance_refs": dict(record.source_provenance_refs),
        },
        root=root_path,
    )
    record.latest_validation_id = validation.memory_validation_id
    if validation.memory_validation_id not in record.validation_record_ids:
        record.validation_record_ids.append(validation.memory_validation_id)
    save_memory_candidate(record, root=root_path)
    return record


def _assert_memory_promotion_allowed(*, memory_candidate: MemoryCandidateRecord, root: Path, actor: str, lane: str) -> None:
    task = load_task(memory_candidate.task_id, root=root)
    if task is None:
        raise ValueError(f"Task not found for memory candidate: {memory_candidate.task_id}")

    assert_control_allows(
        action="promote_memory",
        root=root,
        task_id=memory_candidate.task_id,
        subsystem=memory_candidate.execution_backend or MEMORY_BACKEND_ID,
        provider_id=((task.backend_metadata if task else {}) or {}).get("routing", {}).get("provider_id"),
        actor=actor,
        lane=lane,
    )
    eligibility_status, eligibility_reason = _candidate_eligibility(memory_candidate=memory_candidate, root=root)
    memory_candidate.eligibility_status = eligibility_status
    memory_candidate.eligibility_reason = eligibility_reason
    save_memory_candidate(memory_candidate, root=root)
    if eligibility_status != MemoryEligibilityStatus.ELIGIBLE.value:
        if eligibility_status == MemoryEligibilityStatus.REVIEW_REQUIRED.value:
            raise ValueError(
                f"Memory candidate {memory_candidate.memory_candidate_id} cannot be promoted without approved review."
            )
        if eligibility_status == MemoryEligibilityStatus.APPROVAL_REQUIRED.value:
            raise ValueError(
                f"Memory candidate {memory_candidate.memory_candidate_id} cannot be promoted without approved approval."
            )
        raise ValueError(f"Memory candidate {memory_candidate.memory_candidate_id} is not eligible for promotion: {eligibility_reason}")
    if memory_candidate.latest_validation_id is None:
        raise ValueError(f"Memory candidate {memory_candidate.memory_candidate_id} has no validation record.")


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

    _assert_memory_promotion_allowed(memory_candidate=record, root=root_path, actor=actor, lane=lane)

    record.lifecycle_state = RecordLifecycleState.PROMOTED.value
    record.decision_status = "promoted"
    record.decision_reason = reason
    record.decided_at = now_iso()
    record.decided_by = actor
    record.promoted_at = record.decided_at
    record.promoted_by = actor
    if confidence_score is not None:
        record.confidence_score = _clamp_confidence(confidence_score)
    decision = save_memory_promotion_decision(
        MemoryPromotionDecisionRecord(
            memory_promotion_decision_id=new_id("memprom"),
            memory_candidate_id=record.memory_candidate_id,
            task_id=record.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            reason=reason,
            validation_record_ids=list(record.validation_record_ids),
        ),
        root=root_path,
    )
    record.latest_promotion_decision_id = decision.memory_promotion_decision_id
    save_memory_candidate(record, root=root_path)
    _upsert_memory_entry_for_candidate(candidate=record, actor=actor, lane=lane, root=root_path)
    save_memory_provenance(
        MemoryProvenanceRecord(
            memory_provenance_id=new_id("memprov"),
            memory_candidate_id=record.memory_candidate_id,
            task_id=record.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            memory_type=record.memory_type,
            decision_kind="promotion",
            source_refs={"promotion_decision_id": decision.memory_promotion_decision_id},
            replay_input={"memory_candidate_id": record.memory_candidate_id, "task_id": record.task_id},
        ),
        root=root_path,
    )

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
    decision = save_memory_rejection_decision(
        MemoryRejectionDecisionRecord(
            memory_rejection_decision_id=new_id("memrej"),
            memory_candidate_id=record.memory_candidate_id,
            task_id=record.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            reason=reason,
        ),
        root=root_path,
    )
    record.latest_rejection_decision_id = decision.memory_rejection_decision_id
    save_memory_candidate(record, root=root_path)
    existing_entry = load_memory_entry_by_candidate_id(record.memory_candidate_id, root=root_path)
    if existing_entry is not None:
        existing_entry.review_state = "rejected"
        existing_entry.lifecycle_state = RecordLifecycleState.DEMOTED.value
        save_memory_entry(existing_entry, root=root_path)
    save_memory_provenance(
        MemoryProvenanceRecord(
            memory_provenance_id=new_id("memprov"),
            memory_candidate_id=record.memory_candidate_id,
            task_id=record.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            memory_type=record.memory_type,
            decision_kind="rejection",
            source_refs={"rejection_decision_id": decision.memory_rejection_decision_id},
            replay_input={"memory_candidate_id": record.memory_candidate_id, "task_id": record.task_id},
        ),
        root=root_path,
    )

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
    existing_entry = load_memory_entry_by_candidate_id(record.memory_candidate_id, root=root_path)
    if existing_entry is not None:
        existing_entry.superseded_by = superseded_by_memory_candidate_id
        existing_entry.contradiction_check = {
            "status": record.contradiction_status,
            "reason": record.contradiction_reason,
            "contradicted_at": record.contradicted_at,
            "contradicted_by": record.contradicted_by,
        }
        existing_entry.review_state = "superseded"
        existing_entry.lifecycle_state = RecordLifecycleState.SUPERSEDED.value
        save_memory_entry(existing_entry, root=root_path)

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


def revoke_memory_candidates_for_artifact(
    *,
    artifact_id: str,
    task_id: str,
    actor: str,
    lane: str,
    reason: str,
    root: Optional[Path] = None,
) -> list[MemoryCandidateRecord]:
    root_path = Path(root or ROOT).resolve()
    impacted: list[MemoryCandidateRecord] = []
    for record in list_memory_candidates(root=root_path, task_id=task_id, source_artifact_id=artifact_id):
        if record.decision_status in {"rejected", "revoked"}:
            continue
        previous_state = record.lifecycle_state
        record.eligibility_status = MemoryEligibilityStatus.REVOKED_UPSTREAM.value
        record.eligibility_reason = reason
        record.decision_status = "revoked"
        record.decision_reason = reason
        record.decided_at = now_iso()
        record.decided_by = actor
        record.lifecycle_state = RecordLifecycleState.DEMOTED.value
        decision = save_memory_revocation_decision(
            MemoryRevocationDecisionRecord(
                memory_revocation_decision_id=new_id("memrev"),
                memory_candidate_id=record.memory_candidate_id,
                task_id=record.task_id,
                created_at=now_iso(),
                updated_at=now_iso(),
                actor=actor,
                lane=lane,
                reason=reason,
                trigger_ref=f"artifact:{artifact_id}",
            ),
            root=root_path,
        )
        record.latest_revocation_decision_id = decision.memory_revocation_decision_id
        save_memory_candidate(record, root=root_path)
        existing_entry = load_memory_entry_by_candidate_id(record.memory_candidate_id, root=root_path)
        if existing_entry is not None:
            existing_entry.review_state = "revoked"
            existing_entry.lifecycle_state = RecordLifecycleState.DEMOTED.value
            existing_entry.contradiction_check = {
                "status": "revoked_upstream",
                "reason": reason,
                "contradicted_at": record.decided_at,
                "contradicted_by": actor,
            }
            save_memory_entry(existing_entry, root=root_path)
        save_memory_provenance(
            MemoryProvenanceRecord(
                memory_provenance_id=new_id("memprov"),
                memory_candidate_id=record.memory_candidate_id,
                task_id=record.task_id,
                created_at=now_iso(),
                updated_at=now_iso(),
                actor=actor,
                lane=lane,
                memory_type=record.memory_type,
                decision_kind="revocation",
                source_refs={
                    "revocation_decision_id": decision.memory_revocation_decision_id,
                    "trigger_ref": f"artifact:{artifact_id}",
                },
                replay_input={"memory_candidate_id": record.memory_candidate_id, "task_id": record.task_id},
            ),
            root=root_path,
        )
        append_event(
            make_event(
                task_id=record.task_id,
                event_type="memory_candidate_revoked",
                actor=actor,
                lane=lane,
                summary=f"Memory candidate revoked: {record.memory_candidate_id}",
                from_lifecycle_state=previous_state,
                to_lifecycle_state=RecordLifecycleState.DEMOTED.value,
                execution_backend=record.execution_backend,
                details=reason,
            ),
            root=root_path,
        )
        impacted.append(record)
    return impacted


def build_memory_governance_summary(*, root: Optional[Path] = None) -> dict:
    candidates = list_memory_candidates(root=root)
    entries = list_memory_entries(root=root)
    validations = list_memory_validations(root=root)
    promotions = list_memory_promotion_decisions(root=root)
    rejections = list_memory_rejection_decisions(root=root)
    revocations = list_memory_revocation_decisions(root=root)
    latest_event = None
    for kind, rows in (
        ("promotion", promotions),
        ("rejection", rejections),
        ("revocation", revocations),
    ):
        if rows and (latest_event is None or rows[0].updated_at > latest_event.get("updated_at", "")):
            latest_event = {"event_kind": kind, **rows[0].to_dict()}
    return {
        "memory_candidate_count": len(candidates),
        "memory_entry_count": len(entries),
        "memory_validation_count": len(validations),
        "memory_promotion_count": len(promotions),
        "memory_rejection_count": len(rejections),
        "memory_revocation_count": len(revocations),
        "latest_memory_candidate": candidates[0].to_dict() if candidates else None,
        "latest_memory_entry": entries[0].to_dict() if entries else None,
        "latest_memory_validation": validations[0].to_dict() if validations else None,
        "latest_memory_event": latest_event,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current memory governance summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_memory_governance_summary(root=Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


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
    for row in filtered:
        entry = load_memory_entry_by_candidate_id(row.memory_candidate_id, root=root_path)
        if entry is not None:
            entry.last_retrieved_at = retrieval.updated_at
            save_memory_entry(entry, root=root_path)

    return {
        "retrieval": retrieval.to_dict(),
        "items": [row.to_dict() for row in filtered],
    }


def _estimate_tokens(text: str) -> int:
    return max(1, (len(str(text or "")) + TOKEN_CHAR_RATIO - 1) // TOKEN_CHAR_RATIO)


def _score_memory_entry(*, entry: MemoryEntryRecord, query_terms: set[str], preferred_classes: set[str]) -> float:
    haystack = " ".join(
        [
            entry.memory_type,
            entry.memory_class,
            entry.structural_type,
            entry.title,
            entry.summary,
            entry.content,
        ]
    ).lower()
    term_hits = sum(1 for term in query_terms if term in haystack)
    class_bonus = 0.25 if entry.memory_class in preferred_classes else 0.0
    structure_bonus = 0.15 if entry.structural_type == "episodic" else 0.1
    return float(entry.confidence_score) + class_bonus + structure_bonus + term_hits * 0.2


def retrieve_memory_for_context(
    *,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    query_text: str,
    task_id: Optional[str] = None,
    retrieval_budget_tokens: int = 1200,
    episodic_limit: int = 4,
    semantic_limit: int = 4,
    promoted_only: bool = True,
    include_contradicted: bool = False,
) -> dict[str, object]:
    root_path = Path(root or ROOT).resolve()
    entries = list_memory_entries(root=root_path, task_id=task_id)
    query_terms = set(re.findall(r"[a-z0-9_./-]{3,}", str(query_text or "").lower()))
    filtered: list[MemoryEntryRecord] = []
    returned_candidate_ids: list[str] = []
    for entry in entries:
        if promoted_only and entry.lifecycle_state != RecordLifecycleState.PROMOTED.value:
            continue
        contradiction_status = str((entry.contradiction_check or {}).get("status") or "")
        if not include_contradicted and (contradiction_status == "contradicted" or entry.superseded_by):
            continue
        filtered.append(entry)
        if entry.memory_candidate_id:
            returned_candidate_ids.append(entry.memory_candidate_id)

    episodic_rows = [row for row in filtered if row.structural_type == "episodic"]
    semantic_rows = [row for row in filtered if row.structural_type != "episodic"]
    episodic_rows.sort(key=lambda row: (_score_memory_entry(entry=row, query_terms=query_terms, preferred_classes={"decision_memory", "artifact_memory"}), row.updated_at), reverse=True)
    semantic_rows.sort(key=lambda row: (_score_memory_entry(entry=row, query_terms=query_terms, preferred_classes={"operator_preference_memory", "risk_memory", "research_claim_memory"}), row.updated_at), reverse=True)

    budget_remaining = max(0, int(retrieval_budget_tokens))
    selected_episodic: list[MemoryEntryRecord] = []
    selected_semantic: list[MemoryEntryRecord] = []
    used_tokens = 0
    for bucket, limit, sink in (
        (episodic_rows, max(0, episodic_limit), selected_episodic),
        (semantic_rows, max(0, semantic_limit), selected_semantic),
    ):
        for row in bucket:
            if len(sink) >= limit:
                break
            entry_text = "\n".join(part for part in [row.title, row.summary, row.content] if part)
            entry_tokens = _estimate_tokens(entry_text)
            if sink and used_tokens + entry_tokens > retrieval_budget_tokens:
                continue
            if not sink and entry_tokens > retrieval_budget_tokens and retrieval_budget_tokens > 0:
                continue
            sink.append(row)
            used_tokens += entry_tokens
            budget_remaining = max(0, retrieval_budget_tokens - used_tokens)
            if budget_remaining <= 0:
                break
        if budget_remaining <= 0:
            break

    retrieval = MemoryRetrievalRecord(
        memory_retrieval_id=new_id("memget"),
        created_at=now_iso(),
        updated_at=now_iso(),
        actor=actor,
        lane=lane,
        promoted_only=promoted_only,
        task_id=task_id,
        query_text=query_text[:2000] or None,
        retrieval_scope="context_engine",
        retrieval_budget_tokens=max(0, int(retrieval_budget_tokens)),
        episodic_result_count=len(selected_episodic),
        semantic_result_count=len(selected_semantic),
        include_contradicted=include_contradicted,
        returned_memory_candidate_ids=[
            row.memory_candidate_id for row in [*selected_episodic, *selected_semantic] if row.memory_candidate_id
        ],
        result_count=len(selected_episodic) + len(selected_semantic),
    )
    save_memory_retrieval(retrieval, root=root_path)
    for row in [*selected_episodic, *selected_semantic]:
        row.last_retrieved_at = retrieval.updated_at
        save_memory_entry(row, root=root_path)

    return {
        "retrieval": retrieval.to_dict(),
        "episodic": [row.to_dict() for row in selected_episodic],
        "semantic": [row.to_dict() for row in selected_semantic],
        "used_tokens": used_tokens,
        "remaining_budget_tokens": budget_remaining,
    }


def write_session_memory_entry(
    *,
    actor: str,
    lane: str,
    memory_type: str,
    memory_class: str,
    structural_type: str,
    title: str,
    summary: str,
    content: str = "",
    confidence_score: float = 0.6,
    source_session_key: str = "",
    root: Optional[Path] = None,
) -> Optional[MemoryEntryRecord]:
    """Write a promoted memory entry derived from a live session, bypassing the full governance cycle.

    Used for session-derived facts (operator preferences, constraints) where there is no
    associated task. These entries are auto-promoted and eligible for context retrieval immediately.
    Deduplication: skips write if an existing promoted entry with the same title and memory_class exists.
    """
    title = title.strip()
    if not title:
        return None
    norm_title = title.lower()
    existing = list_memory_entries(root=root, memory_class=memory_class)
    for entry in existing:
        if entry.title.strip().lower() == norm_title:
            return None
    record = MemoryEntryRecord(
        memory_id=new_id("ment"),
        memory_candidate_id="",
        task_id="",
        created_at=now_iso(),
        updated_at=now_iso(),
        actor=actor,
        lane=lane,
        memory_class=memory_class,
        structural_type=structural_type,
        approval_requirement="none",
        confidence_score=confidence_score,
        review_state="not_required",
        memory_type=memory_type,
        title=title,
        summary=summary,
        content=content,
        lifecycle_state=RecordLifecycleState.PROMOTED.value,
        source_refs={"session_key": source_session_key, "source": "session_context"},
    )
    return save_memory_entry(record, root=root)
