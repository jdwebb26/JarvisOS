from pathlib import Path

import pytest

from runtime.controls.control_store import set_emergency_control
from runtime.core.approval_store import request_approval
from runtime.core.artifact_store import load_artifact, promote_artifact, revoke_artifact, write_text_artifact
from runtime.core.intake import create_task_from_message
from runtime.core.models import ControlScopeType, RecordLifecycleState, TaskRecord, TaskStatus, now_iso
from runtime.core.output_store import publish_artifact
from runtime.core.review_store import request_review
from runtime.core.routing import route_task_intent
from runtime.core.status import build_status
from runtime.core.task_store import create_task
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.integrations.hermes_adapter import execute_hermes_task, load_hermes_result
from runtime.memory.governance import (
    list_memory_candidates_for_task,
    list_memory_promotion_decisions,
    list_memory_revocation_decisions,
    list_memory_validations,
    load_memory_candidate,
    promote_memory_candidate,
)
from runtime.ralph.consolidator import execute_consolidation
from runtime.evals.trace_store import replay_trace_to_eval
from runtime.core.rollback_store import execute_artifact_revocation
from scripts.operator_handoff_pack import build_operator_handoff_pack


def _make_task(root: Path, *, task_id: str, task_type: str = "research") -> TaskRecord:
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
            task_type=task_type,
            status=TaskStatus.RUNNING.value,
            execution_backend="qwen_executor",
        ),
        root=root,
    )


def _seed_eval_context(root: Path, task_id: str) -> str:
    hermes = execute_hermes_task(
        task_id=task_id,
        actor="tester",
        lane="hermes",
        root=root,
        transport=lambda _request: {
            "run_id": f"{task_id}_hermes_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Hermes candidate",
            "summary": "backend output",
            "content": "candidate body",
        },
    )
    stored_result = load_hermes_result(hermes["result"]["result_id"], root=root)
    replay_trace_to_eval(
        trace_id=stored_result["trace_id"],
        actor="tester",
        lane="eval",
        evaluator_kind="replay_check",
        objective="seed eval context",
        root=root,
    )
    return hermes["result"]["candidate_artifact_id"]


def test_execution_freeze_blocks_task_creation(tmp_path: Path):
    set_emergency_control(
        control_kind="execution_freeze",
        enabled=True,
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.GLOBAL.value,
        scope_id="global",
        reason="freeze normal execution",
        root=tmp_path,
    )

    with pytest.raises(ValueError, match="task creation"):
        create_task_from_message(
            text="task: write a general note",
            user="tester",
            lane="tests",
            channel="tests",
            message_id="msg_freeze",
            root=tmp_path,
        )


def test_promotion_freeze_blocks_promotion_and_publish(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_promotion_freeze")
    candidate = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Candidate",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
        execution_backend="qwen_executor",
    )
    promoted = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Promoted",
        summary="promoted",
        content="body",
        actor="operator",
        lane="artifacts",
        root=tmp_path,
    )

    set_emergency_control(
        control_kind="promotion_freeze",
        enabled=True,
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.GLOBAL.value,
        scope_id="global",
        reason="freeze promotion/publish",
        root=tmp_path,
    )

    from runtime.core.artifact_store import promote_artifact

    with pytest.raises(ValueError, match="artifact promotion"):
        promote_artifact(
            artifact_id=candidate["artifact_id"],
            actor="operator",
            lane="review",
            root=tmp_path,
        )

    with pytest.raises(ValueError, match="output publish"):
        publish_artifact(
            task_id=task.task_id,
            artifact_id=promoted["artifact_id"],
            actor="operator",
            lane="outputs",
            root=tmp_path,
        )


def test_provider_disable_blocks_qwen_routing_safely(tmp_path: Path):
    set_emergency_control(
        control_kind="provider_disable",
        enabled=True,
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.GLOBAL.value,
        scope_id="global",
        reason="disable qwen",
        target_provider_id="qwen",
        root=tmp_path,
    )

    with pytest.raises(ValueError, match="No active routing candidates"):
        route_task_intent(
            task_id="task_route_disabled",
            normalized_request="write a general note",
            task_type="general",
            risk_level="normal",
            priority="normal",
            actor="tester",
            lane="tests",
            root=tmp_path,
        )


def test_recovery_only_mode_blocks_normal_work_but_allows_rollback(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_recovery_only", task_type="general")
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Promoted",
        summary="ready",
        content="body",
        actor="operator",
        lane="artifacts",
        root=tmp_path,
    )
    publish_artifact(
        task_id=task.task_id,
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="outputs",
        root=tmp_path,
    )

    set_emergency_control(
        control_kind="recovery_only_mode",
        enabled=True,
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.GLOBAL.value,
        scope_id="global",
        reason="recovery only",
        root=tmp_path,
    )

    with pytest.raises(ValueError, match="task creation"):
        create_task_from_message(
            text="task: blocked during recovery",
            user="tester",
            lane="tests",
            channel="tests",
            message_id="msg_recovery_only",
            root=tmp_path,
        )

    result = execute_artifact_revocation(
        artifact_id=artifact["artifact_id"],
        task_id=task.task_id,
        actor="operator",
        lane="rollback",
        reason="recovery cleanup",
        root=tmp_path,
    )
    assert result["rollback_execution"]["ok"] is True


