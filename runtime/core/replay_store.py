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

from runtime.controls.control_store import control_blocks_action
from runtime.core.artifact_store import load_artifact
from runtime.core.candidate_store import find_candidate_for_artifact
from runtime.core.execution_contracts import (
    list_backend_execution_results,
    load_backend_execution_request,
)
from runtime.core.models import (
    ReplayExecutionRecord,
    ReplayPlanRecord,
    ReplayResultKind,
    ReplayResultRecord,
    RecordLifecycleState,
    new_id,
    now_iso,
)
from runtime.core.output_store import find_existing_output
from runtime.core.promotion_governance import assert_artifact_promotion_allowed, assert_artifact_publish_allowed
from runtime.core.rollback_store import list_rollback_plans
from runtime.core.routing import _choose_entry, ensure_default_routing_contracts, infer_required_capabilities, list_model_registry_entries
from runtime.core.task_store import load_task
from runtime.memory.governance import load_memory_candidate


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def replay_plans_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("replay_plans", root=root)


def replay_executions_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("replay_executions", root=root)


def replay_results_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("replay_results", root=root)


def _path(folder: Path, record_id: str) -> Path:
    return folder / f"{record_id}.json"


def _save(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def save_replay_plan(record: ReplayPlanRecord, *, root: Optional[Path] = None) -> ReplayPlanRecord:
    record.updated_at = now_iso()
    _save(_path(replay_plans_dir(root), record.replay_plan_id), record.to_dict())
    return record


def save_replay_execution(record: ReplayExecutionRecord, *, root: Optional[Path] = None) -> ReplayExecutionRecord:
    record.updated_at = now_iso()
    _save(_path(replay_executions_dir(root), record.replay_execution_id), record.to_dict())
    return record


def save_replay_result(record: ReplayResultRecord, *, root: Optional[Path] = None) -> ReplayResultRecord:
    record.updated_at = now_iso()
    _save(_path(replay_results_dir(root), record.replay_result_id), record.to_dict())
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


def list_replay_plans(root: Optional[Path] = None) -> list[ReplayPlanRecord]:
    return _load_rows(replay_plans_dir(root), ReplayPlanRecord)


def list_replay_executions(root: Optional[Path] = None) -> list[ReplayExecutionRecord]:
    return _load_rows(replay_executions_dir(root), ReplayExecutionRecord)


def list_replay_results(root: Optional[Path] = None) -> list[ReplayResultRecord]:
    return _load_rows(replay_results_dir(root), ReplayResultRecord)


def latest_replay_execution(root: Optional[Path] = None) -> Optional[ReplayExecutionRecord]:
    rows = list_replay_executions(root=root)
    return rows[0] if rows else None


def _find_routing_decision(routing_decision_id: str, root: Path) -> Optional[dict]:
    path = root / "state" / "routing_decisions" / f"{routing_decision_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _find_routing_request(routing_request_id: str, root: Path) -> Optional[dict]:
    path = root / "state" / "routing_requests" / f"{routing_request_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _find_output_dependency_for_artifact(artifact_id: str, root: Path) -> Optional[dict]:
    folder = root / "state" / "output_dependencies"
    for path in sorted(folder.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("artifact_id") == artifact_id:
            return row
    return None


def build_route_replay_plan(*, routing_decision_id: str, actor: str, lane: str, root: Optional[Path] = None) -> ReplayPlanRecord:
    root_path = Path(root or ROOT).resolve()
    decision = _find_routing_decision(routing_decision_id, root_path)
    if decision is None:
        return save_replay_plan(
            ReplayPlanRecord(
                replay_plan_id=new_id("rpl"),
                replay_kind="route",
                source_record_type="routing_decision",
                source_record_id=routing_decision_id,
                task_id=None,
                created_at=now_iso(),
                updated_at=now_iso(),
                actor=actor,
                lane=lane,
                replay_allowed=False,
                reason="missing_source",
            ),
            root=root_path,
        )
    request = _find_routing_request(decision["routing_request_id"], root_path)
    return save_replay_plan(
        ReplayPlanRecord(
            replay_plan_id=new_id("rpl"),
            replay_kind="route",
            source_record_type="routing_decision",
            source_record_id=routing_decision_id,
            task_id=decision.get("task_id"),
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            mode="plan_only",
            replay_allowed=request is not None,
            reason="" if request is not None else "missing_source",
            replay_input=request or {},
            source_refs={"routing_decision_id": routing_decision_id, "routing_request_id": decision["routing_request_id"]},
        ),
        root=root_path,
    )


def build_candidate_promotion_replay_plan(*, artifact_id: str, actor: str, lane: str, root: Optional[Path] = None) -> ReplayPlanRecord:
    root_path = Path(root or ROOT).resolve()
    candidate = find_candidate_for_artifact(artifact_id, root=root_path)
    artifact = load_artifact(artifact_id, root=root_path)
    return save_replay_plan(
        ReplayPlanRecord(
            replay_plan_id=new_id("rpl"),
            replay_kind="candidate_promotion",
            source_record_type="artifact",
            source_record_id=artifact_id,
            task_id=artifact.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            mode="plan_only",
            replay_allowed=candidate is not None,
            reason="" if candidate is not None else "missing_source",
            replay_input={"artifact_id": artifact_id, "task_id": artifact.task_id},
            source_refs={"candidate_id": candidate.candidate_id if candidate else None},
        ),
        root=root_path,
    )


def build_publish_replay_plan(*, artifact_id: str, task_id: str, actor: str, lane: str, root: Optional[Path] = None) -> ReplayPlanRecord:
    root_path = Path(root or ROOT).resolve()
    dependency = _find_output_dependency_for_artifact(artifact_id, root_path)
    return save_replay_plan(
        ReplayPlanRecord(
            replay_plan_id=new_id("rpl"),
            replay_kind="publish",
            source_record_type="artifact",
            source_record_id=artifact_id,
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            mode="plan_only",
            replay_allowed=dependency is not None,
            reason="" if dependency is not None else "missing_source",
            replay_input={"artifact_id": artifact_id, "task_id": task_id},
            source_refs={"output_dependency_id": dependency.get("output_dependency_id") if dependency else None},
        ),
        root=root_path,
    )


def build_rollback_replay_plan(*, rollback_plan_id: str, actor: str, lane: str, root: Optional[Path] = None) -> ReplayPlanRecord:
    root_path = Path(root or ROOT).resolve()
    plan = next((row for row in list_rollback_plans(root=root_path) if row.rollback_plan_id == rollback_plan_id), None)
    return save_replay_plan(
        ReplayPlanRecord(
            replay_plan_id=new_id("rpl"),
            replay_kind="rollback",
            source_record_type="rollback_plan",
            source_record_id=rollback_plan_id,
            task_id=plan.task_id if plan else None,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            mode="plan_only",
            replay_allowed=plan is not None,
            reason="" if plan is not None else "missing_source",
            replay_input=plan.to_dict() if plan is not None else {},
            source_refs={"artifact_id": plan.artifact_id if plan else None},
        ),
        root=root_path,
    )


def build_memory_promotion_replay_plan(*, memory_candidate_id: str, actor: str, lane: str, root: Optional[Path] = None) -> ReplayPlanRecord:
    root_path = Path(root or ROOT).resolve()
    memory_candidate = load_memory_candidate(memory_candidate_id, root=root_path)
    return save_replay_plan(
        ReplayPlanRecord(
            replay_plan_id=new_id("rpl"),
            replay_kind="memory_promotion",
            source_record_type="memory_candidate",
            source_record_id=memory_candidate_id,
            task_id=memory_candidate.task_id if memory_candidate else None,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            mode="plan_only",
            replay_allowed=memory_candidate is not None,
            reason="" if memory_candidate is not None else "missing_source",
            replay_input={"memory_candidate_id": memory_candidate_id},
            source_refs={"latest_validation_id": memory_candidate.latest_validation_id if memory_candidate else None},
        ),
        root=root_path,
    )


def build_backend_execution_replay_plan(
    *,
    backend_execution_request_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
) -> ReplayPlanRecord:
    root_path = Path(root or ROOT).resolve()
    request = load_backend_execution_request(backend_execution_request_id, root=root_path)
    return save_replay_plan(
        ReplayPlanRecord(
            replay_plan_id=new_id("rpl"),
            replay_kind="backend_execution",
            source_record_type="backend_execution_request",
            source_record_id=backend_execution_request_id,
            task_id=request.task_id if request else None,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            mode="plan_only",
            replay_allowed=request is not None,
            reason="" if request is not None else "missing_source",
            replay_input=request.to_dict() if request is not None else {},
            source_refs={"execution_backend": request.execution_backend if request else None},
        ),
        root=root_path,
    )


def execute_replay_plan(*, replay_plan_id: str, actor: str, lane: str, root: Optional[Path] = None) -> dict:
    root_path = Path(root or ROOT).resolve()
    plan = next((row for row in list_replay_plans(root=root_path) if row.replay_plan_id == replay_plan_id), None)
    if plan is None:
        raise ValueError(f"Replay plan not found: {replay_plan_id}")

    result_kind = ReplayResultKind.MATCH.value
    expected_snapshot: dict = {}
    observed_snapshot: dict = {}
    drift_fields: list[str] = []
    reason = plan.reason

    if not plan.replay_allowed:
        result_kind = ReplayResultKind.MISSING_SOURCE.value if plan.reason == "missing_source" else ReplayResultKind.INVALID_REPLAY.value
    elif plan.replay_kind == "route":
        request = plan.replay_input
        decision = _find_routing_decision(plan.source_record_id, root_path)
        blocked, message, _ = control_blocks_action(
            action="route_selection",
            root=root_path,
            task_id=plan.task_id,
            actor=actor,
            lane=lane,
        )
        if blocked:
            result_kind = ReplayResultKind.BLOCKED_BY_CONTROL.value
            reason = message
        else:
            ensure_default_routing_contracts(root_path)
            allowed_models = [row.model_name for row in list_model_registry_entries(root_path) if row.active]
            entry, profile, _ = _choose_entry(
                required_capabilities=request.get("required_capabilities") or infer_required_capabilities(
                    task_type=request["task_type"],
                    risk_level=request["risk_level"],
                    priority=request["priority"],
                    normalized_request=request["normalized_request"],
                ),
                task_type=request["task_type"],
                risk_level=request["risk_level"],
                allowed_models=allowed_models,
                root=root_path,
            )
            expected_snapshot = {
                "selected_model_name": decision.get("selected_model_name"),
                "selected_execution_backend": decision.get("selected_execution_backend"),
            }
            observed_snapshot = {
                "selected_model_name": entry.model_name,
                "selected_execution_backend": profile.preferred_execution_backend or entry.default_execution_backend,
            }
    elif plan.replay_kind == "candidate_promotion":
        artifact = load_artifact(plan.source_record_id, root=root_path)
        expected_snapshot = {"lifecycle_state": artifact.lifecycle_state}
        observed_snapshot = {"lifecycle_state": artifact.lifecycle_state}
        if artifact.lifecycle_state == RecordLifecycleState.PROMOTED.value:
            result_kind = ReplayResultKind.MATCH.value
        else:
            try:
                assert_artifact_promotion_allowed(artifact=artifact, actor=actor, lane=lane, root=root_path)
                result_kind = ReplayResultKind.DRIFT.value
            except ValueError as exc:
                if "Control state forbids" in str(exc):
                    result_kind = ReplayResultKind.BLOCKED_BY_CONTROL.value
                else:
                    result_kind = ReplayResultKind.INVALID_REPLAY.value
                reason = str(exc)
    elif plan.replay_kind == "publish":
        dependency = _find_output_dependency_for_artifact(plan.source_record_id, root_path)
        expected_snapshot = {"published_output_id": dependency.get("output_id") if dependency else None}
        try:
            assert_artifact_publish_allowed(
                task_id=plan.task_id or plan.replay_input["task_id"],
                artifact_id=plan.source_record_id,
                actor=actor,
                lane=lane,
                root=root_path,
            )
            existing = find_existing_output(
                task_id=plan.task_id or plan.replay_input["task_id"],
                artifact_id=plan.source_record_id,
                root=root_path,
            )
            observed_snapshot = {"published_output_id": existing.get("output_id") if existing else None}
            result_kind = ReplayResultKind.MATCH.value if existing else ReplayResultKind.DRIFT.value
        except ValueError as exc:
            if "Control state forbids" in str(exc):
                result_kind = ReplayResultKind.BLOCKED_BY_CONTROL.value
            else:
                result_kind = ReplayResultKind.INVALID_REPLAY.value
            reason = str(exc)
    elif plan.replay_kind == "rollback":
        replay_input = plan.replay_input
        blocked, message, _ = control_blocks_action(
            action="rollback_execute",
            root=root_path,
            task_id=plan.task_id,
            actor=actor,
            lane=lane,
        )
        if blocked:
            result_kind = ReplayResultKind.BLOCKED_BY_CONTROL.value
            reason = message
        else:
            artifact = load_artifact(replay_input["artifact_id"], root=root_path)
            expected_snapshot = {"action_kind": replay_input["action_kind"]}
            observed_snapshot = {"lifecycle_state": artifact.lifecycle_state}
            if artifact.revoked_at or artifact.lifecycle_state in {RecordLifecycleState.DEMOTED.value, RecordLifecycleState.SUPERSEDED.value}:
                result_kind = ReplayResultKind.MATCH.value
            else:
                result_kind = ReplayResultKind.DRIFT.value
    elif plan.replay_kind == "memory_promotion":
        candidate = load_memory_candidate(plan.source_record_id, root=root_path)
        if candidate is None:
            result_kind = ReplayResultKind.MISSING_SOURCE.value
            reason = "missing_source"
        else:
            expected_snapshot = {"decision_status": candidate.decision_status}
            observed_snapshot = {
                "decision_status": candidate.decision_status,
                "eligibility_status": candidate.eligibility_status,
            }
            if candidate.decision_status == "promoted":
                result_kind = ReplayResultKind.MATCH.value
            elif candidate.eligibility_status in {"review_required", "approval_required", "revoked_upstream", "ineligible"}:
                result_kind = ReplayResultKind.INVALID_REPLAY.value
                reason = candidate.eligibility_reason
            else:
                blocked, message, _ = control_blocks_action(
                    action="promote_memory",
                    root=root_path,
                    task_id=candidate.task_id,
                    subsystem=candidate.execution_backend,
                    actor=actor,
                    lane=lane,
                )
                if blocked:
                    result_kind = ReplayResultKind.BLOCKED_BY_CONTROL.value
                    reason = message
                else:
                    result_kind = ReplayResultKind.DRIFT.value
    elif plan.replay_kind == "backend_execution":
        request = load_backend_execution_request(plan.source_record_id, root=root_path)
        if request is None:
            result_kind = ReplayResultKind.MISSING_SOURCE.value
            reason = "missing_source"
        else:
            blocked, message, _ = control_blocks_action(
                action="task_progress",
                root=root_path,
                task_id=request.task_id,
                subsystem=request.execution_backend,
                provider_id=request.provider_id,
                actor=actor,
                lane=lane,
            )
            if blocked:
                result_kind = ReplayResultKind.BLOCKED_BY_CONTROL.value
                reason = message
            else:
                matching_results = [
                    row
                    for row in list_backend_execution_results(root=root_path)
                    if row.task_id == request.task_id
                    and row.request_kind == request.request_kind
                    and row.execution_backend == request.execution_backend
                ]
                latest_result = matching_results[0] if matching_results else None
                expected_snapshot = {
                    "provider_id": request.provider_id,
                    "model_name": request.model_name,
                    "execution_backend": request.execution_backend,
                    "request_kind": request.request_kind,
                    "status": latest_result.status if latest_result else None,
                }
                task = load_task(request.task_id, root=root_path)
                observed_snapshot = {
                    "provider_id": (((task.backend_metadata if task else {}) or {}).get("routing") or {}).get("provider_id"),
                    "model_name": task.assigned_model if task else None,
                    "execution_backend": task.execution_backend if task else None,
                    "request_kind": request.request_kind,
                    "status": latest_result.status if latest_result else None,
                }
                if latest_result is None:
                    result_kind = ReplayResultKind.DRIFT.value
                    reason = "No matching backend execution result currently exists."
                elif expected_snapshot == observed_snapshot:
                    result_kind = ReplayResultKind.MATCH.value
                else:
                    result_kind = ReplayResultKind.DRIFT.value
    else:
        result_kind = ReplayResultKind.INVALID_REPLAY.value
        reason = f"Unsupported replay kind: {plan.replay_kind}"

    for field in sorted(set(expected_snapshot) | set(observed_snapshot)):
        if expected_snapshot.get(field) != observed_snapshot.get(field):
            drift_fields.append(field)
    if result_kind == ReplayResultKind.MATCH.value and drift_fields:
        result_kind = ReplayResultKind.DRIFT.value
    result = save_replay_result(
        ReplayResultRecord(
            replay_result_id=new_id("rres"),
            replay_execution_id="pending",
            replay_kind=plan.replay_kind,
            source_record_id=plan.source_record_id,
            task_id=plan.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            result_kind=result_kind,
            expected_snapshot=expected_snapshot,
            observed_snapshot=observed_snapshot,
            drift_fields=drift_fields,
            reason=reason,
        ),
        root=root_path,
    )
    execution = save_replay_execution(
        ReplayExecutionRecord(
            replay_execution_id=new_id("rex"),
            replay_plan_id=plan.replay_plan_id,
            replay_kind=plan.replay_kind,
            task_id=plan.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            mode=plan.mode,
            ok=result_kind == ReplayResultKind.MATCH.value,
            source_record_id=plan.source_record_id,
            result_kind=result_kind,
            reason=reason,
            result_ref_id=result.replay_result_id,
        ),
        root=root_path,
    )
    result.replay_execution_id = execution.replay_execution_id
    save_replay_result(result, root=root_path)
    return {
        "replay_plan": plan.to_dict(),
        "replay_execution": execution.to_dict(),
        "replay_result": result.to_dict(),
    }


def build_replay_summary(root: Optional[Path] = None) -> dict:
    plans = list_replay_plans(root=root)
    executions = list_replay_executions(root=root)
    results = list_replay_results(root=root)
    drift_count = sum(1 for row in results if row.result_kind == ReplayResultKind.DRIFT.value)
    return {
        "replay_plan_count": len(plans),
        "replay_execution_count": len(executions),
        "replay_result_count": len(results),
        "replay_drift_count": drift_count,
        "latest_replay_plan": plans[0].to_dict() if plans else None,
        "latest_replay_execution": executions[0].to_dict() if executions else None,
        "latest_replay_result": results[0].to_dict() if results else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current replay summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_replay_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
