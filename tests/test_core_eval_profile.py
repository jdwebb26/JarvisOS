from pathlib import Path

from runtime.core.models import TaskRecord, TaskType, TaskStatus, now_iso
from runtime.core.status import build_status
from runtime.core.task_store import create_task
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.evals.trace_store import record_run_trace, replay_trace_to_eval
from scripts.operator_handoff_pack import build_operator_handoff_pack


def _make_task(root: Path, *, task_id: str, task_type: str) -> TaskRecord:
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


def test_eval_profile_drives_promotable_outcome_for_general_task(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_eval_profile_general", task_type=TaskType.GENERAL.value)
    trace = record_run_trace(
        task_id=task.task_id,
        trace_kind="hermes_task",
        actor="tester",
        lane="tests",
        execution_backend="hermes_adapter",
        status="completed",
        request_summary="general request",
        response_summary="general response",
        decision_summary="candidate stored",
        request_payload={"prompt": "do the thing"},
        response_payload={"title": "Title", "summary": "Summary", "content": "Body"},
        replay_payload={"expected_status": "completed", "required_response_fields": ["title", "summary", "content"]},
        candidate_artifact_id="artifact_candidate_1",
        root=tmp_path,
    )

    result = replay_trace_to_eval(
        trace_id=trace.trace_id,
        actor="tester",
        lane="eval",
        evaluator_kind="replay_check",
        objective="prove profile driven eval",
        root=tmp_path,
    )

    eval_case = result["eval_case"]
    eval_result = result["eval_result"]
    assert eval_case["profile_id"] == "eval_profile_general"
    assert eval_case["profile_version"] == "v1"
    assert eval_result["profile_id"] == "eval_profile_general"
    assert eval_result["profile_version"] == "v1"
    assert eval_result["veto_results"]["trace_status_completed"]["passed"] is True
    assert eval_result["quality_scores"]["score"] == 1.0
    assert eval_result["derived_outcome"] == "promotable"
    assert eval_result["passed"] is True


def test_eval_without_profile_is_operator_defined_eval_pending(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_eval_profile_review", task_type=TaskType.REVIEW.value)
    trace = record_run_trace(
        task_id=task.task_id,
        trace_kind="generic_task",
        actor="tester",
        lane="tests",
        execution_backend="qwen_executor",
        status="completed",
        request_summary="review request",
        response_summary="review response",
        decision_summary="generic trace",
        root=tmp_path,
    )

    result = replay_trace_to_eval(
        trace_id=trace.trace_id,
        actor="tester",
        lane="eval",
        evaluator_kind="replay_check",
        objective="prove no-profile outcome remains explicit",
        root=tmp_path,
    )

    eval_case = result["eval_case"]
    eval_result = result["eval_result"]
    assert eval_case["profile_id"] is None
    assert eval_result["profile_id"] is None
    assert eval_result["derived_outcome"] == "operator_defined_eval_pending"
    assert eval_result["passed"] is False
    assert "No EvalProfile found" in eval_result["derived_reason"]


def test_eval_profile_summary_surfaces_in_reporting(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_eval_profile_reporting", task_type=TaskType.GENERAL.value)
    trace = record_run_trace(
        task_id=task.task_id,
        trace_kind="hermes_task",
        actor="tester",
        lane="tests",
        execution_backend="hermes_adapter",
        status="completed",
        request_summary="general request",
        response_summary="general response",
        decision_summary="candidate stored",
        request_payload={"prompt": "do the thing"},
        response_payload={"title": "Title", "summary": "Summary", "content": "Body"},
        replay_payload={"expected_status": "completed", "required_response_fields": ["title", "summary", "content"]},
        candidate_artifact_id="artifact_candidate_2",
        root=tmp_path,
    )
    replay_trace_to_eval(
        trace_id=trace.trace_id,
        actor="tester",
        lane="eval",
        evaluator_kind="replay_check",
        objective="seed eval profile summary",
        root=tmp_path,
    )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    state_export = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]

    assert status["eval_profile_summary"]["eval_profile_count"] >= 4
    assert status["eval_profile_summary"]["latest_eval_profile"]["profile_id"]
    assert snapshot["eval_profile_summary"]["eval_profile_count"] >= 4
    assert state_export["eval_profile_summary"]["eval_profile_task_type_counts"]["general"] >= 1
    assert handoff["eval_profile_summary"]["latest_eval_profile"]["profile_version"] == "v1"
