from pathlib import Path

from runtime.core.approval_store import latest_approval_for_task, record_approval_decision
from runtime.core.artifact_store import demote_artifact, load_artifact, revoke_artifact, write_text_artifact
from runtime.core.models import OutputStatus, RecordLifecycleState, TaskRecord, TaskStatus, now_iso
from runtime.core.output_store import load_output, publish_artifact
from runtime.core.review_store import latest_review_for_task, record_review_verdict, request_review
from runtime.core.task_runtime import load_task, ready_to_ship_task, save_task
from runtime.core.task_store import create_task


def _make_task(
    root: Path,
    *,
    task_id: str,
    review_required: bool = True,
    approval_required: bool = False,
) -> TaskRecord:
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
            raw_request="task: candidate lifecycle",
            normalized_request="candidate lifecycle",
            status=TaskStatus.RUNNING.value,
            execution_backend="qwen_executor",
            review_required=review_required,
            approval_required=approval_required,
        ),
        root=root,
    )


def test_review_and_approval_promote_linked_candidate(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_promote", approval_required=True)
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
        execution_backend="hermes_adapter",
    )

    review = request_review(
        task_id=task.task_id,
        reviewer_role="anton",
        requested_by="tester",
        lane="review",
        summary="review candidate",
        root=tmp_path,
    )
    assert review.linked_artifact_ids == [artifact["artifact_id"]]

    record_review_verdict(
        review_id=review.review_id,
        verdict="approved",
        actor="anton",
        lane="review",
        reason="looks good",
        root=tmp_path,
    )

    approval = latest_approval_for_task(task.task_id, root=tmp_path)
    assert approval is not None
    assert approval.linked_artifact_ids == [artifact["artifact_id"]]

    task_before_approval = load_task(tmp_path, task.task_id)
    task_before_approval.final_outcome = "candidate_ready_for_live_apply"
    save_task(tmp_path, task_before_approval)

    record_approval_decision(
        approval_id=approval.approval_id,
        decision="approved",
        actor="anton",
        lane="review",
        reason="approved for promotion",
        root=tmp_path,
    )

    stored_artifact = load_artifact(artifact["artifact_id"], root=tmp_path)
    stored_task = load_task(tmp_path, task.task_id)
    assert stored_artifact.lifecycle_state == RecordLifecycleState.PROMOTED.value
    assert stored_artifact.provenance_ref == f"approval:{approval.approval_id}"
    assert stored_task.promoted_artifact_id == artifact["artifact_id"]
    assert stored_task.status == TaskStatus.READY_TO_SHIP.value


def test_review_rejection_demotes_candidate(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_reject")
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Candidate reject",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
    )

    review = latest_review_for_task(task.task_id, root=tmp_path)
    if review is None:
        review = request_review(
            task_id=task.task_id,
            reviewer_role="archimedes",
            requested_by="tester",
            lane="review",
            summary="review candidate",
            root=tmp_path,
        )

    record_review_verdict(
        review_id=review.review_id,
        verdict="changes_requested",
        actor="archimedes",
        lane="review",
        reason="needs changes",
        root=tmp_path,
    )

    stored_artifact = load_artifact(artifact["artifact_id"], root=tmp_path)
    stored_task = load_task(tmp_path, task.task_id)
    assert stored_artifact.lifecycle_state == RecordLifecycleState.DEMOTED.value
    assert artifact["artifact_id"] in stored_task.demoted_artifact_ids
    assert stored_task.status == TaskStatus.BLOCKED.value


def test_superseded_artifact_marks_existing_output_impacted(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_supersede", review_required=False)
    first = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="First promoted",
        summary="first",
        content="body",
        actor="operator",
        lane="artifacts",
        root=tmp_path,
    )

    task_record = load_task(tmp_path, task.task_id)
    task_record.final_outcome = "candidate_ready_for_live_apply"
    save_task(tmp_path, task_record)
    ready_to_ship_task(root=tmp_path, task_id=task.task_id, actor="operator", lane="review", reason="ready")

    publish_result = publish_artifact(
        task_id=task.task_id,
        artifact_id=first["artifact_id"],
        actor="operator",
        lane="outputs",
        root=tmp_path,
    )

    replacement = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Replacement promoted",
        summary="replacement",
        content="body2",
        actor="operator",
        lane="artifacts",
        root=tmp_path,
    )

    demote_artifact(
        artifact_id=first["artifact_id"],
        actor="operator",
        lane="review",
        root=tmp_path,
        superseded_by_artifact_id=replacement["artifact_id"],
    )

    impacted_output = load_output(publish_result["output_id"], root=tmp_path)
    stored_task = load_task(tmp_path, task.task_id)
    first_artifact = load_artifact(first["artifact_id"], root=tmp_path)
    assert impacted_output.status == OutputStatus.IMPACTED.value
    assert impacted_output.superseded_by_artifact_id == replacement["artifact_id"]
    assert first_artifact.downstream_impacted_output_ids == [publish_result["output_id"]]
    assert stored_task.status == TaskStatus.BLOCKED.value


def test_revoked_promoted_artifact_marks_output_revoked_and_task_revocation_ready(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_revoke", review_required=False)
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

    publish_result = publish_artifact(
        task_id=task.task_id,
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="outputs",
        root=tmp_path,
    )

    revoked = revoke_artifact(
        artifact_id=artifact["artifact_id"],
        actor="anton",
        lane="review",
        root=tmp_path,
        reason="source invalidated",
    )

    output_record = load_output(publish_result["output_id"], root=tmp_path)
    task_record = load_task(tmp_path, task.task_id)
    assert revoked.revoked_by == "anton"
    assert revoked.revocation_reason == "source invalidated"
    assert output_record.status == OutputStatus.REVOKED.value
    assert output_record.revocation_reason == "source invalidated"
    assert artifact["artifact_id"] in task_record.revoked_artifact_ids
    assert publish_result["output_id"] in task_record.impacted_output_ids
