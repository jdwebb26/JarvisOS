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

from runtime.controls.control_store import assert_control_allows, build_control_summary, list_blocked_actions
from runtime.core.candidate_store import find_candidate_for_artifact, list_candidates
from runtime.core.degradation_policy import record_degradation_event
from runtime.core.models import ApprovalStatus, ControlBlockedActionRecord, ControlRunState, RecordLifecycleState, ReviewStatus, new_id, now_iso
from runtime.core.task_store import load_task, task_dependency_summary
from runtime.controls.control_store import save_blocked_action


def _provider_id_for_task(task) -> Optional[str]:
    routing = ((task.backend_metadata if task else {}) or {}).get("routing", {})
    return routing.get("provider_id")


class GovernanceBlockedError(ValueError):
    def __init__(self, message: str, *, blocked: dict[str, object]) -> None:
        super().__init__(message)
        self.blocked = blocked


def build_governance_blocked_contract(record: ControlBlockedActionRecord) -> dict[str, object]:
    return {
        "blocked_action_id": record.blocked_action_id,
        "action": record.action,
        "task_id": record.task_id,
        "provider_id": record.provider_id,
        "subsystem": record.subsystem,
        "reason": record.reason,
        "metadata": dict(record.metadata or {}),
    }


def latest_governance_block_for_task_action(
    *,
    task_id: str,
    action: str,
    root: Optional[Path] = None,
) -> Optional[dict[str, object]]:
    for record in list_blocked_actions(root=root):
        if record.task_id != task_id or record.action != action:
            continue
        return build_governance_blocked_contract(record)
    return None


def raise_structured_governance_block_if_available(
    *,
    task_id: str,
    action: str,
    reason: str,
    root: Optional[Path] = None,
) -> None:
    blocked = latest_governance_block_for_task_action(task_id=task_id, action=action, root=root)
    if blocked is not None and str(blocked.get("reason") or "") == reason:
        raise GovernanceBlockedError(reason, blocked=blocked)
    raise ValueError(reason)


def _record_governance_block(
    *,
    action: str,
    task_id: str,
    actor: str,
    lane: str,
    provider_id: Optional[str],
    execution_backend: Optional[str],
    reason: str,
    metadata: Optional[dict] = None,
    root: Optional[Path] = None,
) -> None:
    metadata_payload = dict(metadata or {})
    policy_block_kind = str(metadata_payload.get("policy_block_kind") or "")
    degradation_subsystem = ""
    if policy_block_kind == "review_gate_uncleared":
        degradation_subsystem = "reviewer_lane"
    elif policy_block_kind == "approval_gate_uncleared":
        degradation_subsystem = "auditor_lane"
    if degradation_subsystem:
        record_degradation_event(
            subsystem=degradation_subsystem,
            actor=actor,
            lane=lane,
            task_id=task_id,
            failure_category=policy_block_kind,
            reason=reason,
            source_refs={
                **metadata_payload,
                "blocked_action_kind": action,
                "execution_backend": execution_backend,
                "provider_id": provider_id,
                "security_posture_reduced": False,
            },
            status="applied",
            root=root,
        )
    save_blocked_action(
        ControlBlockedActionRecord(
            blocked_action_id=new_id("ctlblk"),
            created_at=now_iso(),
            action=action,
            task_id=task_id,
            subsystem=execution_backend,
            provider_id=provider_id,
            actor=actor,
            lane=lane,
            effective_status=ControlRunState.ACTIVE.value,
            reason=reason,
            metadata=metadata_payload,
        ),
        root=root,
    )
    raise ValueError(reason)


def _assert_review_and_approval_gates_cleared(
    *,
    action: str,
    task,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
) -> None:
    provider_id = _provider_id_for_task(task)
    execution_backend = task.execution_backend or lane

    if task.review_required:
        from runtime.core.review_store import latest_review_for_task

        latest_review = latest_review_for_task(task.task_id, root=root)
        if latest_review is None:
            _record_governance_block(
                action=action,
                task_id=task.task_id,
                actor=actor,
                lane=lane,
                provider_id=provider_id,
                execution_backend=execution_backend,
                reason="Review-required output cannot be promoted or published without an approved review record.",
                metadata={
                    "policy_block_kind": "review_gate_uncleared",
                    "review_required": True,
                    "latest_review_id": None,
                    "latest_review_status": None,
                },
                root=root,
            )
        if latest_review.status != ReviewStatus.APPROVED.value:
            _record_governance_block(
                action=action,
                task_id=task.task_id,
                actor=actor,
                lane=lane,
                provider_id=provider_id,
                execution_backend=execution_backend,
                reason=(
                    "Review-required output cannot be promoted or published while the reviewer lane is unavailable "
                    f"or uncleared: latest_review_status={latest_review.status}."
                ),
                metadata={
                    "policy_block_kind": "review_gate_uncleared",
                    "review_required": True,
                    "latest_review_id": latest_review.review_id,
                    "latest_review_status": latest_review.status,
                    "reviewer_role": latest_review.reviewer_role,
                },
                root=root,
            )

    if task.approval_required:
        from runtime.core.approval_store import latest_approval_for_task

        latest_approval = latest_approval_for_task(task.task_id, root=root)
        if latest_approval is None:
            _record_governance_block(
                action=action,
                task_id=task.task_id,
                actor=actor,
                lane=lane,
                provider_id=provider_id,
                execution_backend=execution_backend,
                reason="Approval-required output cannot be promoted or published without an approved approval record.",
                metadata={
                    "policy_block_kind": "approval_gate_uncleared",
                    "approval_required": True,
                    "latest_approval_id": None,
                    "latest_approval_status": None,
                },
                root=root,
            )
        if latest_approval.status != ApprovalStatus.APPROVED.value:
            _record_governance_block(
                action=action,
                task_id=task.task_id,
                actor=actor,
                lane=lane,
                provider_id=provider_id,
                execution_backend=execution_backend,
                reason=(
                    "Approval-required output cannot be promoted or published while the auditor lane is unavailable "
                    f"or uncleared: latest_approval_status={latest_approval.status}."
                ),
                metadata={
                    "policy_block_kind": "approval_gate_uncleared",
                    "approval_required": True,
                    "latest_approval_id": latest_approval.approval_id,
                    "latest_approval_status": latest_approval.status,
                    "requested_reviewer": latest_approval.requested_reviewer,
                },
                root=root,
            )


