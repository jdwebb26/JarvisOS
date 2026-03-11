import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.approval_store import load_approval, load_approval_checkpoint
from runtime.core.artifact_store import load_artifact
from runtime.core.models import RecordLifecycleState, TaskRecord, TaskStatus, now_iso
from runtime.core.status import build_status
from runtime.core.review_store import latest_review_for_task
from runtime.core.task_store import create_task, load_task, save_task
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.integrations.autoresearch_adapter import AUTORESEARCH_BACKEND_ID, execute_research_campaign
from runtime.researchlab.runner import (
    list_experiment_runs_for_campaign,
    list_metric_results_for_run,
    load_research_campaign,
    load_research_recommendation,
)
from scripts.operator_handoff_pack import build_operator_handoff_pack


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


def _seed_autoresearch_contract(task: TaskRecord) -> TaskRecord:
    task.backend_metadata["autoresearch_contract"] = {
        "target_module": "runtime/core/routing.py",
        "program_md_path": "docs/spec/strategy/program.md",
        "eval_command": "python3 -m pytest -q tests/test_routing_candidate_spine.py",
        "budget_minutes": 15,
        "sandbox_root": "workspace/work/research_contract",
    }
    return task


def test_autoresearch_creates_reviewable_candidate_campaign(tmp_path: Path):
    task = _make_task(
        tmp_path,
        task_id="task_research_review",
        status=TaskStatus.QUEUED.value,
        review_required=True,
    )
    _seed_autoresearch_contract(task)
    save_task(task, root=tmp_path)

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
        baseline_ref="baseline:v1",
        benchmark_slice_ref="slice:smoke",
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
    _seed_autoresearch_contract(task)
    save_task(task, root=tmp_path)

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
        baseline_ref="baseline:v1",
        benchmark_slice_ref="slice:smoke",
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
    _seed_autoresearch_contract(task)
    save_task(task, root=tmp_path)

    result = execute_research_campaign(
        task_id=task.task_id,
        actor="tester",
        lane="research",
        objective="bad payload run",
        objective_metrics=["score"],
        baseline_ref="baseline:v1",
        benchmark_slice_ref="slice:smoke",
        max_passes=1,
        max_budget_units=1,
        root=tmp_path,
        runner=lambda _request: {"summary": "missing metrics", "hypothesis": "broken payload"},
    )

    stored_task = load_task(task.task_id, root=tmp_path)
    campaign = load_research_campaign(result["campaign"]["campaign_id"], root=tmp_path)

    assert stored_task is not None
    assert stored_task.status == TaskStatus.BLOCKED.value
    assert result["candidate_artifact_id"] is None
    assert campaign is not None
    assert campaign.status == "failed"
    assert "metrics" in campaign.comparison_summary


def test_autoresearch_invalid_request_contract_blocks_before_runner_dispatch(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_research_invalid_contract", status=TaskStatus.RUNNING.value)
    save_task(task, root=tmp_path)

    result = execute_research_campaign(
        task_id=task.task_id,
        actor="tester",
        lane="research",
        objective="underspecified run",
        objective_metrics=["score"],
        max_passes=1,
        max_budget_units=1,
        root=tmp_path,
        runner=lambda _request: {"summary": "should not dispatch", "hypothesis": "n/a", "metrics": {"score": 1.0}, "budget_used": 1},
    )

    stored_task = load_task(task.task_id, root=tmp_path)
    campaign = load_research_campaign(result["campaign"]["campaign_id"], root=tmp_path)
    result_path = next((tmp_path / "state" / "lab_run_results").glob("*.json"))
    result_row = json.loads(result_path.read_text(encoding="utf-8"))

    assert stored_task is not None
    assert stored_task.status == TaskStatus.BLOCKED.value
    assert result["candidate_artifact_id"] is None
    assert campaign is not None
    assert campaign.status == "failed"
    assert result_row["status"] == "invalid_request"
    assert result_row["failure_category"] == "invalid_request_contract"


def test_autoresearch_persists_spec_fields_and_surfaces_summary(tmp_path: Path):
    task = _make_task(
        tmp_path,
        task_id="task_research_contract",
        status=TaskStatus.QUEUED.value,
        review_required=True,
    )
    _seed_autoresearch_contract(task)
    save_task(task, root=tmp_path)

    result = execute_research_campaign(
        task_id=task.task_id,
        actor="tester",
        lane="research",
        objective="Tighten bounded experiment contract",
        objective_metrics=["win_rate"],
        primary_metric="win_rate",
        baseline_ref="baseline:v1",
        benchmark_slice_ref="slice:smoke",
        max_passes=1,
        max_budget_units=1,
        root=tmp_path,
        runner=lambda _request: {
            "run_id": "run_contract",
            "summary": "contract pass",
            "hypothesis": "narrower eval contract",
            "metrics": {"win_rate": 0.63},
            "baseline_metrics": {"win_rate": 0.58},
            "candidate_metrics": {"win_rate": 0.63},
            "delta_metrics": {"win_rate": 0.05},
            "candidate_patch_path": "workspace/work/research_contract/patch.diff",
            "experiment_log_path": "workspace/work/research_contract/run.log",
            "recommendation": {"action": "promote_candidate"},
            "token_usage": {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200},
            "budget_used": 1,
        },
    )

    request_path = next((tmp_path / "state" / "lab_run_requests").glob("*.json"))
    result_path = next((tmp_path / "state" / "lab_run_results").glob("*.json"))
    request_row = json.loads(request_path.read_text(encoding="utf-8"))
    result_row = json.loads(result_path.read_text(encoding="utf-8"))
    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    exported = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)

    assert request_row["task_id"] == task.task_id
    assert request_row["target_module"] == "runtime/core/routing.py"
    assert request_row["program_md_path"] == "docs/spec/strategy/program.md"
    assert request_row["eval_command"] == "python3 -m pytest -q tests/test_routing_candidate_spine.py"
    assert request_row["baseline_ref"] == "baseline:v1"
    assert request_row["benchmark_slice_ref"] == "slice:smoke"
    assert request_row["budget_minutes"] == 15
    assert request_row["sandbox_root"] == "workspace/work/research_contract"

    assert result_row["task_id"] == task.task_id
    assert result_row["run_id"] == "run_contract"
    assert result_row["candidate_patch_path"] == "workspace/work/research_contract/patch.diff"
    assert result_row["baseline_metrics"] == {"win_rate": 0.58}
    assert result_row["candidate_metrics"] == {"win_rate": 0.63}
    assert result_row["delta_metrics"] == {"win_rate": 0.05}
    assert result_row["experiment_log_path"] == "workspace/work/research_contract/run.log"
    assert result_row["recommendation"] == {"action": "promote_candidate"}
    assert result_row["token_usage"]["total_tokens"] == 200

    assert status["autoresearch_summary"]["lab_run_request_count"] == 1
    assert status["autoresearch_summary"]["lab_run_result_count"] == 1
    assert status["autoresearch_summary"]["latest_lab_run_result"]["run_id"] == "run_contract"
    assert snapshot["autoresearch_summary"]["latest_lab_run_request"]["target_module"] == "runtime/core/routing.py"
    assert exported["counts"]["lab_run_requests"] == 1
    assert exported["counts"]["lab_run_results"] == 1
    assert exported["autoresearch_summary"]["latest_lab_run_result"]["candidate_patch_path"] == "workspace/work/research_contract/patch.diff"
    assert handoff["pack"]["autoresearch_summary"]["latest_lab_run_result"]["run_id"] == "run_contract"
    assert result["candidate_artifact_id"] is not None


