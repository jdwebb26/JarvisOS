from pathlib import Path

import pytest

from runtime.controls.control_store import apply_control_action
from runtime.core.models import ControlScopeType, RecordLifecycleState, TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import latest_review_for_task, record_review_verdict
from runtime.core.task_store import create_task
from runtime.evals.trace_store import replay_trace_to_eval
from runtime.integrations.hermes_adapter import execute_hermes_task, load_hermes_result
from runtime.memory.governance import (
    list_memory_candidates_for_task,
    list_memory_retrievals,
    load_memory_candidate,
    promote_memory_candidate,
    reject_memory_candidate,
    retrieve_memory,
    supersede_memory_candidate,
)
from runtime.ralph.consolidator import execute_consolidation


def _make_task(
    root: Path,
    *,
    task_id: str,
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
            status=TaskStatus.RUNNING.value,
            execution_backend="qwen_executor",
            review_required=review_required,
            approval_required=approval_required,
        ),
        root=root,
    )


def _seed_eval_context(root: Path, task_id: str) -> None:
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


def test_memory_promotion_and_retrieval_are_bounded(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_memory_retrieve")
    _seed_eval_context(tmp_path, task.task_id)
    execute_consolidation(task_id=task.task_id, actor="tester", lane="ralph", root=tmp_path)

    memory_candidates = list_memory_candidates_for_task(task.task_id, root=tmp_path)
    target = next(candidate for candidate in memory_candidates if candidate.memory_type == "task_digest")

    promoted = promote_memory_candidate(
        memory_candidate_id=target.memory_candidate_id,
        actor="operator",
        lane="memory",
        root=tmp_path,
        reason="useful digest",
        confidence_score=0.82,
    )
    rejected = reject_memory_candidate(
        memory_candidate_id=next(candidate for candidate in memory_candidates if candidate.memory_candidate_id != target.memory_candidate_id).memory_candidate_id,
        actor="operator",
        lane="memory",
        root=tmp_path,
        reason="too narrow",
    )

    retrieval = retrieve_memory(
        actor="operator",
        lane="memory",
        root=tmp_path,
        task_id=task.task_id,
        memory_type="task_digest",
        source_trace_id=target.source_trace_ids[0],
    )
    stored_promoted = load_memory_candidate(promoted.memory_candidate_id, root=tmp_path)
    stored_rejected = load_memory_candidate(rejected.memory_candidate_id, root=tmp_path)
    retrievals = list_memory_retrievals(root=tmp_path, task_id=task.task_id)

    assert stored_promoted is not None
    assert stored_promoted.lifecycle_state == RecordLifecycleState.PROMOTED.value
    assert stored_promoted.decision_status == "promoted"
    assert stored_promoted.confidence_score == pytest.approx(0.82)
    assert stored_rejected is not None
    assert stored_rejected.decision_status == "rejected"
    assert retrieval["retrieval"]["promoted_only"] is True
    assert [item["memory_candidate_id"] for item in retrieval["items"]] == [promoted.memory_candidate_id]
    assert retrievals[0].result_count == 1


def test_memory_promotion_requires_review_when_task_requires_review(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_memory_review", review_required=True)
    execute_consolidation(task_id=task.task_id, actor="tester", lane="ralph", root=tmp_path)

    memory_candidate = list_memory_candidates_for_task(task.task_id, root=tmp_path)[0]
    pending_review = latest_review_for_task(task.task_id, root=tmp_path)

    with pytest.raises(ValueError, match="approved review"):
        promote_memory_candidate(
            memory_candidate_id=memory_candidate.memory_candidate_id,
            actor="operator",
            lane="memory",
            root=tmp_path,
            reason="should fail before review",
        )

    assert pending_review is not None
    record_review_verdict(
        review_id=pending_review.review_id,
        verdict="approved",
        actor="anton",
        lane="review",
        reason="digest reviewed",
        root=tmp_path,
    )

    promoted = promote_memory_candidate(
        memory_candidate_id=memory_candidate.memory_candidate_id,
        actor="operator",
        lane="memory",
        root=tmp_path,
        reason="review cleared",
        confidence_score=0.77,
    )

    assert promoted.lifecycle_state == RecordLifecycleState.PROMOTED.value
    assert promoted.decision_status == "promoted"


def test_superseded_memory_is_hidden_from_default_retrieval_and_control_blocks_promotion(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_memory_supersede")
    _seed_eval_context(tmp_path, task.task_id)
    execute_consolidation(task_id=task.task_id, actor="tester", lane="ralph", root=tmp_path)
    memory_candidates = list_memory_candidates_for_task(task.task_id, root=tmp_path)

    first = promote_memory_candidate(
        memory_candidate_id=memory_candidates[0].memory_candidate_id,
        actor="operator",
        lane="memory",
        root=tmp_path,
        reason="first promoted",
        confidence_score=0.7,
    )
    second = promote_memory_candidate(
        memory_candidate_id=memory_candidates[1].memory_candidate_id,
        actor="operator",
        lane="memory",
        root=tmp_path,
        reason="second promoted",
        confidence_score=0.9,
    )
    supersede_memory_candidate(
        memory_candidate_id=first.memory_candidate_id,
        actor="operator",
        lane="memory",
        root=tmp_path,
        reason="newer summary supersedes old one",
        superseded_by_memory_candidate_id=second.memory_candidate_id,
    )

    default_retrieval = retrieve_memory(actor="operator", lane="memory", root=tmp_path, task_id=task.task_id)
    full_retrieval = retrieve_memory(
        actor="operator",
        lane="memory",
        root=tmp_path,
        task_id=task.task_id,
        promoted_only=False,
        include_contradicted=True,
    )

    assert [item["memory_candidate_id"] for item in default_retrieval["items"]] == [second.memory_candidate_id]
    assert {item["memory_candidate_id"] for item in full_retrieval["items"]} == {
        first.memory_candidate_id,
        second.memory_candidate_id,
    }

    task_control = _make_task(tmp_path, task_id="task_memory_control")
    execute_consolidation(task_id=task_control.task_id, actor="tester", lane="ralph", root=tmp_path)
    control_candidate = list_memory_candidates_for_task(task_control.task_id, root=tmp_path)[0]
    apply_control_action(
        action="degrade",
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.GLOBAL.value,
        scope_id="global",
        reason="operator degrade",
        root=tmp_path,
    )
    with pytest.raises(ValueError, match="Control state forbids artifact promotion"):
        promote_memory_candidate(
            memory_candidate_id=control_candidate.memory_candidate_id,
            actor="operator",
            lane="memory",
            root=tmp_path,
            reason="blocked by control",
        )
