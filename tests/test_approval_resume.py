from pathlib import Path

from runtime.core.approval_store import (
    load_approval_checkpoint,
    request_approval,
    resume_approval_from_checkpoint,
    save_approval,
    record_approval_decision,
)
from runtime.core.artifact_store import load_artifact, write_text_artifact
from runtime.core.models import ApprovalStatus, RecordLifecycleState, TaskRecord, TaskStatus, now_iso
from runtime.core.task_runtime import load_task, save_task
from runtime.core.task_store import create_task


def _make_task(root: Path, *, task_id: str) -> TaskRecord:
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
            raw_request="task: approval resume",
            normalized_request="approval resume",
            status=TaskStatus.RUNNING.value,
            execution_backend="qwen_executor",
        ),
        root=root,
    )


def test_request_approval_creates_durable_checkpoint(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_checkpoint_create")
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Candidate draft",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
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

    checkpoint = load_approval_checkpoint(approval.resumable_checkpoint_id, root=tmp_path)
    assert checkpoint is not None
    assert checkpoint.task_id == task.task_id
    assert checkpoint.approval_id == approval.approval_id
    assert checkpoint.linked_artifact_ids == [artifact["artifact_id"]]
    assert checkpoint.task_status_when_paused == TaskStatus.RUNNING.value
    assert checkpoint.resume_target_status == TaskStatus.QUEUED.value


def test_approval_decision_approved_promotes_and_resumes_from_checkpoint(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_resume_auto")
    task.final_outcome = "candidate_ready_for_live_apply"
    save_task(tmp_path, task)
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Candidate ready",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
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

    checkpoint = load_approval_checkpoint(approval.resumable_checkpoint_id, root=tmp_path)
    stored_task = load_task(tmp_path, task.task_id)
    stored_artifact = load_artifact(artifact["artifact_id"], root=tmp_path)

    assert checkpoint is not None
    assert checkpoint.status == "resumed"
    assert checkpoint.resume_count == 1
    assert stored_task.status == TaskStatus.READY_TO_SHIP.value
    assert stored_task.backend_metadata["approval_resume"]["approval_id"] == approval.approval_id
    assert stored_artifact.lifecycle_state == RecordLifecycleState.PROMOTED.value


def test_manual_resume_rebinds_to_correct_task_artifact_and_checkpoint(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_resume_manual")
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Promoted artifact",
        summary="final",
        content="body",
        actor="operator",
        lane="artifacts",
        root=tmp_path,
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
    approval.status = ApprovalStatus.APPROVED.value
    save_approval(approval, root=tmp_path)

    result = resume_approval_from_checkpoint(
        approval_id=approval.approval_id,
        actor="operator",
        lane="review",
        root=tmp_path,
        reason="manual resume after outage",
    )

    checkpoint = load_approval_checkpoint(approval.resumable_checkpoint_id, root=tmp_path)
    stored_task = load_task(tmp_path, task.task_id)
    assert result["task_id"] == task.task_id
    assert result["artifact_id"] == artifact["artifact_id"]
    assert result["checkpoint_id"] == approval.resumable_checkpoint_id
    assert stored_task.status == TaskStatus.QUEUED.value
    assert checkpoint is not None
    assert checkpoint.status == "resumed"
