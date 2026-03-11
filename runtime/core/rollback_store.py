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

from runtime.core.artifact_store import demote_artifact, revoke_artifact
from runtime.controls.control_store import assert_control_allows
from runtime.core.models import (
    OutputDependencyRecord,
    RollbackProvenanceRecord,
    RollbackExecutionRecord,
    RollbackPlanRecord,
    RevocationImpactRecord,
    now_iso,
    new_id,
)
from runtime.core.provenance_store import save_rollback_provenance


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    root_path = Path(root or ROOT).resolve()
    path = root_path / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dependencies_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("output_dependencies", root=root)


def rollback_plans_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("rollback_plans", root=root)


def rollback_executions_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("rollback_executions", root=root)


def revocation_impacts_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("revocation_impacts", root=root)


def _path(folder: Path, record_id: str) -> Path:
    return folder / f"{record_id}.json"


def _save(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def save_output_dependency(record: OutputDependencyRecord, root: Optional[Path] = None) -> OutputDependencyRecord:
    record.updated_at = now_iso()
    _save(_path(output_dependencies_dir(root), record.output_dependency_id), record.to_dict())
    return record


def save_rollback_plan(record: RollbackPlanRecord, root: Optional[Path] = None) -> RollbackPlanRecord:
    record.updated_at = now_iso()
    _save(_path(rollback_plans_dir(root), record.rollback_plan_id), record.to_dict())
    return record


def save_rollback_execution(record: RollbackExecutionRecord, root: Optional[Path] = None) -> RollbackExecutionRecord:
    record.updated_at = now_iso()
    _save(_path(rollback_executions_dir(root), record.rollback_execution_id), record.to_dict())
    return record


def save_revocation_impact(record: RevocationImpactRecord, root: Optional[Path] = None) -> RevocationImpactRecord:
    record.updated_at = now_iso()
    _save(_path(revocation_impacts_dir(root), record.revocation_impact_id), record.to_dict())
    return record


def _load_rows(folder: Path, model) -> list:
    rows = []
    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(model.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def list_output_dependencies(root: Optional[Path] = None) -> list[OutputDependencyRecord]:
    return _load_rows(output_dependencies_dir(root), OutputDependencyRecord)


def list_rollback_plans(root: Optional[Path] = None) -> list[RollbackPlanRecord]:
    return _load_rows(rollback_plans_dir(root), RollbackPlanRecord)


def list_rollback_executions(root: Optional[Path] = None) -> list[RollbackExecutionRecord]:
    return _load_rows(rollback_executions_dir(root), RollbackExecutionRecord)


def list_revocation_impacts(root: Optional[Path] = None) -> list[RevocationImpactRecord]:
    return _load_rows(revocation_impacts_dir(root), RevocationImpactRecord)


def latest_rollback_execution(root: Optional[Path] = None) -> Optional[RollbackExecutionRecord]:
    rows = list_rollback_executions(root=root)
    return rows[0] if rows else None


def record_output_dependency(
    *,
    output_id: str,
    task_id: str,
    artifact_id: str,
    actor: str,
    lane: str,
    output_status: str,
    root: Optional[Path] = None,
) -> OutputDependencyRecord:
    existing = next(
        (row for row in list_output_dependencies(root=root) if row.output_id == output_id),
        None,
    )
    if existing is not None:
        existing.output_status = output_status
        return save_output_dependency(existing, root=root)
    return save_output_dependency(
        OutputDependencyRecord(
            output_dependency_id=new_id("odep"),
            output_id=output_id,
            task_id=task_id,
            artifact_id=artifact_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            output_status=output_status,
        ),
        root=root,
    )


def build_rollback_plan(
    *,
    artifact_id: str,
    task_id: str,
    actor: str,
    lane: str,
    action_kind: str,
    reason: str,
    root: Optional[Path] = None,
) -> RollbackPlanRecord:
    dependencies = [row for row in list_output_dependencies(root=root) if row.artifact_id == artifact_id]
    plan = save_rollback_plan(
        RollbackPlanRecord(
            rollback_plan_id=new_id("rbp"),
            task_id=task_id,
            artifact_id=artifact_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            action_kind=action_kind,
            reason=reason,
            affected_output_ids=[row.output_id for row in dependencies],
            affected_task_ids=sorted({row.task_id for row in dependencies}),
            status="planned",
        ),
        root=root,
    )
    save_rollback_provenance(
        RollbackProvenanceRecord(
            rollback_provenance_id=new_id("rbprov"),
            rollback_plan_id=plan.rollback_plan_id,
            rollback_execution_id=None,
            task_id=task_id,
            artifact_id=artifact_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            action_kind=action_kind,
            source_refs={"affected_output_ids": list(plan.affected_output_ids)},
            replay_input=plan.to_dict(),
        ),
        root=root,
    )
    return plan


def _record_impacts(
    *,
    rollback_execution_id: str,
    artifact_id: str,
    task_id: str,
    actor: str,
    lane: str,
    affected_output_ids: list[str],
    reason: str,
    root: Optional[Path] = None,
) -> list[RevocationImpactRecord]:
    impacts: list[RevocationImpactRecord] = []
    dependency_map = {row.output_id: row for row in list_output_dependencies(root=root)}
    for output_id in affected_output_ids:
        dep = dependency_map.get(output_id)
        impact = save_revocation_impact(
            RevocationImpactRecord(
                revocation_impact_id=new_id("imp"),
                rollback_execution_id=rollback_execution_id,
                artifact_id=artifact_id,
                task_id=task_id,
                created_at=now_iso(),
                updated_at=now_iso(),
                actor=actor,
                lane=lane,
                output_id=output_id,
                impacted_task_id=dep.task_id if dep else task_id,
                impact_kind="output_invalidated",
                impact_status="recorded",
                reason=reason,
            ),
            root=root,
        )
        impacts.append(impact)
    try:
        from runtime.memory.governance import list_memory_candidates

        for candidate in list_memory_candidates(root=root, task_id=task_id, source_artifact_id=artifact_id):
            impacts.append(
                save_revocation_impact(
                    RevocationImpactRecord(
                        revocation_impact_id=new_id("imp"),
                        rollback_execution_id=rollback_execution_id,
                        artifact_id=artifact_id,
                        task_id=task_id,
                        created_at=now_iso(),
                        updated_at=now_iso(),
                        actor=actor,
                        lane=lane,
                        impacted_task_id=candidate.task_id,
                        impacted_record_type="memory_candidate",
                        impacted_record_id=candidate.memory_candidate_id,
                        impact_kind="memory_eligibility_invalidated",
                        impact_status="recorded",
                        reason=reason,
                        source_ref=f"artifact:{artifact_id}",
                    ),
                    root=root,
                )
            )
    except Exception:
        pass
    try:
        from runtime.core.approval_store import list_approvals_for_task

        for approval in list_approvals_for_task(task_id, root=root):
            if approval.status != "pending":
                continue
            if approval.linked_artifact_ids and artifact_id not in approval.linked_artifact_ids:
                continue
            impacts.append(
                save_revocation_impact(
                    RevocationImpactRecord(
                        revocation_impact_id=new_id("imp"),
                        rollback_execution_id=rollback_execution_id,
                        artifact_id=artifact_id,
                        task_id=task_id,
                        created_at=now_iso(),
                        updated_at=now_iso(),
                        actor=actor,
                        lane=lane,
                        impacted_task_id=task_id,
                        impacted_record_type="approval",
                        impacted_record_id=approval.approval_id,
                        impact_kind="approval_in_flight_impacted",
                        impact_status="recorded",
                        reason=reason,
                        source_ref=f"approval:{approval.approval_id}",
                    ),
                    root=root,
                )
            )
    except Exception:
        pass
    try:
        from runtime.core.review_store import list_reviews_for_task

        for review in list_reviews_for_task(task_id, root=root):
            if review.status != "pending":
                continue
            if review.linked_artifact_ids and artifact_id not in review.linked_artifact_ids:
                continue
            impacts.append(
                save_revocation_impact(
                    RevocationImpactRecord(
                        revocation_impact_id=new_id("imp"),
                        rollback_execution_id=rollback_execution_id,
                        artifact_id=artifact_id,
                        task_id=task_id,
                        created_at=now_iso(),
                        updated_at=now_iso(),
                        actor=actor,
                        lane=lane,
                        impacted_task_id=task_id,
                        impacted_record_type="review",
                        impacted_record_id=review.review_id,
                        impact_kind="review_linked_candidate_impacted",
                        impact_status="recorded",
                        reason=reason,
                        source_ref=f"review:{review.review_id}",
                    ),
                    root=root,
                )
            )
    except Exception:
        pass
    try:
        from runtime.core.candidate_store import find_candidate_for_artifact

        candidate = find_candidate_for_artifact(artifact_id, root=root)
        if candidate is not None:
            impacts.append(
                save_revocation_impact(
                    RevocationImpactRecord(
                        revocation_impact_id=new_id("imp"),
                        rollback_execution_id=rollback_execution_id,
                        artifact_id=artifact_id,
                        task_id=task_id,
                        created_at=now_iso(),
                        updated_at=now_iso(),
                        actor=actor,
                        lane=lane,
                        impacted_task_id=task_id,
                        impacted_record_type="candidate",
                        impacted_record_id=candidate.candidate_id,
                        impact_kind="candidate_lifecycle_impacted",
                        impact_status="recorded",
                        reason=reason,
                        source_ref=f"candidate:{candidate.candidate_id}",
                    ),
                    root=root,
                )
            )
    except Exception:
        pass
    impacts.append(
        save_revocation_impact(
            RevocationImpactRecord(
                revocation_impact_id=new_id("imp"),
                rollback_execution_id=rollback_execution_id,
                artifact_id=artifact_id,
                task_id=task_id,
                created_at=now_iso(),
                updated_at=now_iso(),
                actor=actor,
                lane=lane,
                impacted_task_id=task_id,
                impacted_record_type="task",
                impacted_record_id=task_id,
                impact_kind="task_publish_readiness_invalidated",
                impact_status="recorded",
                reason=reason,
                source_ref=f"task:{task_id}",
            ),
            root=root,
        )
    )
    return impacts


def execute_rollback_plan(
    *,
    rollback_plan_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
) -> RollbackExecutionRecord:
    plan = next((row for row in list_rollback_plans(root=root) if row.rollback_plan_id == rollback_plan_id), None)
    if plan is None:
        raise ValueError(f"Rollback plan not found: {rollback_plan_id}")
    assert_control_allows(
        action="rollback_execute",
        root=root,
        task_id=plan.task_id,
        actor=actor,
        lane=lane,
    )
    if plan.action_kind == "revoke":
        artifact = revoke_artifact(
            artifact_id=plan.artifact_id,
            actor=actor,
            lane=lane,
            root=root,
            reason=plan.reason or f"Rollback execution {rollback_plan_id} revoked artifact.",
        )
    elif plan.action_kind == "demote":
        artifact = demote_artifact(
            artifact_id=plan.artifact_id,
            actor=actor,
            lane=lane,
            root=root,
        )
    else:
        raise ValueError(f"Unsupported rollback action kind: {plan.action_kind}")
    affected_output_ids = list(artifact.downstream_impacted_output_ids)
    execution = save_rollback_execution(
        RollbackExecutionRecord(
            rollback_execution_id=new_id("rbx"),
            rollback_plan_id=plan.rollback_plan_id,
            task_id=plan.task_id,
            artifact_id=plan.artifact_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            action_kind=plan.action_kind,
            status="completed",
            ok=True,
            reason=plan.reason,
            affected_output_ids=affected_output_ids,
            result_summary=f"Executed {plan.action_kind} rollback for artifact {plan.artifact_id}.",
        ),
        root=root,
    )
    impacts = _record_impacts(
        rollback_execution_id=execution.rollback_execution_id,
        artifact_id=plan.artifact_id,
        task_id=plan.task_id,
        actor=actor,
        lane=lane,
        affected_output_ids=affected_output_ids,
        reason=plan.reason,
        root=root,
    )
    execution.revocation_impact_ids = [row.revocation_impact_id for row in impacts]
    save_rollback_execution(execution, root=root)
    save_rollback_provenance(
        RollbackProvenanceRecord(
            rollback_provenance_id=new_id("rbprov"),
            rollback_plan_id=plan.rollback_plan_id,
            rollback_execution_id=execution.rollback_execution_id,
            task_id=plan.task_id,
            artifact_id=plan.artifact_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            action_kind=plan.action_kind,
            source_refs={
                "affected_output_ids": list(affected_output_ids),
                "revocation_impact_ids": list(execution.revocation_impact_ids),
            },
            replay_input=plan.to_dict(),
        ),
        root=root,
    )
    plan.status = "executed"
    save_rollback_plan(plan, root=root)
    return execution


def execute_artifact_revocation(
    *,
    artifact_id: str,
    task_id: str,
    actor: str,
    lane: str,
    reason: str,
    root: Optional[Path] = None,
) -> dict:
    plan = build_rollback_plan(
        artifact_id=artifact_id,
        task_id=task_id,
        actor=actor,
        lane=lane,
        action_kind="revoke",
        reason=reason,
        root=root,
    )
    execution = execute_rollback_plan(
        rollback_plan_id=plan.rollback_plan_id,
        actor=actor,
        lane=lane,
        root=root,
    )
    return {"rollback_plan": plan.to_dict(), "rollback_execution": execution.to_dict()}


def build_rollback_summary(root: Optional[Path] = None) -> dict:
    plans = list_rollback_plans(root=root)
    executions = list_rollback_executions(root=root)
    impacts = list_revocation_impacts(root=root)
    return {
        "rollback_plan_count": len(plans),
        "rollback_execution_count": len(executions),
        "revocation_impact_count": len(impacts),
        "latest_rollback_plan": plans[0].to_dict() if plans else None,
        "latest_rollback_execution": executions[0].to_dict() if executions else None,
        "latest_revocation_impact": impacts[0].to_dict() if impacts else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show rollback/revocation execution summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_rollback_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
