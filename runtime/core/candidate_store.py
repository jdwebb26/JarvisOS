#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import (
    CandidateRecord,
    CandidateRevocationRecord,
    PromotionDecisionRecord,
    RecordLifecycleState,
    RejectionDecisionRecord,
    ValidationRecord,
    new_id,
    now_iso,
)
from runtime.core.task_store import load_task


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    base = Path(root or ROOT).resolve()
    path = base / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def candidates_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("candidate_records", root=root)


def validations_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("candidate_validations", root=root)


def promotion_decisions_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("promotion_decisions", root=root)


def rejection_decisions_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("rejection_decisions", root=root)


def revocation_events_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("candidate_revocations", root=root)


def _record_path(folder: Path, record_id: str) -> Path:
    return folder / f"{record_id}.json"


def _save(folder: Path, record_id: str, payload: dict) -> dict:
    _record_path(folder, record_id).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _load_rows(folder: Path) -> list[dict]:
    rows: list[dict] = []
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return rows


def save_candidate(record: CandidateRecord, root: Optional[Path] = None) -> CandidateRecord:
    record.updated_at = now_iso()
    _save(candidates_dir(root), record.candidate_id, record.to_dict())
    return record


def save_validation(record: ValidationRecord, root: Optional[Path] = None) -> ValidationRecord:
    record.updated_at = now_iso()
    _save(validations_dir(root), record.validation_id, record.to_dict())
    return record


def save_promotion_decision(record: PromotionDecisionRecord, root: Optional[Path] = None) -> PromotionDecisionRecord:
    record.updated_at = now_iso()
    _save(promotion_decisions_dir(root), record.promotion_decision_id, record.to_dict())
    return record


def save_rejection_decision(record: RejectionDecisionRecord, root: Optional[Path] = None) -> RejectionDecisionRecord:
    record.updated_at = now_iso()
    _save(rejection_decisions_dir(root), record.rejection_decision_id, record.to_dict())
    return record


def save_candidate_revocation(record: CandidateRevocationRecord, root: Optional[Path] = None) -> CandidateRevocationRecord:
    record.updated_at = now_iso()
    _save(revocation_events_dir(root), record.revocation_id, record.to_dict())
    return record


def list_candidates(root: Optional[Path] = None) -> list[CandidateRecord]:
    rows = [CandidateRecord.from_dict(row) for row in _load_rows(candidates_dir(root))]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def latest_candidate(root: Optional[Path] = None) -> Optional[CandidateRecord]:
    rows = list_candidates(root=root)
    return rows[0] if rows else None


def load_candidate(candidate_id: str, root: Optional[Path] = None) -> Optional[CandidateRecord]:
    path = _record_path(candidates_dir(root), candidate_id)
    if not path.exists():
        return None
    return CandidateRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_validations(root: Optional[Path] = None) -> list[ValidationRecord]:
    rows = [ValidationRecord.from_dict(row) for row in _load_rows(validations_dir(root))]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def latest_validation(root: Optional[Path] = None) -> Optional[ValidationRecord]:
    rows = list_validations(root=root)
    return rows[0] if rows else None


def list_promotion_decisions(root: Optional[Path] = None) -> list[PromotionDecisionRecord]:
    rows = [PromotionDecisionRecord.from_dict(row) for row in _load_rows(promotion_decisions_dir(root))]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def latest_promotion_decision(root: Optional[Path] = None) -> Optional[PromotionDecisionRecord]:
    rows = list_promotion_decisions(root=root)
    return rows[0] if rows else None


def list_rejection_decisions(root: Optional[Path] = None) -> list[RejectionDecisionRecord]:
    rows = [RejectionDecisionRecord.from_dict(row) for row in _load_rows(rejection_decisions_dir(root))]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def latest_rejection_decision(root: Optional[Path] = None) -> Optional[RejectionDecisionRecord]:
    rows = list_rejection_decisions(root=root)
    return rows[0] if rows else None


def list_candidate_revocations(root: Optional[Path] = None) -> list[CandidateRevocationRecord]:
    rows = [CandidateRevocationRecord.from_dict(row) for row in _load_rows(revocation_events_dir(root))]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def latest_candidate_revocation(root: Optional[Path] = None) -> Optional[CandidateRevocationRecord]:
    rows = list_candidate_revocations(root=root)
    return rows[0] if rows else None


def find_candidate_for_artifact(artifact_id: str, root: Optional[Path] = None) -> Optional[CandidateRecord]:
    for candidate in list_candidates(root=root):
        if candidate.artifact_id == artifact_id:
            return candidate
    return None


def register_candidate_artifact(
    *,
    task_id: str,
    artifact_id: str,
    actor: str,
    lane: str,
    execution_backend: Optional[str],
    root: Optional[Path] = None,
) -> CandidateRecord:
    existing = find_candidate_for_artifact(artifact_id, root=root)
    if existing is not None:
        return existing

    task = load_task(task_id, root=root)
    routing = ((task.backend_metadata if task else {}) or {}).get("routing", {})
    candidate = save_candidate(
        CandidateRecord(
            candidate_id=new_id("cand"),
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            candidate_kind="artifact_candidate",
            source_record_type="artifact",
            source_record_id=artifact_id,
            artifact_id=artifact_id,
            execution_backend=execution_backend,
            provider_id=routing.get("provider_id"),
            model_name=routing.get("model_name") or (task.assigned_model if task else None),
            routing_decision_id=routing.get("routing_decision_id"),
            lifecycle_state=RecordLifecycleState.CANDIDATE.value,
        ),
        root=root,
    )
    validation = record_candidate_validation(
        candidate_id=candidate.candidate_id,
        task_id=task_id,
        actor=actor,
        lane=lane,
        validator_kind="candidate_registration",
        status="passed",
        summary="Candidate artifact registered.",
        details=f"Artifact {artifact_id} entered the candidate-first lifecycle.",
        evidence_refs={"artifact_id": artifact_id},
        root=root,
    )
    candidate.validation_record_ids.append(validation.validation_id)
    candidate.latest_validation_id = validation.validation_id
    save_candidate(candidate, root=root)
    return candidate


