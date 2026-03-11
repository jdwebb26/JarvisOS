#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.controls.control_store import assert_control_allows
from runtime.core.approval_store import (
    ApprovalStatus,
    latest_approval_for_task,
    load_approval_checkpoint,
    request_approval,
    save_approval,
    save_approval_checkpoint,
)
from runtime.core.artifact_store import write_text_artifact
from runtime.core.execution_contracts import (
    record_backend_execution_request,
    record_backend_execution_result,
    resolve_execution_identity,
    save_backend_execution_request,
)
from runtime.core.models import (
    ExperimentRunRecord,
    MetricResultRecord,
    ResearchCampaignRecord,
    ResearchRecommendationRecord,
    ReviewStatus,
    TaskStatus,
    new_id,
    now_iso,
)
from runtime.core.review_store import latest_review_for_task, request_review, save_review
from runtime.core.task_events import append_event, make_event
from runtime.core.task_store import load_task, save_task, transition_task
from runtime.evals.trace_store import record_run_trace
from runtime.researchlab.runner import (
    list_experiment_runs_for_campaign,
    save_experiment_run,
    save_metric_result,
    save_research_campaign,
    save_research_recommendation,
)


AUTORESEARCH_BACKEND_ID = "autoresearch_adapter"
SUCCESS_STATUS = "completed"
FAILED_STATUS = "failed"
STOPPED_STATUS = "stopped"

Runner = Callable[["LabRunRequest"], dict[str, Any]]


class LabRunMalformedError(ValueError):
    pass


def _serialize(instance: Any) -> dict[str, Any]:
    return asdict(instance)


@dataclass
class LabRunRequest:
    request_id: str
    campaign_id: str
    task_id: str
    created_at: str
    requested_by: str
    lane: str
    pass_index: int
    objective: str
    objective_metrics: list[str]
    primary_metric: str
    metric_directions: dict[str, str]
    baseline_ref: Optional[str]
    benchmark_slice_ref: Optional[str]
    remaining_passes: int
    remaining_budget_units: int
    stop_conditions: dict[str, Any] = field(default_factory=dict)
    execution_backend: str = AUTORESEARCH_BACKEND_ID
    sandbox_class: str = "bounded"
    schema_version: str = "v5.1"

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass
class LabRunResult:
    result_id: str
    request_id: str
    campaign_id: str
    task_id: str
    run_id: str
    received_at: str
    status: str
    summary: str
    hypothesis: str
    metrics: dict[str, float]
    comparison_summary: str = ""
    budget_used: int = 1
    recommendation_hint: str = ""
    stop_signal: bool = False
    raw_result: dict[str, Any] = field(default_factory=dict)
    execution_backend: str = AUTORESEARCH_BACKEND_ID
    schema_version: str = "v5.1"

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


def _direction_for(metric_name: str, metric_directions: dict[str, str]) -> str:
    direction = str(metric_directions.get(metric_name) or "maximize").strip().lower()
    if direction not in {"maximize", "minimize"}:
        raise LabRunMalformedError(f"Metric `{metric_name}` has invalid direction `{direction}`.")
    return direction


def _score_improved(*, metric_name: str, direction: str, current: float, best: Optional[float]) -> bool:
    if best is None:
        return True
    if direction == "minimize":
        return current < best
    return current > best


def _parse_result(*, request: LabRunRequest, payload: dict[str, Any]) -> LabRunResult:
    if not isinstance(payload, dict):
        raise LabRunMalformedError("Lab run response must be a JSON object.")

    summary = str(payload.get("summary") or "").strip()
    hypothesis = str(payload.get("hypothesis") or "").strip()
    raw_metrics = payload.get("metrics")
    if not summary:
        raise LabRunMalformedError("Lab run response must include non-empty `summary`.")
    if not isinstance(raw_metrics, dict):
        raise LabRunMalformedError("Lab run response must include `metrics` as an object.")

    metrics: dict[str, float] = {}
    for metric_name in request.objective_metrics:
        if metric_name not in raw_metrics:
            raise LabRunMalformedError(f"Lab run response is missing required metric `{metric_name}`.")
        try:
            metrics[metric_name] = float(raw_metrics[metric_name])
        except (TypeError, ValueError) as exc:
            raise LabRunMalformedError(f"Metric `{metric_name}` must be numeric.") from exc
        _direction_for(metric_name, request.metric_directions)

    budget_used = int(payload.get("budget_used", 1))
    if budget_used < 1:
        raise LabRunMalformedError("Lab run response `budget_used` must be >= 1.")

    return LabRunResult(
        result_id=new_id("labres"),
        request_id=request.request_id,
        campaign_id=request.campaign_id,
        task_id=request.task_id,
        run_id=str(payload.get("run_id") or new_id("labrun")),
        received_at=now_iso(),
        status=str(payload.get("status") or SUCCESS_STATUS),
        summary=summary,
        hypothesis=hypothesis,
        metrics=metrics,
        comparison_summary=str(payload.get("comparison_summary") or "").strip(),
        budget_used=budget_used,
        recommendation_hint=str(payload.get("recommendation_hint") or "").strip(),
        stop_signal=bool(payload.get("stop_signal", False)),
        raw_result=dict(payload),
    )