def assert_artifact_promotion_allowed(
    *,
    artifact,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
) -> dict:
    root_path = Path(root or ROOT).resolve()
    task = load_task(artifact.task_id, root=root_path)
    if task is None:
        raise ValueError(f"Task not found for artifact promotion: {artifact.task_id}")
    if artifact.lifecycle_state != RecordLifecycleState.CANDIDATE.value:
        raise ValueError(
            f"Artifact {artifact.artifact_id} is `{artifact.lifecycle_state}` and cannot be promoted from that state."
        )

    state = assert_control_allows(
        action="promote_artifact",
        root=root_path,
        task_id=artifact.task_id,
        subsystem=artifact.execution_backend or lane,
        provider_id=_provider_id_for_task(task),
        actor=actor,
        lane=lane,
    )
    candidate = find_candidate_for_artifact(artifact.artifact_id, root=root_path)
    if candidate is not None:
        if candidate.latest_revocation_id:
            raise ValueError(f"Artifact candidate {candidate.candidate_id} is revoked and cannot be promoted.")
        if candidate.latest_rejection_decision_id:
            raise ValueError(f"Artifact candidate {candidate.candidate_id} is rejected and cannot be promoted.")
        if candidate.latest_validation_id is None:
            raise ValueError(f"Artifact candidate {candidate.candidate_id} has no validation record.")
    _assert_review_and_approval_gates_cleared(
        action="promote_artifact",
        task=task,
        actor=actor,
        lane=lane,
        root=root_path,
    )
    dependency_state = task_dependency_summary(task.task_id, root=root_path)
    if dependency_state["hard_block"] or dependency_state["speculative_only"]:
        raise ValueError(str(dependency_state["reason"]))
    return {
        "control_state": state,
        "candidate_id": candidate.candidate_id if candidate else None,
        "policy_status": "eligible",
    }


def assert_artifact_publish_allowed(
    *,
    task_id: str,
    artifact_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
) -> dict:
    root_path = Path(root or ROOT).resolve()
    task = load_task(task_id, root=root_path)
    if task is None:
        raise ValueError(f"Task not found for output publish: {task_id}")
    if task.promoted_artifact_id and task.promoted_artifact_id != artifact_id:
        raise ValueError(
            f"Artifact {artifact_id} cannot be published because task {task_id} is currently promoted to {task.promoted_artifact_id}."
        )
    state = assert_control_allows(
        action="publish_output",
        root=root_path,
        task_id=task_id,
        subsystem=lane,
        provider_id=_provider_id_for_task(task),
        actor=actor,
        lane=lane,
    )
    _assert_review_and_approval_gates_cleared(
        action="publish_output",
        task=task,
        actor=actor,
        lane=lane,
        root=root_path,
    )
    dependency_state = task_dependency_summary(task.task_id, root=root_path)
    if dependency_state["hard_block"] or dependency_state["speculative_only"]:
        raise ValueError(str(dependency_state["reason"]))
    return {
        "control_state": state,
        "policy_status": "eligible",
    }


def build_promotion_governance_summary(*, root: Optional[Path] = None) -> dict:
    root_path = Path(root or ROOT).resolve()
    control_summary = build_control_summary(root=root_path)
    candidates = list_candidates(root=root_path)
    promoted = [row for row in candidates if row.lifecycle_state == RecordLifecycleState.PROMOTED.value]
    pending = [row for row in candidates if row.lifecycle_state == RecordLifecycleState.CANDIDATE.value]
    return {
        "candidate_count": len(candidates),
        "promotable_candidate_count": len(pending),
        "promoted_candidate_count": len(promoted),
        "effective_control_status": (control_summary.get("effective") or {}).get("effective_status"),
        "promotion_freeze_active": bool(((control_summary.get("effective") or {}).get("emergency_flags") or {}).get("promotion_freeze")),
        "memory_freeze_active": bool(((control_summary.get("effective") or {}).get("emergency_flags") or {}).get("memory_freeze")),
        "latest_blocked_action": control_summary.get("latest_blocked_action"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current promotion governance summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_promotion_governance_summary(root=Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
