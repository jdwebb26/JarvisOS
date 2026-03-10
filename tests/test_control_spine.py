from pathlib import Path

import pytest

from runtime.controls.control_store import apply_control_action, get_effective_control_state
from runtime.core.approval_store import (
    load_approval_checkpoint,
    record_approval_decision,
    request_approval,
    resume_approval_from_checkpoint,
)
from runtime.core.artifact_store import load_artifact, write_text_artifact
from runtime.core.models import ControlScopeType, RecordLifecycleState, TaskRecord, TaskStatus, now_iso
from runtime.core.output_store import publish_artifact
from runtime.core.status import build_status
from runtime.core.task_runtime import load_task, ready_to_ship_task, save_task
from runtime.core.task_store import create_task
from runtime.dashboard.heartbeat_report import build_heartbeat_report
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.dashboard.task_board import build_task_board


def _make_task(root: Path, *, task_id: str, status: str = TaskStatus.RUNNING.value) -> TaskRecord:
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
            status=status,
            execution_backend="qwen_executor",
        ),
        root=root,
    )


def test_control_state_is_durable_and_visible_in_reporting(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_control_reporting")

    apply_control_action(
        action="degrade",
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.GLOBAL.value,
        scope_id="global",
        reason="budget hard-stop",
        root=tmp_path,
    )
    apply_control_action(
        action="pause",
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.TASK.value,
        scope_id=task.task_id,
        reason="manual hold",
        root=tmp_path,
    )
    apply_control_action(
        action="stop",
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.SUBSYSTEM.value,
        scope_id="qwen_executor",
        reason="subsystem breaker",
        root=tmp_path,
    )

    status = build_status(tmp_path)
    heartbeat = build_heartbeat_report(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    state_export = build_state_export(tmp_path)
    task_board = build_task_board(tmp_path)

    assert status["counts"]["controls"] == 3
    assert status["counts"]["paused_controls"] == 1
    assert status["counts"]["stopped_controls"] == 1
    assert status["counts"]["degraded_controls"] == 1
    assert status["control_state"]["effective"]["effective_status"] == "stopped"
    assert "degraded_controls_present" in heartbeat["degraded_signals"]
    assert "paused_controls_present" in heartbeat["degraded_signals"]
    assert "stopped_controls_present" in heartbeat["degraded_signals"]
    assert snapshot["counts"]["controls"] == 3
    assert state_export["control_run_state_counts"]["paused"] == 1
    assert state_export["control_run_state_counts"]["stopped"] == 1
    assert state_export["control_safety_mode_counts"]["degraded"] == 1
    assert task_board["rows"][0]["control_status"] == "stopped"


def test_pause_blocks_approval_resume_until_resumed(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_control_pause_resume")
    task.final_outcome = "candidate_ready_for_live_apply"
    save_task(tmp_path, task)
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Backend candidate",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
        execution_backend="qwen_executor",
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
    apply_control_action(
        action="pause",
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.GLOBAL.value,
        scope_id="global",
        reason="operator pause",
        root=tmp_path,
    )

    record_approval_decision(
        approval_id=approval.approval_id,
        decision="approved",
        actor="anton",
        lane="review",
        reason="approved while paused",
        root=tmp_path,
    )

    checkpoint = load_approval_checkpoint(approval.resumable_checkpoint_id, root=tmp_path)
    stored_task = load_task(tmp_path, task.task_id)
    stored_artifact = load_artifact(artifact["artifact_id"], root=tmp_path)

    assert checkpoint is not None
    assert checkpoint.status == "pending"
    assert stored_task.status == TaskStatus.BLOCKED.value
    assert stored_artifact.lifecycle_state == RecordLifecycleState.CANDIDATE.value

    apply_control_action(
        action="resume",
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.GLOBAL.value,
        scope_id="global",
        reason="operator resume",
        root=tmp_path,
    )
    result = resume_approval_from_checkpoint(
        approval_id=approval.approval_id,
        actor="operator",
        lane="review",
        reason="resume after pause cleared",
        root=tmp_path,
    )

    resumed_artifact = load_artifact(artifact["artifact_id"], root=tmp_path)
    resumed_task = load_task(tmp_path, task.task_id)
    resumed_checkpoint = load_approval_checkpoint(approval.resumable_checkpoint_id, root=tmp_path)

    assert result["task_status_after"] == TaskStatus.READY_TO_SHIP.value
    assert resumed_artifact.lifecycle_state == RecordLifecycleState.PROMOTED.value
    assert resumed_task.status == TaskStatus.READY_TO_SHIP.value
    assert resumed_checkpoint is not None
    assert resumed_checkpoint.status == "resumed"


def test_revoked_or_degraded_control_blocks_ready_to_ship_and_publish(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_control_publish")
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Operator final",
        summary="final",
        content="body",
        actor="operator",
        lane="artifacts",
        root=tmp_path,
    )
    task_record = load_task(tmp_path, task.task_id)
    task_record.final_outcome = "candidate_ready_for_live_apply"
    save_task(tmp_path, task_record)

    apply_control_action(
        action="degrade",
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.GLOBAL.value,
        scope_id="global",
        reason="degraded mode",
        root=tmp_path,
    )
    with pytest.raises(ValueError, match="Control state forbids ready-to-ship transition"):
        ready_to_ship_task(root=tmp_path, task_id=task.task_id, actor="operator", lane="review", reason="ready")

    apply_control_action(
        action="resume",
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.GLOBAL.value,
        scope_id="global",
        reason="clear degraded mode",
        root=tmp_path,
    )
    ready_to_ship_task(root=tmp_path, task_id=task.task_id, actor="operator", lane="review", reason="ready")

    apply_control_action(
        action="revoke",
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.TASK.value,
        scope_id=task.task_id,
        reason="publish revoked",
        root=tmp_path,
    )
    with pytest.raises(ValueError, match="Control state forbids output publish"):
        publish_artifact(
            task_id=task.task_id,
            artifact_id=artifact["artifact_id"],
            actor="operator",
            lane="outputs",
            root=tmp_path,
        )

    state = get_effective_control_state(root=tmp_path, task_id=task.task_id, subsystem="outputs")
    assert state["effective_status"] == "revoked"