def _default_runner(_: LabRunRequest) -> dict[str, Any]:
    raise RuntimeError("Autoresearch runner is not configured.")


def _link_candidate_to_pending_records(*, task_id: str, artifact_id: str, root: Path) -> None:
    review = latest_review_for_task(task_id, root=root)
    if review is not None and review.status == ReviewStatus.PENDING.value and artifact_id not in review.linked_artifact_ids:
        review.linked_artifact_ids.append(artifact_id)
        save_review(review, root=root)

    approval = latest_approval_for_task(task_id, root=root)
    if approval is not None and approval.status == ApprovalStatus.PENDING.value and artifact_id not in approval.linked_artifact_ids:
        approval.linked_artifact_ids.append(artifact_id)
        save_approval(approval, root=root)
        if approval.resumable_checkpoint_id:
            checkpoint = load_approval_checkpoint(approval.resumable_checkpoint_id, root=root)
            if checkpoint is not None and artifact_id not in checkpoint.linked_artifact_ids:
                checkpoint.linked_artifact_ids.append(artifact_id)
                save_approval_checkpoint(checkpoint, root=root)


def _maybe_request_operator_gate(*, task, actor: str, lane: str, summary: str, artifact_id: str, root: Path) -> None:
    if task.review_required:
        existing = latest_review_for_task(task.task_id, root=root)
        if existing is None or existing.status != ReviewStatus.PENDING.value:
            request_review(
                task_id=task.task_id,
                reviewer_role="anton" if task.risk_level == "high_stakes" else "operator",
                requested_by=actor,
                lane=lane,
                summary=summary,
                linked_artifact_ids=[artifact_id],
                root=root,
            )
        return

    if task.approval_required:
        existing = latest_approval_for_task(task.task_id, root=root)
        if existing is None or existing.status != ApprovalStatus.PENDING.value:
            request_approval(
                task_id=task.task_id,
                approval_type=task.task_type,
                requested_by=actor,
                requested_reviewer="anton" if task.risk_level == "high_stakes" else "operator",
                lane=lane,
                summary=summary,
                linked_artifact_ids=[artifact_id],
                root=root,
            )


def _campaign_report_content(
    *,
    campaign: ResearchCampaignRecord,
    runs: list[ExperimentRunRecord],
    recommendation: ResearchRecommendationRecord,
    metric_rows: list[MetricResultRecord],
) -> str:
    lines = [
        f"# Research Campaign {campaign.campaign_id}",
        "",
        f"Objective: {campaign.objective}",
        f"Primary metric: {campaign.primary_metric}",
        f"Status: {campaign.status}",
        f"Completed passes: {campaign.completed_passes}/{campaign.max_passes}",
        f"Budget used: {campaign.budget_used}/{campaign.max_budget_units}",
        "",
        "## Recommendation",
        f"Action: {recommendation.action}",
        f"Summary: {recommendation.summary}",
        f"Rationale: {recommendation.rationale}",
        "",
        "## Run Summaries",
    ]
    for run in runs:
        lines.append(
            f"- Pass {run.pass_index}: status={run.status} budget={run.budget_used} summary={run.summary}"
        )
        if run.comparison_summary:
            lines.append(f"  comparison: {run.comparison_summary}")
    lines.extend(["", "## Metrics"])
    for metric in metric_rows:
        delta = "" if metric.delta_value is None else f" delta={metric.delta_value:+.4f}"
        baseline = "" if metric.baseline_value is None else f" baseline={metric.baseline_value:.4f}"
        lines.append(
            f"- run={metric.run_id} metric={metric.metric_name} value={metric.metric_value:.4f}{baseline}{delta} direction={metric.direction}"
        )
    return "\n".join(lines).strip() + "\n"