def record_candidate_validation(
    *,
    candidate_id: str,
    task_id: str,
    actor: str,
    lane: str,
    validator_kind: str,
    status: str,
    summary: str,
    details: str = "",
    evidence_refs: Optional[dict] = None,
    root: Optional[Path] = None,
) -> ValidationRecord:
    validation = save_validation(
        ValidationRecord(
            validation_id=new_id("val"),
            candidate_id=candidate_id,
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
    candidate = load_candidate(candidate_id, root=root)
    if candidate is not None:
        if validation.validation_id not in candidate.validation_record_ids:
            candidate.validation_record_ids.append(validation.validation_id)
        candidate.latest_validation_id = validation.validation_id
        save_candidate(candidate, root=root)
    return validation


def record_candidate_promotion(
    *,
    artifact_id: str,
    actor: str,
    lane: str,
    reason: str,
    provenance_ref: Optional[str],
    root: Optional[Path] = None,
) -> Optional[PromotionDecisionRecord]:
    candidate = find_candidate_for_artifact(artifact_id, root=root)
    if candidate is None:
        return None
    decision = save_promotion_decision(
        PromotionDecisionRecord(
            promotion_decision_id=new_id("prom"),
            candidate_id=candidate.candidate_id,
            task_id=candidate.task_id,
            artifact_id=artifact_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            decision="promoted",
            reason=reason,
            provenance_ref=provenance_ref,
            validation_record_ids=list(candidate.validation_record_ids),
        ),
        root=root,
    )
    candidate.lifecycle_state = RecordLifecycleState.PROMOTED.value
    candidate.latest_promotion_decision_id = decision.promotion_decision_id
    save_candidate(candidate, root=root)
    return decision


def record_candidate_rejection(
    *,
    artifact_id: str,
    actor: str,
    lane: str,
    reason: str,
    trigger_event: str,
    root: Optional[Path] = None,
) -> Optional[RejectionDecisionRecord]:
    candidate = find_candidate_for_artifact(artifact_id, root=root)
    if candidate is None:
        return None
    decision = save_rejection_decision(
        RejectionDecisionRecord(
            rejection_decision_id=new_id("rej"),
            candidate_id=candidate.candidate_id,
            task_id=candidate.task_id,
            artifact_id=artifact_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            decision="rejected",
            reason=reason,
            trigger_event=trigger_event,
        ),
        root=root,
    )
    candidate.lifecycle_state = RecordLifecycleState.DEMOTED.value
    candidate.latest_rejection_decision_id = decision.rejection_decision_id
    save_candidate(candidate, root=root)
    return decision


def record_candidate_revocation_hook(
    *,
    artifact_id: str,
    actor: str,
    lane: str,
    reason: str,
    impacted_output_ids: Optional[list[str]] = None,
    root: Optional[Path] = None,
) -> Optional[CandidateRevocationRecord]:
    candidate = find_candidate_for_artifact(artifact_id, root=root)
    if candidate is None:
        return None
    revocation = save_candidate_revocation(
        CandidateRevocationRecord(
            revocation_id=new_id("crev"),
            candidate_id=candidate.candidate_id,
            task_id=candidate.task_id,
            artifact_id=artifact_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            reason=reason,
            impacted_output_ids=list(impacted_output_ids or []),
            hook_status="recorded",
        ),
        root=root,
    )
    candidate.lifecycle_state = RecordLifecycleState.DEMOTED.value
    candidate.latest_revocation_id = revocation.revocation_id
    candidate.revoked_at = revocation.created_at
    candidate.revoked_by = actor
    candidate.revocation_reason = reason
    save_candidate(candidate, root=root)
    return revocation


def build_candidate_summary(root: Optional[Path] = None) -> dict:
    candidates = list_candidates(root=root)
    validations = list_validations(root=root)
    promotions = list_promotion_decisions(root=root)
    rejections = list_rejection_decisions(root=root)
    revocations = list_candidate_revocations(root=root)
    latest_candidate_record = candidates[0].to_dict() if candidates else None
    latest_validation_record = validations[0].to_dict() if validations else None
    latest_event = None
    if promotions:
        latest_event = {"event_kind": "promotion", **promotions[0].to_dict()}
    if rejections and ((latest_event is None) or rejections[0].updated_at > latest_event.get("updated_at", "")):
        latest_event = {"event_kind": "rejection", **rejections[0].to_dict()}
    if revocations and ((latest_event is None) or revocations[0].updated_at > latest_event.get("updated_at", "")):
        latest_event = {"event_kind": "revocation", **revocations[0].to_dict()}
    return {
        "candidate_count": len(candidates),
        "validation_count": len(validations),
        "promotion_count": len(promotions),
        "rejection_count": len(rejections),
        "revocation_count": len(revocations),
        "latest_candidate": latest_candidate_record,
        "latest_validation": latest_validation_record,
        "latest_event": latest_event,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the latest candidate-first scaffolding summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_candidate_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
