from pathlib import Path

import pytest

from runtime.core.artifact_store import demote_artifact, load_artifact, promote_artifact, write_text_artifact
from runtime.core.models import CORE_SCHEMA_VERSION, RecordLifecycleState, TaskRecord, TaskStatus, now_iso
from runtime.core.output_store import publish_artifact
from runtime.core.task_events import list_events
from runtime.core.task_store import create_task, load_task


def _make_task(root: Path, *, task_id: str = "task_testcase") -> TaskRecord:
    record = TaskRecord(
        task_id=task_id,
        created_at=now_iso(),
        updated_at=now_iso(),
        source_lane="tests",
        source_channel="tests",
        source_message_id=f"{task_id}_msg",
        source_user="tester",
        trigger_type="explicit_task_colon",
        raw_request="task: write a report",
        normalized_request="write a report",
        status=TaskStatus.RUNNING.value,
        execution_backend="qwen_executor",
    )
    return create_task(record, root=root)


def test_task_record_backfills_schema_and_backend_defaults():
    record = TaskRecord.from_dict(
        {
            "task_id": "task_legacy",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "source_lane": "tests",
            "source_channel": "tests",
            "source_message_id": "legacy_msg",
            "source_user": "tester",
            "trigger_type": "explicit_task_colon",
            "raw_request": "task: legacy",
            "normalized_request": "legacy",
            "version": "v1",
        }
    )

    assert record.schema_version == CORE_SCHEMA_VERSION
    assert record.execution_backend == "unassigned"
    assert record.lifecycle_state == RecordLifecycleState.WORKING.value
    assert record.version == "v1"


def test_backend_artifact_stays_candidate_until_promoted(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_candidate_gate")

    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Backend draft",
        summary="Candidate output",
        content="draft body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
        execution_backend="hermes_adapter",
        backend_run_id="run_123",
        provenance_ref="trace/hermes/run_123",
    )

    stored_task = load_task(task.task_id, root=tmp_path)
    assert stored_task is not None
    assert stored_task.lifecycle_state == RecordLifecycleState.CANDIDATE.value
    assert artifact["lifecycle_state"] == RecordLifecycleState.CANDIDATE.value
    assert artifact["artifact_id"] in stored_task.candidate_artifact_ids

    with pytest.raises(ValueError, match="cannot be published until promoted"):
        publish_artifact(
            task_id=task.task_id,
            artifact_id=artifact["artifact_id"],
            actor="operator",
            lane="outputs",
            root=tmp_path,
        )

    promoted = promote_artifact(
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="review",
        root=tmp_path,
        provenance_ref="approval/apr_123",
    )
    promoted_task = load_task(task.task_id, root=tmp_path)

    assert promoted.lifecycle_state == RecordLifecycleState.PROMOTED.value
    assert promoted.provenance_ref == "approval/apr_123"
    assert promoted_task is not None
    assert promoted_task.lifecycle_state == RecordLifecycleState.PROMOTED.value
    assert promoted_task.promoted_artifact_id == artifact["artifact_id"]
    assert artifact["artifact_id"] not in promoted_task.candidate_artifact_ids

    publish_result = publish_artifact(
        task_id=task.task_id,
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="outputs",
        root=tmp_path,
    )
    assert publish_result["already_published"] is False


def test_demoted_artifact_marks_task_and_event_history(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_demote_case")
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Operator artifact",
        summary="Already promoted",
        content="body",
        actor="operator",
        lane="artifacts",
        root=tmp_path,
    )

    demoted = demote_artifact(
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="review",
        root=tmp_path,
    )
    stored_task = load_task(task.task_id, root=tmp_path)
    events = list_events(task.task_id, root=tmp_path)

    assert demoted.lifecycle_state == RecordLifecycleState.DEMOTED.value
    assert demoted.demoted_by == "operator"
    assert stored_task is not None
    assert stored_task.lifecycle_state == RecordLifecycleState.DEMOTED.value
    assert stored_task.promoted_artifact_id is None
    assert artifact["artifact_id"] in stored_task.demoted_artifact_ids
    assert any(
        event.event_type == "artifact_lifecycle_changed"
        and event.artifact_id == artifact["artifact_id"]
        and event.to_lifecycle_state == RecordLifecycleState.DEMOTED.value
        for event in events
    )


def test_operator_artifact_remains_publishable_by_default(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_operator_publish")
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Operator final",
        summary="Final output",
        content="ready",
        actor="operator",
        lane="artifacts",
        root=tmp_path,
    )

    stored = load_artifact(artifact["artifact_id"], root=tmp_path)
    assert stored.lifecycle_state == RecordLifecycleState.PROMOTED.value

    publish_result = publish_artifact(
        task_id=task.task_id,
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="outputs",
        root=tmp_path,
    )
    assert publish_result["already_published"] is False
