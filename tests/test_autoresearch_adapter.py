from pathlib import Path

from runtime.core.approval_store import load_approval, load_approval_checkpoint
from runtime.core.artifact_store import load_artifact
from runtime.core.models import RecordLifecycleState, TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import latest_review_for_task
from runtime.core.task_store import create_task, load_task
from runtime.integrations.autoresearch_adapter import AUTORESEARCH_BACKEND_ID, execute_research_campaign
from runtime.researchlab.runner import (
    list_experiment_runs_for_campaign,
    list_metric_results_for_run,
    load_research_campaign,
    load_research_recommendation,
)


def _make_task(
    root: Path,
    *,
    task_id: str,
    status: str,
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


def test_autoresearch_creates_reviewable_candidate_campaign(tmp_path: Path):
    task = _make_task(
        tmp_path,
        task_id="task_research_review",
        status=TaskStatus.QUEUED.value,
        review_required=True,
    )

    def runner(request):
        return {
            "run_id": f"run_{request.pass_index}",
            "summary": f"pass {request.pass_index}",
            "hypothesis": "better prompt framing",
            "metrics": {"sharpe_gain": 0.10 * request.pass_index, "drawdown": 0.20},
            "budget_used": 1,
            "comparison_summary": f"sharpe_gain={0.10 * request.pass_index:.2f}",
        }

    result = execute_research_campaign(
        task_id=task.task_id,
        actor="tester",
        lane="research",
        objective="Improve overnight NQ strategy candidate",
        objective_metrics=["sharpe_gain", "drawdown"],
        metric_directions={"sharpe_gain": "maximize", "drawdown": "minimize"},
        primary_metric="sharpe_gain",
        max_passes=2,
        max_budget_units=3,
        root=tmp_path,
        runner=runner,
    )

    campaign = load_research_campaign(result["campaign"]["campaign_id"], root=tmp_path)
    recommendation = load_research_recommendation(result["recommendation"]["recommendation_id"], root=tmp_path)
    runs = list_experiment_runs_for_campaign(campaign.campaign_id, root=tmp_path)
    metrics = list_metric_results_for_run(runs[0].run_id, root=tmp_path)
    artifact = load_artifact(result["candidate_artifact_id"], root=tmp_path)
    stored_task = load_task(task.task_id, root=tmp_path)
    pending_review = latest_review_for_task(task.task_id, root=tmp_path)

    assert campaign is not None
    assert campaign.completed_passes == 2
    assert campaign.best_run_id == "run_2"
    assert recommendation is not None
    assert recommendation.action == "promote_candidate"
    assert len(runs) == 2
    assert len(metrics) == 2
    assert artifact.lifecycle_state == RecordLifecycleState.CANDIDATE.value
    assert artifact.execution_backend == AUTORESEARCH_BACKEND_ID
    assert stored_task is not None
    assert stored_task.execution_backend == AUTORESEARCH_BACKEND_ID
    assert stored_task.status == TaskStatus.WAITING_REVIEW.value
    assert pending_review is not None
    assert pending_review.linked_artifact_ids == [artifact.artifact_id]


def test_autoresearch_links_pending_approval_checkpoint(tmp_path: Path):
    task = _make_task(
        tmp_path,
        task_id="task_research_approval",
        status=TaskStatus.WAITING_APPROVAL.value,
        approval_required=True,
    )

    from runtime.core.approval_store import request_approval

    approval = request_approval(
        task_id=task.task_id,
        approval_type="research",
        requested_by="tester",
        requested_reviewer="anton",
        lane="research",
        summary="approval pending",
        root=tmp_path,
    )

    result = execute_research_campaign(
        task_id=task.task_id,
        actor="tester",
        lane="research",
        objective="Validate code experiment",
        objective_metrics=["win_rate"],
        primary_metric="win_rate",
        max_passes=1,
        max_budget_units=1,
        root=tmp_path,
        runner=lambda _request: {
            "run_id": "run_approval",
            "summary": "approval pass",
            "hypothesis": "safer patch",
            "metrics": {"win_rate": 0.61},
            "budget_used": 1,
        },
    )

    stored_approval = load_approval(approval.approval_id, root=tmp_path)
    checkpoint = load_approval_checkpoint(approval.resumable_checkpoint_id, root=tmp_path)

    assert stored_approval is not None
    assert stored_approval.linked_artifact_ids == [result["candidate_artifact_id"]]
    assert checkpoint is not None
    assert checkpoint.linked_artifact_ids == [result["candidate_artifact_id"]]


def test_autoresearch_malformed_run_blocks_task(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_research_bad", status=TaskStatus.RUNNING.value)

    result = execute_research_campaign(
        task_id=task.task_id,
        actor="tester",
        lane="research",
        objective="bad payload run",
        objective_metrics=["score"],
        max_passes=1,
        max_budget_units=1,
        root=tmp_path,
        runner=lambda _request: {"summary": "missing metrics"},
    )

    stored_task = load_task(task.task_id, root=tmp_path)
    campaign = load_research_campaign(result["campaign"]["campaign_id"], root=tmp_path)

    assert stored_task is not None
    assert stored_task.status == TaskStatus.BLOCKED.value
    assert result["candidate_artifact_id"] is None
    assert campaign is not None
    assert campaign.status == "failed"
    assert "metrics" in campaign.comparison_summary