def test_autoresearch_persists_strategy_diversity_map(tmp_path: Path):
    task = _make_task(
        tmp_path,
        task_id="task_research_diversity",
        status=TaskStatus.QUEUED.value,
        review_required=True,
    )
    _seed_autoresearch_contract(task)
    save_task(task, root=tmp_path)

    execute_research_campaign(
        task_id=task.task_id,
        actor="tester",
        lane="research",
        objective="Preserve candidate diversity across regimes",
        objective_metrics=["sharpe_gain"],
        primary_metric="sharpe_gain",
        baseline_ref="baseline:v1",
        benchmark_slice_ref="slice:smoke",
        max_passes=1,
        max_budget_units=1,
        root=tmp_path,
        runner=lambda _request: {
            "run_id": "run_diversity",
            "summary": "diversity pass",
            "hypothesis": "regime split broadening",
            "metrics": {"sharpe_gain": 0.21},
            "candidate_metrics": {"sharpe_gain": 0.21},
            "recommendation": {"action": "promote_candidate"},
            "diversity_map": {
                "strategy_type": "mean_reversion",
                "regime_sensitivity": "volatile_open",
                "turnover_characteristics": "medium_turnover",
                "drawdown_profile": "shallow_intraday",
                "style_niche": "opening_imbalance",
                "metric_quality": "strong",
                "hard_vetoes": [],
                "behavioral_diversity_relative_to_promoted": "materially_different",
            },
            "budget_used": 1,
        },
    )

    diversity_path = next((tmp_path / "state" / "strategy_diversity_maps").glob("*.json"))
    diversity_row = json.loads(diversity_path.read_text(encoding="utf-8"))
    status = build_status(tmp_path)
    exported = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)

    assert diversity_row["task_id"] == task.task_id
    assert diversity_row["run_id"] == "run_diversity"
    assert diversity_row["strategy_type"] == "mean_reversion"
    assert diversity_row["regime_sensitivity"] == "volatile_open"
    assert diversity_row["turnover_characteristics"] == "medium_turnover"
    assert diversity_row["drawdown_profile"] == "shallow_intraday"
    assert diversity_row["style_niche"] == "opening_imbalance"
    assert diversity_row["metric_quality"] == "strong"
    assert diversity_row["behavioral_diversity_relative_to_promoted"] == "materially_different"

    assert status["autoresearch_summary"]["strategy_diversity_map_count"] == 1
    assert status["autoresearch_summary"]["latest_strategy_diversity_map"]["strategy_type"] == "mean_reversion"
    assert exported["counts"]["strategy_diversity_maps"] == 1
    assert exported["autoresearch_summary"]["latest_strategy_diversity_map"]["style_niche"] == "opening_imbalance"
    assert handoff["pack"]["autoresearch_summary"]["latest_strategy_diversity_map"]["metric_quality"] == "strong"


def _run_tmp(test_fn, name: str) -> None:
    path = Path(name)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    try:
        test_fn(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    _run_tmp(test_autoresearch_creates_reviewable_candidate_campaign, "tmp_test_autoresearch_review")
    _run_tmp(test_autoresearch_links_pending_approval_checkpoint, "tmp_test_autoresearch_approval")
    _run_tmp(test_autoresearch_malformed_run_blocks_task, "tmp_test_autoresearch_malformed")
    _run_tmp(test_autoresearch_invalid_request_contract_blocks_before_runner_dispatch, "tmp_test_autoresearch_invalid_request")
    _run_tmp(test_autoresearch_persists_spec_fields_and_surfaces_summary, "tmp_test_autoresearch_contract")
    _run_tmp(test_autoresearch_persists_strategy_diversity_map, "tmp_test_autoresearch_diversity")