def test_memory_candidate_validation_promotion_and_upstream_revocation(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_memory_discipline")
    _seed_eval_context(tmp_path, task.task_id)
    execute_consolidation(task_id=task.task_id, actor="tester", lane="ralph", root=tmp_path)

    memory_candidates = list_memory_candidates_for_task(task.task_id, root=tmp_path)
    validations = list_memory_validations(root=tmp_path)
    assert memory_candidates
    assert validations
    assert memory_candidates[0].latest_validation_id is not None

    target = next(candidate for candidate in memory_candidates if candidate.source_artifact_ids)
    source_artifact_id = target.source_artifact_ids[0]

    promoted = promote_memory_candidate(
        memory_candidate_id=target.memory_candidate_id,
        actor="operator",
        lane="memory",
        root=tmp_path,
        reason="approved memory",
        confidence_score=0.9,
    )
    assert list_memory_promotion_decisions(root=tmp_path)

    revoke_artifact(
        artifact_id=source_artifact_id,
        actor="operator",
        lane="rollback",
        root=tmp_path,
        reason="source artifact revoked",
    )
    stored = load_memory_candidate(promoted.memory_candidate_id, root=tmp_path)
    revocations = list_memory_revocation_decisions(root=tmp_path)

    assert stored is not None
    assert stored.decision_status == "revoked"
    assert stored.eligibility_status == "revoked_upstream"
    assert stored.lifecycle_state == RecordLifecycleState.DEMOTED.value
    assert revocations


def test_review_required_promotion_is_blocked_until_review_clears_and_is_operator_visible(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_review_gate_hold")
    task.review_required = True
    from runtime.core.task_runtime import save_task
    save_task(tmp_path, task)
    candidate = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Candidate review gate",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
        execution_backend="qwen_executor",
    )

    request_review(
        task_id=task.task_id,
        reviewer_role="operator",
        requested_by="tester",
        lane="review",
        summary="review required before promotion",
        root=tmp_path,
    )

    with pytest.raises(ValueError, match="reviewer lane is unavailable or uncleared"):
        promote_artifact(
            artifact_id=candidate["artifact_id"],
            actor="operator",
            lane="review",
            root=tmp_path,
        )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]
    latest_blocked = status["control_state"]["latest_blocked_action"]

    assert latest_blocked is not None
    assert latest_blocked["action"] == "promote_artifact"
    assert latest_blocked["metadata"]["policy_block_kind"] == "review_gate_uncleared"
    assert latest_blocked["metadata"]["latest_review_status"] == "pending"
    assert "reviewer lane is unavailable or uncleared" in latest_blocked["reason"]
    assert snapshot["control_state"]["latest_blocked_action"]["metadata"]["policy_block_kind"] == "review_gate_uncleared"
    assert export_payload["promotion_governance_summary"]["latest_blocked_action"]["metadata"]["policy_block_kind"] == "review_gate_uncleared"
    assert handoff["promotion_governance_summary"]["latest_blocked_action"]["metadata"]["policy_block_kind"] == "review_gate_uncleared"


def test_non_review_required_promotion_behavior_is_unchanged(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_no_review_gate")
    candidate = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Candidate no review",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
        execution_backend="qwen_executor",
    )

    promoted = promote_artifact(
        artifact_id=candidate["artifact_id"],
        actor="operator",
        lane="review",
        root=tmp_path,
    )

    assert promoted.lifecycle_state == RecordLifecycleState.PROMOTED.value


def test_approval_required_promotion_is_blocked_until_approval_clears(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_approval_gate_hold")
    task.approval_required = True
    from runtime.core.task_runtime import save_task
    save_task(tmp_path, task)
    candidate = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Candidate approval gate",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
        execution_backend="qwen_executor",
    )

    request_approval(
        task_id=task.task_id,
        approval_type="deploy",
        requested_by="tester",
        requested_reviewer="anton",
        lane="review",
        summary="approval required before promotion",
        root=tmp_path,
    )

    with pytest.raises(ValueError, match="auditor lane is unavailable or uncleared"):
        promote_artifact(
            artifact_id=candidate["artifact_id"],
            actor="operator",
            lane="review",
            root=tmp_path,
        )

    status = build_status(tmp_path)
    latest_blocked = status["control_state"]["latest_blocked_action"]
    assert latest_blocked is not None
    assert latest_blocked["metadata"]["policy_block_kind"] == "approval_gate_uncleared"
    assert latest_blocked["metadata"]["latest_approval_status"] == "pending"


def test_reporting_surfaces_controls_memory_and_governance_summaries(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_reporting_core")
    _seed_eval_context(tmp_path, task.task_id)
    execute_consolidation(task_id=task.task_id, actor="tester", lane="ralph", root=tmp_path)
    set_emergency_control(
        control_kind="memory_freeze",
        enabled=True,
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.GLOBAL.value,
        scope_id="global",
        reason="pause memory promotion",
        root=tmp_path,
    )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]

    assert status["control_state"]["effective"]["emergency_flags"]["memory_freeze"] is True
    assert status["memory_discipline_summary"]["memory_candidate_count"] >= 1
    assert status["promotion_governance_summary"]["memory_freeze_active"] is True
    assert snapshot["memory_discipline_summary"]["memory_candidate_count"] >= 1
    assert snapshot["promotion_governance_summary"]["memory_freeze_active"] is True
    assert export_payload["counts"]["memory_validations"] >= 1
    assert export_payload["control_summary"]["memory_freeze_count"] == 1
    assert handoff["memory_discipline_summary"]["memory_candidate_count"] >= 1
    assert handoff["promotion_governance_summary"]["memory_freeze_active"] is True
