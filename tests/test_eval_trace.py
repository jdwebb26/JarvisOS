from pathlib import Path

from runtime.core.artifact_store import load_artifact
from runtime.core.models import RecordLifecycleState, TaskRecord, TaskStatus, now_iso
from runtime.core.task_store import create_task, load_task
from runtime.evals.trace_store import (
    load_eval_result,
    load_run_trace,
    replay_trace_to_eval,
)
from runtime.integrations.autoresearch_adapter import execute_research_campaign
from runtime.integrations.hermes_adapter import execute_hermes_task, load_hermes_result
from runtime.researchlab.runner import list_experiment_runs_for_campaign


def _make_task(
    root: Path,
    *,
    task_id: str,
    status: str,
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
        ),
        root=root,
    )


def test_hermes_trace_replay_creates_eval_artifact(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_eval_hermes", status=TaskStatus.RUNNING.value)

    hermes_result = execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "hermes_trace_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Hermes trace candidate",
            "summary": "traceable backend output",
            "content": "candidate body",
        },
    )

    stored_result = load_hermes_result(hermes_result["result"]["result_id"], root=tmp_path)
    trace = load_run_trace(stored_result["trace_id"], root=tmp_path)
    eval_payload = replay_trace_to_eval(
        trace_id=trace.trace_id,
        actor="tester",
        lane="eval",
        evaluator_kind="replay_check",
        objective="Confirm Hermes trace is replayable",
        root=tmp_path,
    )

    eval_result = load_eval_result(eval_payload["eval_result"]["eval_result_id"], root=tmp_path)
    eval_artifact = load_artifact(eval_payload["report_artifact_id"], root=tmp_path)

    assert trace is not None
    assert trace.trace_kind == "hermes_task"
    assert trace.candidate_artifact_id == hermes_result["candidate_artifact_id"]
    assert eval_result is not None
    assert eval_result.passed is True
    assert eval_artifact.lifecycle_state == RecordLifecycleState.CANDIDATE.value
    assert load_task(task.task_id, root=tmp_path).promoted_artifact_id is None


def test_research_trace_replay_uses_metric_target(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_eval_research", status=TaskStatus.RUNNING.value)

    campaign_result = execute_research_campaign(
        task_id=task.task_id,
        actor="tester",
        lane="research",
        objective="Improve overnight research candidate",
        objective_metrics=["score"],
        primary_metric="score",
        max_passes=2,
        max_budget_units=2,
        root=tmp_path,
        runner=lambda request: {
            "run_id": f"research_trace_{request.pass_index}",
            "summary": "research pass",
            "hypothesis": "better experiment",
            "metrics": {"score": 0.4 * request.pass_index},
            "budget_used": 1,
        },
    )

    runs = list_experiment_runs_for_campaign(campaign_result["campaign"]["campaign_id"], root=tmp_path)
    trace = load_run_trace(runs[-1].trace_id, root=tmp_path)
    eval_payload = replay_trace_to_eval(
        trace_id=trace.trace_id,
        actor="tester",
        lane="eval",
        evaluator_kind="metric_threshold",
        objective="Confirm research pass hit target metric",
        criteria={"primary_metric": "score", "target_metric_value": 0.5},
        root=tmp_path,
    )

    eval_result = load_eval_result(eval_payload["eval_result"]["eval_result_id"], root=tmp_path)
    eval_artifact = load_artifact(eval_payload["report_artifact_id"], root=tmp_path)

    assert trace is not None
    assert trace.trace_kind == "research_experiment"
    assert trace.replay_payload["metrics"]["score"] == 0.8
    assert eval_result is not None
    assert eval_result.passed is True
    assert eval_artifact.lifecycle_state == RecordLifecycleState.CANDIDATE.value
