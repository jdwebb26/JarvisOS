from pathlib import Path

from runtime.core.artifact_store import demote_artifact, revoke_artifact, write_text_artifact
from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.output_store import publish_artifact
from runtime.core.task_runtime import load_task, ready_to_ship_task, save_task
from runtime.core.task_store import create_task
from runtime.dashboard.heartbeat_report import build_heartbeat_report
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.output_board import build_output_board
from runtime.dashboard.state_export import build_state_export
from runtime.dashboard.task_board import build_task_board
from runtime.core.status import build_status


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


def test_status_and_heartbeat_surface_impacted_and_revoked_work(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_status_case")
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Promoted artifact",
        summary="summary",
        content="content",
        actor="operator",
        lane="artifacts",
        root=tmp_path,
    )

    task_record = load_task(tmp_path, task.task_id)
    task_record.final_outcome = "candidate_ready_for_live_apply"
    save_task(tmp_path, task_record)
    ready_to_ship_task(root=tmp_path, task_id=task.task_id, actor="operator", lane="review", reason="ready")
    published = publish_artifact(
        task_id=task.task_id,
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="outputs",
        root=tmp_path,
    )

    replacement = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Replacement artifact",
        summary="summary2",
        content="content2",
        actor="operator",
        lane="artifacts",
        root=tmp_path,
    )
    demote_artifact(
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="review",
        root=tmp_path,
        superseded_by_artifact_id=replacement["artifact_id"],
    )
    revoke_artifact(
        artifact_id=replacement["artifact_id"],
        actor="anton",
        lane="review",
        root=tmp_path,
        reason="replacement invalidated",
    )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    heartbeat = build_heartbeat_report(tmp_path)
    state_export = build_state_export(tmp_path)
    output_board = build_output_board(root=tmp_path)
    task_board = build_task_board(tmp_path)

    assert status["counts"]["blocked"] == 1
    assert status["counts"]["impacted_outputs"] == 1
    assert status["counts"]["revoked_artifacts"] == 1
    assert status["blocked"][0]["reason"]
    assert status["impacted_outputs"][0]["output_id"] == published["output_id"]
    assert status["revoked_artifacts"][0]["artifact_id"] == replacement["artifact_id"]

    assert snapshot["counts"]["blocked"] == 1
    assert snapshot["counts"]["impacted_outputs"] == 1
    assert heartbeat["overall_health"] == "degraded"
    assert "blocked_tasks_present" in heartbeat["degraded_signals"]
    assert state_export["output_status_counts"]["impacted"] == 1
    assert output_board["rows"][0]["status"] in {"impacted", "revoked"}
    assert task_board["rows"][0]["impacted_output_ids"]
