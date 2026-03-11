from pathlib import Path

from runtime.core.approval_sessions import (
    build_approval_session_summary,
    ensure_approval_session,
    list_approval_contexts,
    list_approval_sessions,
    list_resume_tokens,
)
from runtime.core.approval_store import record_approval_decision, request_approval
from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.output_store import load_output, publish_artifact
from runtime.core.rollback_store import (
    build_rollback_summary,
    execute_artifact_revocation,
    list_output_dependencies,
    list_revocation_impacts,
    list_rollback_executions,
    list_rollback_plans,
)
from runtime.core.routing import route_task_intent
from runtime.core.subsystem_contracts import build_subsystem_contract_summary, ensure_default_subsystem_contracts
from runtime.core.task_runtime import load_task, save_task
from runtime.core.task_store import create_task
from runtime.core.artifact_store import write_text_artifact
from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from scripts.operator_handoff_pack import build_operator_handoff_pack


def _make_task(
    root: Path,
    *,
    task_id: str,
    approval_required: bool = False,
) -> TaskRecord:
    route = route_task_intent(
        task_id=task_id,
        normalized_request="deploy live service" if approval_required else "general work",
        task_type="deploy" if approval_required else "general",
        risk_level="high_stakes" if approval_required else "normal",
        priority="high" if approval_required else "normal",
        actor="tester",
        lane="tests",
        root=root,
    )
    return create_task(
        TaskRecord(
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            source_lane="tests",
            source_channel="tests",
            source_message_id=f"{task_id}_msg",
            source_user="tester",
            trigger_type="explicit_task_colon",
            raw_request=f"task: {task_id}",
            normalized_request=task_id,
            status=TaskStatus.RUNNING.value,
            task_type="deploy" if approval_required else "general",
            risk_level="high_stakes" if approval_required else "normal",
            priority="high" if approval_required else "normal",
            assigned_model=route["decision"]["selected_model_name"],
            execution_backend=route["decision"]["selected_execution_backend"],
            backend_metadata={"routing": {
                "routing_request_id": route["request"]["routing_request_id"],
                "routing_decision_id": route["decision"]["routing_decision_id"],
                "provider_id": route["decision"]["selected_provider_id"],
                "model_name": route["decision"]["selected_model_name"],
            }},
            approval_required=approval_required,
        ),
        root=root,
    )


def test_explicit_rollback_revocation_execution_tracks_dependencies(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_rollback_case")
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Promoted artifact",
        summary="summary",
        content="body",
        actor="operator",
        lane="artifacts",
        root=tmp_path,
    )
    published = publish_artifact(
        task_id=task.task_id,
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="outputs",
        root=tmp_path,
    )

    result = execute_artifact_revocation(
        artifact_id=artifact["artifact_id"],
        task_id=task.task_id,
        actor="anton",
        lane="review",
        root=tmp_path,
        reason="source invalidated",
    )

    output = load_output(published["output_id"], root=tmp_path)
    rollback_summary = build_rollback_summary(root=tmp_path)
    assert output.status == "revoked"
    assert len(list_output_dependencies(root=tmp_path)) == 1
    assert len(list_rollback_plans(root=tmp_path)) == 1
    assert len(list_rollback_executions(root=tmp_path)) == 1
    impacts = list_revocation_impacts(root=tmp_path)
    assert len(impacts) == 2
    assert {impact.impact_kind for impact in impacts} == {
        "output_invalidated",
        "task_publish_readiness_invalidated",
    }
    assert result["rollback_execution"]["affected_output_ids"] == [published["output_id"]]
    assert rollback_summary["latest_rollback_execution"]["artifact_id"] == artifact["artifact_id"]


def test_resumable_approval_session_tracks_context_and_resume_token(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_approval_session", approval_required=True)
    task.final_outcome = "candidate_ready_for_live_apply"
    save_task(tmp_path, task)
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Approval candidate",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
        execution_backend=task.execution_backend,
    )

    approval = request_approval(
        task_id=task.task_id,
        approval_type="deploy",
        requested_by="tester",
        requested_reviewer="anton",
        lane="review",
        summary="approval required",
        root=tmp_path,
    )

    sessions = list_approval_sessions(root=tmp_path)
    contexts = list_approval_contexts(root=tmp_path)
    tokens = list_resume_tokens(root=tmp_path)
    assert len(sessions) == 1
    assert len(contexts) == 1
    assert len(tokens) == 1
    assert sessions[0].latest_checkpoint_id == approval.resumable_checkpoint_id
    assert sessions[0].linked_artifact_ids == [artifact["artifact_id"]]
    assert tokens[0].token_ref.startswith(f"resume:{approval.approval_id}:")

    record_approval_decision(
        approval_id=approval.approval_id,
        decision="approved",
        actor="anton",
        lane="review",
        reason="approved",
        root=tmp_path,
    )
    session_summary = build_approval_session_summary(root=tmp_path)
    stored_task = load_task(tmp_path, task.task_id)
    assert session_summary["latest_approval_session"]["session_state"] == "resumed"
    assert stored_task.status == TaskStatus.READY_TO_SHIP.value


def test_subsystem_contract_scaffolding_persists_and_surfaces(tmp_path: Path):
    ensure_default_subsystem_contracts(tmp_path)
    summary = build_subsystem_contract_summary(tmp_path)
    assert summary["contract_count"] >= 6
    assert "planner" in summary["subsystem_kinds"]
    assert "provider_adapter" in summary["subsystem_kinds"]


def test_reporting_surfaces_rollback_approval_sessions_and_contracts(tmp_path: Path):
    ensure_default_subsystem_contracts(tmp_path)
    task = _make_task(tmp_path, task_id="task_reporting_core", approval_required=True)
    task.final_outcome = "candidate_ready_for_live_apply"
    save_task(tmp_path, task)
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Core report artifact",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
        execution_backend=task.execution_backend,
    )
    approval = request_approval(
        task_id=task.task_id,
        approval_type="deploy",
        requested_by="tester",
        requested_reviewer="anton",
        lane="review",
        summary="approval required",
        root=tmp_path,
    )
    record_approval_decision(
        approval_id=approval.approval_id,
        decision="approved",
        actor="anton",
        lane="review",
        reason="approved",
        root=tmp_path,
    )
    publish_artifact(
        task_id=task.task_id,
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="outputs",
        root=tmp_path,
    )
    execute_artifact_revocation(
        artifact_id=artifact["artifact_id"],
        task_id=task.task_id,
        actor="anton",
        lane="review",
        root=tmp_path,
        reason="post-publish invalidation",
    )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]

    assert status["rollback_summary"]["latest_rollback_execution"]["reason"] == "post-publish invalidation"
    assert status["approval_session_summary"]["latest_approval_session"]["approval_id"] == approval.approval_id
    assert status["subsystem_contract_summary"]["contract_count"] >= 6
    assert snapshot["rollback_summary"]["rollback_execution_count"] >= 1
    assert export_payload["counts"]["approval_sessions"] >= 1
    assert export_payload["counts"]["rollback_executions"] >= 1
    assert export_payload["counts"]["subsystem_contracts"] >= 6
    assert handoff["rollback_summary"]["latest_rollback_execution"]["artifact_id"] == artifact["artifact_id"]
    assert handoff["approval_session_summary"]["latest_approval_session"]["approval_id"] == approval.approval_id
    assert handoff["subsystem_contract_summary"]["contract_count"] >= 6