def _update_task_metadata(task, *, campaign: ResearchCampaignRecord, recommendation: ResearchRecommendationRecord) -> None:
    task.execution_backend = AUTORESEARCH_BACKEND_ID
    task.backend_run_id = campaign.best_run_id or task.backend_run_id
    task.backend_metadata.setdefault("autoresearch", {})
    meta = task.backend_metadata["autoresearch"]
    meta["last_campaign_id"] = campaign.campaign_id
    meta["objective"] = campaign.objective
    meta["primary_metric"] = campaign.primary_metric
    meta["completed_passes"] = campaign.completed_passes
    meta["budget_used"] = campaign.budget_used
    meta["best_run_id"] = campaign.best_run_id
    meta["best_score"] = campaign.best_score
    meta["recommendation_id"] = recommendation.recommendation_id
    meta["recommendation_action"] = recommendation.action


def execute_research_campaign(
    *,
    task_id: str,
    actor: str,
    lane: str,
    objective: str,
    objective_metrics: list[str],
    metric_directions: Optional[dict[str, str]] = None,
    primary_metric: Optional[str] = None,
    max_passes: int = 1,
    max_budget_units: int = 1,
    stop_conditions: Optional[dict[str, Any]] = None,
    baseline_ref: Optional[str] = None,
    benchmark_slice_ref: Optional[str] = None,
    root: Optional[Path] = None,
    runner: Optional[Runner] = None,
) -> dict[str, Any]:
    root_path = Path(root or ROOT).resolve()
    task = load_task(task_id, root=root_path)
    if task is None:
        raise ValueError(f"Task not found: {task_id}")
    if not objective.strip():
        raise ValueError("Research campaign objective is required.")
    if not objective_metrics:
        raise ValueError("Research campaign requires at least one objective metric.")
    if max_passes < 1 or max_budget_units < 1:
        raise ValueError("Research campaign requires positive max_passes and max_budget_units.")

    normalized_directions = {name: _direction_for(name, metric_directions or {}) for name in objective_metrics}
    chosen_primary = primary_metric or objective_metrics[0]
    if chosen_primary not in objective_metrics:
        raise ValueError("Primary metric must be included in objective_metrics.")

    original_status = task.status
    if original_status not in {
        TaskStatus.QUEUED.value,
        TaskStatus.RUNNING.value,
        TaskStatus.WAITING_REVIEW.value,
        TaskStatus.WAITING_APPROVAL.value,
    }:
        raise ValueError(f"Task {task_id} is `{task.status}` and cannot run bounded research from this state.")

    assert_control_allows(
        action="task_progress",
        root=root_path,
        task_id=task_id,
        subsystem=AUTORESEARCH_BACKEND_ID,
    )

    campaign = ResearchCampaignRecord(
        campaign_id=new_id("camp"),
        task_id=task_id,
        created_at=now_iso(),
        updated_at=now_iso(),
        requested_by=actor,
        lane=lane,
        objective=objective.strip(),
        objective_metrics=list(objective_metrics),
        primary_metric=chosen_primary,
        metric_directions=normalized_directions,
        baseline_ref=baseline_ref,
        benchmark_slice_ref=benchmark_slice_ref,
        max_passes=max_passes,
        max_budget_units=max_budget_units,
        stop_conditions=dict(stop_conditions or {}),
        status="running",
    )
    save_research_campaign(campaign, root=root_path)

    if original_status == TaskStatus.QUEUED.value:
        transition_task(
            task_id=task_id,
            to_status=TaskStatus.RUNNING.value,
            actor=actor,
            lane=lane,
            summary=f"Research campaign started: {campaign.campaign_id}",
            root=root_path,
            details=objective,
        )

    append_event(
        make_event(
            task_id=task_id,
            event_type="research_campaign_started",
            actor=actor,
            lane=lane,
            summary=f"Research campaign started: {campaign.campaign_id}",
            from_status=original_status,
            to_status=TaskStatus.RUNNING.value if original_status == TaskStatus.QUEUED.value else original_status,
            execution_backend=AUTORESEARCH_BACKEND_ID,
            details=objective,
        ),
        root=root_path,
    )

    use_runner = runner or _default_runner
    best_score: Optional[float] = None
    best_run_id: Optional[str] = None
    baseline_primary: Optional[float] = None
    no_improvement_passes = 0
    final_stop_reason = "pass_limit_reached"
    metric_rows: list[MetricResultRecord] = []
    latest_execution_request_id: Optional[str] = None
    latest_execution_result_id: Optional[str] = None
    routing_meta = (task.backend_metadata or {}).get("routing") or {}

    for pass_index in range(1, max_passes + 1):
        if campaign.budget_used >= campaign.max_budget_units:
            final_stop_reason = "budget_exhausted"
            break

        assert_control_allows(
            action="task_progress",
            root=root_path,
            task_id=task_id,
            subsystem=AUTORESEARCH_BACKEND_ID,
        )

        request = LabRunRequest(
            request_id=new_id("labreq"),
            campaign_id=campaign.campaign_id,
            task_id=task_id,
            created_at=now_iso(),
            requested_by=actor,
            lane=lane,
            pass_index=pass_index,
            objective=campaign.objective,
            objective_metrics=list(campaign.objective_metrics),
            primary_metric=campaign.primary_metric,
            metric_directions=dict(campaign.metric_directions),
            baseline_ref=campaign.baseline_ref,
            benchmark_slice_ref=campaign.benchmark_slice_ref,
            remaining_passes=max_passes - pass_index + 1,
            remaining_budget_units=max_budget_units - campaign.budget_used,
            stop_conditions=dict(campaign.stop_conditions),
        )
        execution_identity = resolve_execution_identity(task=task, routing_meta=routing_meta)
        execution_request = record_backend_execution_request(
            task_id=task_id,
            actor=actor,
            lane=lane,
            request_kind="research_experiment",
            execution_backend=AUTORESEARCH_BACKEND_ID,
            provider_id=execution_identity["provider_id"],
            model_name=execution_identity["model_name"],
            routing_decision_id=routing_meta.get("routing_decision_id"),
            provider_adapter_result_id=routing_meta.get("provider_adapter_result_id"),
            input_summary=request.objective,
            input_refs={"campaign_id": campaign.campaign_id, "request_id": request.request_id, "pass_index": pass_index},
            source_refs={"routing_request_id": routing_meta.get("routing_request_id")},
            root=root_path,
        )
        latest_execution_request_id = execution_request.backend_execution_request_id

        try:
            result = _parse_result(request=request, payload=use_runner(request))
        except Exception as exc:
            run = ExperimentRunRecord(
                run_id=new_id("labrun"),
                campaign_id=campaign.campaign_id,
                task_id=task_id,
                pass_index=pass_index,
                created_at=now_iso(),
                updated_at=now_iso(),
                actor=actor,
                lane=lane,
                status=FAILED_STATUS,
                stop_reason=f"{type(exc).__name__}: {exc}",
                raw_result={},
                execution_backend=AUTORESEARCH_BACKEND_ID,
            )
            trace = record_run_trace(
                task_id=task_id,
                trace_kind="research_experiment",
                actor=actor,
                lane=lane,
                execution_backend=AUTORESEARCH_BACKEND_ID,
                backend_run_id=run.run_id,
                status=FAILED_STATUS,
                request_summary=request.objective,
                response_summary="",
                decision_summary=f"Research experiment failed: {run.stop_reason}",
                request_payload=request.to_dict(),
                response_payload={},
                replay_payload={
                    "objective": request.objective,
                    "primary_metric": request.primary_metric,
                    "primary_direction": request.metric_directions.get(request.primary_metric, "maximize"),
                    "metrics": {},
                    "expected_status": FAILED_STATUS,
                },
                source_refs={
                    "campaign_id": campaign.campaign_id,
                    "request_id": request.request_id,
                    "run_id": run.run_id,
                },
                error=run.stop_reason,
                root=root_path,
            )
            run.trace_id = trace.trace_id
            save_experiment_run(run, root=root_path)
            execution_request.status = "failed"
            execution_request.backend_run_id = run.run_id
            save_backend_execution_request(execution_request, root=root_path)
            execution_result = record_backend_execution_result(
                backend_execution_request_id=execution_request.backend_execution_request_id,
                task_id=task_id,
                actor=actor,
                lane=lane,
                request_kind="research_experiment",
                execution_backend=AUTORESEARCH_BACKEND_ID,
                provider_id=execution_identity["provider_id"],
                model_name=execution_identity["model_name"],
                status=FAILED_STATUS,
                backend_run_id=run.run_id,
                trace_id=trace.trace_id,
                outcome_summary=run.stop_reason,
                error=run.stop_reason,
                source_refs={
                    "campaign_id": campaign.campaign_id,
                    "request_id": request.request_id,
                    "run_id": run.run_id,
                },
                root=root_path,
            )
            latest_execution_result_id = execution_result.backend_execution_result_id
            campaign.status = FAILED_STATUS
            campaign.comparison_summary = run.stop_reason
            save_research_campaign(campaign, root=root_path)
            task = load_task(task_id, root=root_path)
            task.checkpoint_summary = f"Research campaign failed: {run.stop_reason}"
            save_task(task, root=root_path)
            transition_task(
                task_id=task_id,
                to_status=TaskStatus.BLOCKED.value,
                actor=actor,
                lane=lane,
                summary=f"Research campaign failed: {campaign.campaign_id}",
                root=root_path,
                details=run.stop_reason,
            )
            append_event(
                make_event(
                    task_id=task_id,
                    event_type="research_campaign_failed",
                    actor="autoresearch",
                    lane=lane,
                    summary=f"Research campaign failed: {campaign.campaign_id}",
                    from_status=original_status,
                    to_status=TaskStatus.BLOCKED.value,
                    execution_backend=AUTORESEARCH_BACKEND_ID,
                    reason=run.stop_reason,
                ),
                root=root_path,
            )
            return {
                "campaign": campaign.to_dict(),
                "recommendation": None,
                "candidate_artifact_id": None,
                "task_status": TaskStatus.BLOCKED.value,
            }

        run = ExperimentRunRecord(
            run_id=result.run_id,
            campaign_id=campaign.campaign_id,
            task_id=task_id,
            pass_index=pass_index,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            status=result.status,
            budget_used=result.budget_used,
            summary=result.summary,
            hypothesis=result.hypothesis,
            comparison_summary=result.comparison_summary,
            stop_reason="",
            raw_result=result.to_dict(),
            execution_backend=AUTORESEARCH_BACKEND_ID,
        )

        primary_value = result.metrics[campaign.primary_metric]
        primary_direction = normalized_directions[campaign.primary_metric]
        if baseline_primary is None:
            baseline_primary = primary_value
        improved = _score_improved(
            metric_name=campaign.primary_metric,
            direction=primary_direction,
            current=primary_value,
            best=best_score,
        )
        if improved:
            best_score = primary_value
            best_run_id = run.run_id
            no_improvement_passes = 0
        else:
            no_improvement_passes += 1

        for metric_name, metric_value in result.metrics.items():
            direction = normalized_directions[metric_name]
            baseline_value = baseline_primary if metric_name == campaign.primary_metric else None
            delta_value = None if baseline_value is None else metric_value - baseline_value
            metric_row = MetricResultRecord(
                metric_result_id=new_id("metric"),
                campaign_id=campaign.campaign_id,
                run_id=run.run_id,
                task_id=task_id,
                metric_name=metric_name,
                metric_value=metric_value,
                direction=direction,
                created_at=now_iso(),
                updated_at=now_iso(),
                baseline_value=baseline_value,
                delta_value=delta_value,
                summary=result.summary,
            )
            save_metric_result(metric_row, root=root_path)
            metric_rows.append(metric_row)

        trace = record_run_trace(
            task_id=task_id,
            trace_kind="research_experiment",
            actor=actor,
            lane=lane,
            execution_backend=AUTORESEARCH_BACKEND_ID,
            backend_run_id=run.run_id,
            status=result.status,
            request_summary=request.objective,
            response_summary=result.summary,
            decision_summary=result.comparison_summary or f"Primary metric {campaign.primary_metric}={primary_value:.4f}",
            request_payload=request.to_dict(),
            response_payload=result.to_dict(),
            replay_payload={
                "objective": request.objective,
                "primary_metric": campaign.primary_metric,
                "primary_direction": primary_direction,
                "metrics": dict(result.metrics),
                "budget_used": result.budget_used,
                "expected_status": result.status,
            },
            source_refs={
                "campaign_id": campaign.campaign_id,
                "request_id": request.request_id,
                "result_id": result.result_id,
                "run_id": run.run_id,
            },
            root=root_path,
        )
        run.trace_id = trace.trace_id
        save_experiment_run(run, root=root_path)
        execution_request.status = "completed"
        execution_request.backend_run_id = run.run_id
        save_backend_execution_request(execution_request, root=root_path)
        execution_result = record_backend_execution_result(
            backend_execution_request_id=execution_request.backend_execution_request_id,
            task_id=task_id,
            actor=actor,
            lane=lane,
            request_kind="research_experiment",
            execution_backend=AUTORESEARCH_BACKEND_ID,
            provider_id=execution_identity["provider_id"],
            model_name=execution_identity["model_name"],
            status=result.status,
            backend_run_id=run.run_id,
            trace_id=trace.trace_id,
            outcome_summary=result.comparison_summary or result.summary,
            source_refs={
                "campaign_id": campaign.campaign_id,
                "request_id": request.request_id,
                "result_id": result.result_id,
                "run_id": run.run_id,
            },
            metadata={"metrics": dict(result.metrics), "budget_used": result.budget_used},
            root=root_path,
        )
        latest_execution_result_id = execution_result.backend_execution_result_id

        campaign.completed_passes = pass_index
        campaign.budget_used += result.budget_used
        campaign.best_run_id = best_run_id
        campaign.best_score = best_score
        campaign.comparison_summary = result.comparison_summary or f"Primary metric {campaign.primary_metric}={primary_value:.4f}"
        save_research_campaign(campaign, root=root_path)

        append_event(
            make_event(
                task_id=task_id,
                event_type="research_experiment_recorded",
                actor="autoresearch",
                lane=lane,
                summary=f"Research pass {pass_index} recorded: {run.run_id}",
                from_status=original_status,
                to_status=task.status,
                execution_backend=AUTORESEARCH_BACKEND_ID,
                backend_run_id=run.run_id,
                details=run.summary,
            ),
            root=root_path,
        )

        target_value = campaign.stop_conditions.get("target_metric_value")
        stagnation_limit = int(campaign.stop_conditions.get("max_non_improving_passes", 0) or 0)
        if target_value is not None:
            reached_target = (primary_value <= float(target_value)) if primary_direction == "minimize" else (primary_value >= float(target_value))
            if reached_target:
                final_stop_reason = "target_reached"
                break
        if stagnation_limit and no_improvement_passes >= stagnation_limit:
            final_stop_reason = "stagnation_limit"
            break
        if result.stop_signal:
            final_stop_reason = "runner_stop_signal"
            break
        if campaign.budget_used >= campaign.max_budget_units:
            final_stop_reason = "budget_exhausted"
            break

    runs = list_experiment_runs_for_campaign(campaign.campaign_id, root=root_path)
    task = load_task(task_id, root=root_path)
    best_delta = None if best_score is None or baseline_primary is None else best_score - baseline_primary
    recommendation_action = "hold_candidate"
    if best_score is not None:
        improvement = _score_improved(
            metric_name=campaign.primary_metric,
            direction=normalized_directions[campaign.primary_metric],
            current=best_score,
            best=baseline_primary,
        )
        if improvement:
            recommendation_action = "promote_candidate"
        elif task.promoted_artifact_id:
            recommendation_action = "demote_promoted_baseline"

    recommendation = ResearchRecommendationRecord(
        recommendation_id=new_id("rec"),
        campaign_id=campaign.campaign_id,
        task_id=task_id,
        created_at=now_iso(),
        updated_at=now_iso(),
        actor=actor,
        lane=lane,
        action=recommendation_action,
        summary=f"Completed {campaign.completed_passes} bounded research passes for `{campaign.objective}`.",
        rationale=f"Primary metric `{campaign.primary_metric}` best={best_score!r} baseline={baseline_primary!r} delta={best_delta!r}; stop_reason={final_stop_reason}.",
        best_run_id=best_run_id,
        execution_backend=AUTORESEARCH_BACKEND_ID,
    )

    campaign.status = STOPPED_STATUS if final_stop_reason in {"budget_exhausted", "target_reached", "stagnation_limit", "runner_stop_signal"} else SUCCESS_STATUS
    report_artifact = write_text_artifact(
        task_id=task_id,
        artifact_type="report",
        title=f"Research campaign recommendation: {campaign.objective}",
        summary=recommendation.summary,
        content=_campaign_report_content(
            campaign=campaign,
            runs=runs,
            recommendation=recommendation,
            metric_rows=metric_rows,
        ),
        actor="autoresearch",
        lane=lane,
        root=root_path,
        producer_kind="backend",
        execution_backend=AUTORESEARCH_BACKEND_ID,
        backend_run_id=best_run_id or campaign.campaign_id,
        provenance_ref=f"research:{campaign.campaign_id}",
    )
    recommendation.recommended_artifact_id = report_artifact["artifact_id"]
    recommendation.linked_artifact_ids = [report_artifact["artifact_id"]]
    save_research_recommendation(recommendation, root=root_path)

    campaign.latest_recommendation_id = recommendation.recommendation_id
    campaign.linked_artifact_ids = [report_artifact["artifact_id"]]
    campaign.comparison_summary = recommendation.rationale
    save_research_campaign(campaign, root=root_path)

    _link_candidate_to_pending_records(task_id=task_id, artifact_id=report_artifact["artifact_id"], root=root_path)
    _maybe_request_operator_gate(
        task=task,
        actor=actor,
        lane=lane,
        summary=f"Research recommendation ready for review: {campaign.campaign_id}",
        artifact_id=report_artifact["artifact_id"],
        root=root_path,
    )

    task = load_task(task_id, root=root_path)
    _update_task_metadata(task, campaign=campaign, recommendation=recommendation)
    task.checkpoint_summary = f"Research campaign complete: {campaign.campaign_id}"
    task.backend_metadata.setdefault("execution_contracts", {})
    task.backend_metadata["execution_contracts"]["latest_backend_execution_request_id"] = latest_execution_request_id
    task.backend_metadata["execution_contracts"]["latest_backend_execution_result_id"] = latest_execution_result_id
    save_task(task, root=root_path)

    if original_status == TaskStatus.QUEUED.value:
        task = load_task(task_id, root=root_path)
        if task.status == TaskStatus.RUNNING.value:
            transition_task(
                task_id=task_id,
                to_status=TaskStatus.QUEUED.value,
                actor=actor,
                lane=lane,
                summary=f"Research campaign complete: {campaign.campaign_id}",
                root=root_path,
                details=recommendation.summary,
            )

    append_event(
        make_event(
            task_id=task_id,
            event_type="research_recommendation_recorded",
            actor="autoresearch",
            lane=lane,
            summary=f"Research recommendation recorded: {recommendation.recommendation_id}",
            from_status=original_status,
            to_status=load_task(task_id, root=root_path).status,
            artifact_id=report_artifact["artifact_id"],
            artifact_type=report_artifact["artifact_type"],
            artifact_title=report_artifact["title"],
            execution_backend=AUTORESEARCH_BACKEND_ID,
            backend_run_id=best_run_id,
            details=recommendation.rationale,
        ),
        root=root_path,
    )

    return {
        "campaign": campaign.to_dict(),
        "recommendation": recommendation.to_dict(),
        "candidate_artifact_id": report_artifact["artifact_id"],
        "task_status": load_task(task_id, root=root_path).status,
    }


