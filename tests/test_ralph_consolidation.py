from pathlib import Path

import pytest

from runtime.controls.control_store import apply_control_action
from runtime.core.artifact_store import load_artifact
from runtime.core.models import ControlScopeType, RecordLifecycleState, TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import latest_review_for_task
from runtime.core.task_store import create_task, load_task
from runtime.evals.trace_store import replay_trace_to_eval
from runtime.integrations.hermes_adapter import execute_hermes_task, load_hermes_result
from runtime.ralph.consolidator import (
    execute_consolidation,
    list_memory_candidates_for_task,
    load_consolidation_run,
)


def _make_task(
    root: Path,
    *,
    task_id: str,
    status: str = TaskStatus.RUNNING.value,
    review_required: bool = False,
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
            raw_request=f"task: {task_id}",
            normalized_request=task_id,
            task_type="research",
            status=status,
            execution_backend="qwen_executor",
            review_required=review_required,
            approval_required=approval_required,
        ),
        root=root,
    )


def test_ralph_generates_digest_and_memory_candidates(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_ralph_digest", review_required=True)
    hermes_result = execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "ralph_hermes_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Hermes candidate",
            "summary": "backend output for Ralph",
            "content": "candidate body",
        },
    )
    stored_result = load_hermes_result(hermes_result["result"]["result_id"], root=tmp_path)
    replay_trace_to_eval(
        trace_id=stored_result["trace_id"],
        actor="tester",
        lane="eval",
        evaluator_kind="replay_check",
        objective="Create eval context for Ralph",
        root=tmp_path,
    )

    result = execute_consolidation(
        task_id=task.task_id,
        actor="tester",
        lane="ralph",
        root=tmp_path,
    )

    run = load_consolidation_run(result["consolidation_run"]["consolidation_run_id"], root=tmp_path)
    digest_artifact = load_artifact(result["digest_artifact_id"], root=tmp_path)
    memory_candidates = list_memory_candidates_for_task(task.task_id, root=tmp_path)
    pending_review = latest_review_for_task(task.task_id, root=tmp_path)
    stored_task = load_task(task.task_id, root=tmp_path)

    assert run is not None
    assert run.status == "completed"
    assert run.digest_artifact_id == result["digest_artifact_id"]
    assert len(run.source_trace_ids) >= 1
    assert len(run.source_eval_result_ids) >= 1
    assert digest_artifact.lifecycle_state == RecordLifecycleState.CANDIDATE.value
    assert digest_artifact.execution_backend == "ralph_adapter"
    assert len(memory_candidates) >= 1
    assert any(candidate.memory_type == "task_digest" for candidate in memory_candidates)
    assert pending_review is not None
    assert result["digest_artifact_id"] in pending_review.linked_artifact_ids
    assert stored_task is not None
    assert stored_task.backend_metadata["ralph"]["digest_artifact_id"] == result["digest_artifact_id"]
    assert stored_task.promoted_artifact_id is None


def test_ralph_respects_control_state(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_ralph_control")
    apply_control_action(
        action="pause",
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.GLOBAL.value,
        scope_id="global",
        reason="operator pause",
        root=tmp_path,
    )

    with pytest.raises(ValueError, match="Control state forbids task progress"):
        execute_consolidation(
            task_id=task.task_id,
            actor="tester",
            lane="ralph",
            root=tmp_path,
        )
