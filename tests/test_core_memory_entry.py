from pathlib import Path

from runtime.core.artifact_store import revoke_artifact
from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.status import build_status
from runtime.core.task_store import create_task
from runtime.evals.trace_store import replay_trace_to_eval
from runtime.integrations.hermes_adapter import execute_hermes_task, load_hermes_result
from runtime.memory.governance import (
    build_memory_governance_summary,
    list_memory_candidates_for_task,
    load_memory_entry_by_candidate_id,
    promote_memory_candidate,
    retrieve_memory,
)
from runtime.ralph.consolidator import execute_consolidation


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
            raw_request=f"task: {task_id}",
            normalized_request=task_id,
            task_type="research",
            status=TaskStatus.RUNNING.value,
            execution_backend="qwen_executor",
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


def test_promoted_memory_creates_memory_entry_and_retrieval_updates_it(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_memory_entry")
    _seed_eval_context(tmp_path, task.task_id)
    execute_consolidation(task_id=task.task_id, actor="tester", lane="ralph", root=tmp_path)

    candidate = next(
        row for row in list_memory_candidates_for_task(task.task_id, root=tmp_path) if row.memory_type == "task_digest"
    )
    promote_memory_candidate(
        memory_candidate_id=candidate.memory_candidate_id,
        actor="operator",
        lane="memory",
        root=tmp_path,
        reason="promote durable memory entry",
        confidence_score=0.81,
    )

    entry = load_memory_entry_by_candidate_id(candidate.memory_candidate_id, root=tmp_path)
    assert entry is not None
    assert entry.memory_class == "artifact_memory"
    assert entry.structural_type == "episodic"
    assert entry.approval_requirement == "none"
    assert entry.confidence_score == 0.81
    assert entry.last_retrieved_at is None

    retrieve_memory(actor="operator", lane="memory", root=tmp_path, task_id=task.task_id)

    entry = load_memory_entry_by_candidate_id(candidate.memory_candidate_id, root=tmp_path)
    summary = build_memory_governance_summary(root=tmp_path)
    status = build_status(tmp_path)

    assert entry is not None
    assert entry.last_retrieved_at is not None
    assert summary["memory_entry_count"] == 1
    assert summary["latest_memory_entry"]["memory_candidate_id"] == candidate.memory_candidate_id
    assert status["memory_discipline_summary"]["memory_entry_count"] == 1


def test_upstream_artifact_revocation_updates_memory_entry_state(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_memory_entry_revoked")
    _seed_eval_context(tmp_path, task.task_id)
    execute_consolidation(task_id=task.task_id, actor="tester", lane="ralph", root=tmp_path)

    candidate = next(
        row for row in list_memory_candidates_for_task(task.task_id, root=tmp_path) if row.source_artifact_ids
    )
    promote_memory_candidate(
        memory_candidate_id=candidate.memory_candidate_id,
        actor="operator",
        lane="memory",
        root=tmp_path,
        reason="promote before upstream revoke",
    )

    source_artifact_id = candidate.source_artifact_ids[0]
    revoke_artifact(
        artifact_id=source_artifact_id,
        actor="anton",
        lane="review",
        root=tmp_path,
        reason="source artifact revoked",
    )

    entry = load_memory_entry_by_candidate_id(candidate.memory_candidate_id, root=tmp_path)
    assert entry is not None
    assert entry.review_state == "revoked"
    assert entry.lifecycle_state == "demoted"
    assert entry.contradiction_check["status"] == "revoked_upstream"