def _build_response_runner(args: argparse.Namespace) -> Runner:
    if args.response_file:
        payloads = json.loads(Path(args.response_file).read_text(encoding="utf-8"))
        if not isinstance(payloads, list):
            payloads = [payloads]
        responses = [dict(item) for item in payloads]

        def response_runner(request: LabRunRequest) -> dict[str, Any]:
            index = max(0, request.pass_index - 1)
            if index >= len(responses):
                return dict(responses[-1])
            return dict(responses[index])

        return response_runner
    return _default_runner


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded autoresearch-inspired campaign for a task.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="research", help="Lane name")
    parser.add_argument("--objective", required=True, help="Research objective")
    parser.add_argument("--objective-metric", action="append", dest="objective_metrics", required=True, help="Objective metric name")
    parser.add_argument("--primary-metric", default="", help="Primary metric name")
    parser.add_argument("--max-passes", type=int, default=2, help="Maximum experiment passes")
    parser.add_argument("--max-budget-units", type=int, default=2, help="Maximum total experiment budget units")
    parser.add_argument("--response-file", default="", help="Path to mock JSON result or list of results")
    args = parser.parse_args()

    result = execute_research_campaign(
        task_id=args.task_id,
        actor=args.actor,
        lane=args.lane,
        objective=args.objective,
        objective_metrics=args.objective_metrics,
        primary_metric=args.primary_metric or None,
        max_passes=args.max_passes,
        max_budget_units=args.max_budget_units,
        root=Path(args.root).resolve(),
        runner=_build_response_runner(args),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
