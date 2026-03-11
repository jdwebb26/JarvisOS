#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.controls.control_store import assert_control_allows
from runtime.core.artifact_store import write_text_artifact
from runtime.core.eval_profiles import ensure_default_eval_profiles, resolve_eval_profile
from runtime.core.models import (
    EvalCaseRecord,
    EvalDerivedOutcome,
    EvalOutcomeRecord,
    EvalResultRecord,
    RunTraceRecord,
    new_id,
    now_iso,
)
from runtime.core.task_events import append_event, make_event
from runtime.core.task_store import load_task


EVALUATION_BACKEND_ID = "evaluation_spine"


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_traces_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("run_traces", root=root)


def eval_cases_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("eval_cases", root=root)


def eval_results_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("eval_results", root=root)


def eval_outcomes_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("eval_outcomes", root=root)


def _record_path(folder: Path, record_id: str) -> Path:
    return folder / f"{record_id}.json"


def save_run_trace(record: RunTraceRecord, *, root: Optional[Path] = None) -> RunTraceRecord:
    record.updated_at = now_iso()
    _record_path(run_traces_dir(root), record.trace_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_run_trace(trace_id: str, *, root: Optional[Path] = None) -> Optional[RunTraceRecord]:
    path = _record_path(run_traces_dir(root), trace_id)
    if not path.exists():
        return None
    return RunTraceRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_run_traces_for_task(task_id: str, *, root: Optional[Path] = None) -> list[RunTraceRecord]:
    rows: list[RunTraceRecord] = []
    for path in run_traces_dir(root).glob("*.json"):
        try:
            row = RunTraceRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if row.task_id == task_id:
            rows.append(row)
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def save_eval_case(record: EvalCaseRecord, *, root: Optional[Path] = None) -> EvalCaseRecord:
    record.updated_at = now_iso()
    _record_path(eval_cases_dir(root), record.eval_case_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_eval_case(eval_case_id: str, *, root: Optional[Path] = None) -> Optional[EvalCaseRecord]:
    path = _record_path(eval_cases_dir(root), eval_case_id)
    if not path.exists():
        return None
    return EvalCaseRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_eval_result(record: EvalResultRecord, *, root: Optional[Path] = None) -> EvalResultRecord:
    record.updated_at = now_iso()
    _record_path(eval_results_dir(root), record.eval_result_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def save_eval_outcome(record: EvalOutcomeRecord, *, root: Optional[Path] = None) -> EvalOutcomeRecord:
    record.updated_at = now_iso()
    _record_path(eval_outcomes_dir(root), record.eval_outcome_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_eval_result(eval_result_id: str, *, root: Optional[Path] = None) -> Optional[EvalResultRecord]:
    path = _record_path(eval_results_dir(root), eval_result_id)
    if not path.exists():
        return None
    return EvalResultRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_eval_results_for_task(task_id: str, *, root: Optional[Path] = None) -> list[EvalResultRecord]:
    rows: list[EvalResultRecord] = []
    for path in eval_results_dir(root).glob("*.json"):
        try:
            row = EvalResultRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if row.task_id == task_id:
            rows.append(row)
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def list_eval_outcomes_for_task(task_id: str, *, root: Optional[Path] = None) -> list[EvalOutcomeRecord]:
    rows: list[EvalOutcomeRecord] = []
    for path in eval_outcomes_dir(root).glob("*.json"):
        try:
            row = EvalOutcomeRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if row.task_id == task_id:
            rows.append(row)
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def build_eval_outcome_summary(root: Optional[Path] = None) -> dict[str, Any]:
    rows: list[EvalOutcomeRecord] = []
    for path in eval_outcomes_dir(root).glob("*.json"):
        try:
            rows.append(EvalOutcomeRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    outcome_counts: dict[str, int] = {}
    for row in rows:
        outcome_counts[row.derived_outcome] = outcome_counts.get(row.derived_outcome, 0) + 1
    return {
        "eval_outcome_count": len(rows),
        "eval_outcome_counts": outcome_counts,
        "latest_eval_outcome": rows[0].to_dict() if rows else None,
    }


def record_run_trace(
    *,
    task_id: str,
    trace_kind: str,
    actor: str,
    lane: str,
    execution_backend: str,
    status: str,
    request_summary: str,
    response_summary: str,
    decision_summary: str,
    request_payload: Optional[dict[str, Any]] = None,
    response_payload: Optional[dict[str, Any]] = None,
    replay_payload: Optional[dict[str, Any]] = None,
    source_refs: Optional[dict[str, Any]] = None,
    backend_run_id: Optional[str] = None,
    candidate_artifact_id: Optional[str] = None,
    error: str = "",
    root: Optional[Path] = None,
) -> RunTraceRecord:
    record = RunTraceRecord(
        trace_id=new_id("trace"),
        task_id=task_id,
        trace_kind=trace_kind,
        created_at=now_iso(),
        updated_at=now_iso(),
        actor=actor,
        lane=lane,
        execution_backend=execution_backend,
        backend_run_id=backend_run_id,
        status=status,
        request_summary=request_summary,
        response_summary=response_summary,
        decision_summary=decision_summary,
        request_payload=dict(request_payload or {}),
        response_payload=dict(response_payload or {}),
        replay_payload=dict(replay_payload or {}),
        source_refs=dict(source_refs or {}),
        candidate_artifact_id=candidate_artifact_id,
        error=error,
    )
    save_run_trace(record, root=root)
    return record


def create_eval_case_for_trace(
    *,
    trace_id: str,
    actor: str,
    lane: str,
    evaluator_kind: str,
    objective: str,
    eval_profile_id: Optional[str] = None,
    eval_profile_version: Optional[str] = None,
    criteria: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> EvalCaseRecord:
    trace = load_run_trace(trace_id, root=root)
    if trace is None:
        raise ValueError(f"Run trace not found: {trace_id}")
    task = load_task(trace.task_id, root=Path(root or ROOT).resolve())
    task_type = task.task_type if task is not None else "general"
    ensure_default_eval_profiles(root=root)
    profile = resolve_eval_profile(
        task_type=task_type,
        profile_id=eval_profile_id,
        profile_version=eval_profile_version,
        root=root,
    )
    record = EvalCaseRecord(
        eval_case_id=new_id("evalcase"),
        trace_id=trace_id,
        task_id=trace.task_id,
        created_at=now_iso(),
        updated_at=now_iso(),
        actor=actor,
        lane=lane,
        evaluator_kind=evaluator_kind,
        objective=objective,
        profile_id=profile.profile_id if profile else eval_profile_id,
        profile_version=profile.profile_version if profile else eval_profile_version,
        task_type=task_type,
        criteria=dict(criteria or {}),
    )
    save_eval_case(record, root=root)
    return record


def _score_hermes_trace(trace: RunTraceRecord, criteria: dict[str, Any]) -> tuple[float, bool, str, str, dict[str, Any]]:
    checks = 0
    total = 0
    compared: dict[str, Any] = {
        "trace_status": trace.status,
        "candidate_artifact_id": trace.candidate_artifact_id,
    }
    expected_status = criteria.get("expected_status", "completed")
    total += 1
    if trace.status == expected_status:
        checks += 1
    compared["expected_status"] = expected_status

    if criteria.get("require_candidate_artifact", True):
        total += 1
        if trace.candidate_artifact_id:
            checks += 1

    required_fields = list(criteria.get("required_response_fields", ["title", "summary", "content"]))
    if required_fields:
        total += 1
        if all(trace.response_payload.get(field) for field in required_fields):
            checks += 1
    compared["required_response_fields"] = required_fields

    score = checks / max(total, 1)
    passed = checks == total
    summary = f"Hermes replay eval {'passed' if passed else 'failed'} ({checks}/{total} checks)."
    details = f"status={trace.status} candidate_artifact_id={trace.candidate_artifact_id!r}"
    return score, passed, summary, details, compared


def _score_research_trace(trace: RunTraceRecord, criteria: dict[str, Any]) -> tuple[float, bool, str, str, dict[str, Any]]:
    metrics = dict(trace.replay_payload.get("metrics") or {})
    primary_metric = str(criteria.get("primary_metric") or trace.replay_payload.get("primary_metric") or "").strip()
    if not primary_metric:
        primary_metric = next(iter(metrics.keys()), "")
    direction = str(criteria.get("direction") or trace.replay_payload.get("primary_direction") or "maximize")
    expected_status = criteria.get("expected_status", "completed")

    checks = 0
    total = 0
    compared: dict[str, Any] = {
        "trace_status": trace.status,
        "primary_metric": primary_metric,
        "metrics": metrics,
    }

    total += 1
    if trace.status == expected_status:
        checks += 1
    compared["expected_status"] = expected_status

    if primary_metric:
        total += 1
        if primary_metric in metrics:
            checks += 1

    if "target_metric_value" in criteria and primary_metric in metrics:
        total += 1
        current = float(metrics[primary_metric])
        target = float(criteria["target_metric_value"])
        if (direction == "minimize" and current <= target) or (direction != "minimize" and current >= target):
            checks += 1
        compared["target_metric_value"] = target
        compared["primary_metric_value"] = current

    score = checks / max(total, 1)
    passed = checks == total
    summary = f"Research replay eval {'passed' if passed else 'failed'} ({checks}/{total} checks)."
    details = f"status={trace.status} primary_metric={primary_metric!r} metrics={metrics}"
    return score, passed, summary, details, compared


def _default_eval_for_trace(trace: RunTraceRecord, criteria: dict[str, Any]) -> tuple[float, bool, str, str, dict[str, Any]]:
    if trace.trace_kind == "hermes_task":
        return _score_hermes_trace(trace, criteria)
    if trace.trace_kind == "research_experiment":
        return _score_research_trace(trace, criteria)
    score = 1.0 if trace.status == criteria.get("expected_status", "completed") else 0.0
    passed = score == 1.0
    summary = f"Generic replay eval {'passed' if passed else 'failed'}."
    details = f"trace_kind={trace.trace_kind} status={trace.status}"
    return score, passed, summary, details, {"trace_kind": trace.trace_kind, "trace_status": trace.status}


def _evaluate_profile_outcome(
    *,
    trace: RunTraceRecord,
    score: float,
    compared_values: dict[str, Any],
    profile,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {"score": score, "trace_status": trace.status}
    if "primary_metric" in compared_values and "primary_metric_value" in compared_values:
        metric_name = str(compared_values["primary_metric"])
        metric_value = compared_values["primary_metric_value"]
        if metric_name not in metrics:
            metrics[metric_name] = metric_value
        else:
            metrics[f"source_metric:{metric_name}"] = metric_value
        metrics["primary_metric_value"] = metric_value

    veto_results: dict[str, Any] = {}
    for check in list(profile.veto_checks):
        name = str(check.get("name") or check.get("kind") or f"veto_{len(veto_results)+1}")
        kind = str(check.get("kind") or "")
        passed = True
        details = ""
        if kind == "trace_status_equals":
            expected = str(check.get("expected") or "completed")
            passed = trace.status == expected
            details = f"expected={expected} actual={trace.status}"
        elif kind == "candidate_artifact_required":
            passed = bool(trace.candidate_artifact_id)
            details = f"candidate_artifact_id={trace.candidate_artifact_id!r}"
        elif kind == "response_fields_required":
            required = list(check.get("fields") or [])
            passed = all(trace.response_payload.get(field) for field in required)
            details = f"fields={required}"
        elif kind == "primary_metric_present":
            metric_name = str(compared_values.get("primary_metric") or "").strip()
            passed = bool(metric_name and metric_name in metrics)
            details = f"primary_metric={metric_name!r}"
        veto_results[name] = {"passed": passed, "kind": kind, "details": details}

    hard_fail_results: dict[str, bool] = {}
    for condition in list(profile.hard_fail_conditions):
        if condition == "trace_error_present":
            hard_fail_results[condition] = bool(trace.error)
        elif condition == "trace_not_completed":
            hard_fail_results[condition] = trace.status != "completed"
        else:
            hard_fail_results[condition] = False

    quality_scores: dict[str, Any] = {}
    for metric in list(profile.quality_metrics):
        metric_name = str(metric.get("metric") or "")
        if not metric_name:
            continue
        quality_scores[metric_name] = metrics.get(metric_name)

    derived_outcome = EvalDerivedOutcome.PROMOTABLE.value
    derived_reason = "Eval profile thresholds satisfied."
    veto_failed = any(not result.get("passed", False) for result in veto_results.values())
    hard_fail_triggered = any(hard_fail_results.values())
    threshold_failures: list[str] = []
    minimum_score = profile.promotion_thresholds.get("minimum_score")
    if minimum_score is not None and float(score) < float(minimum_score):
        threshold_failures.append(f"score<{minimum_score}")
    for metric in list(profile.quality_metrics):
        metric_name = str(metric.get("metric") or "")
        minimum = metric.get("minimum")
        if metric_name and minimum is not None:
            actual = quality_scores.get(metric_name)
            if actual is None or float(actual) < float(minimum):
                threshold_failures.append(f"{metric_name}<{minimum}")

    if hard_fail_triggered or veto_failed:
        derived_outcome = EvalDerivedOutcome.REJECTED.value
        reasons = [name for name, failed in hard_fail_results.items() if failed]
        reasons.extend(name for name, result in veto_results.items() if not result.get("passed", False))
        derived_reason = ", ".join(reasons) or "Hard veto failed."
    elif threshold_failures:
        derived_outcome = EvalDerivedOutcome.REVIEW_ONLY.value
        derived_reason = ", ".join(threshold_failures)

    passed = derived_outcome == EvalDerivedOutcome.PROMOTABLE.value
    return {
        "veto_results": veto_results,
        "hard_fail_results": hard_fail_results,
        "quality_scores": quality_scores,
        "metrics": metrics,
        "derived_outcome": derived_outcome,
        "derived_reason": derived_reason,
        "passed": passed,
    }


def replay_trace_to_eval(
    *,
    trace_id: str,
    actor: str,
    lane: str,
    evaluator_kind: str,
    objective: str,
    eval_profile_id: Optional[str] = None,
    eval_profile_version: Optional[str] = None,
    criteria: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
    emit_report_artifact: bool = True,
) -> dict[str, Any]:
    root_path = Path(root or ROOT).resolve()
    trace = load_run_trace(trace_id, root=root_path)
    if trace is None:
        raise ValueError(f"Run trace not found: {trace_id}")

    assert_control_allows(
        action="task_progress",
        root=root_path,
        task_id=trace.task_id,
        subsystem=EVALUATION_BACKEND_ID,
    )

    eval_case = create_eval_case_for_trace(
        trace_id=trace_id,
        actor=actor,
        lane=lane,
        evaluator_kind=evaluator_kind,
        objective=objective,
        eval_profile_id=eval_profile_id,
        eval_profile_version=eval_profile_version,
        criteria=criteria,
        root=root_path,
    )
    score, passed, summary, details, compared_values = _default_eval_for_trace(trace, eval_case.criteria)
    profile = None
    if eval_case.profile_id:
        profile = resolve_eval_profile(
            task_type=eval_case.task_type,
            profile_id=eval_case.profile_id,
            profile_version=eval_case.profile_version,
            root=root_path,
        )
    if profile is None:
        derived = {
            "veto_results": {},
            "hard_fail_results": {},
            "quality_scores": {"score": score},
            "metrics": {"score": score, "trace_status": trace.status},
            "derived_outcome": EvalDerivedOutcome.OPERATOR_DEFINED_EVAL_PENDING.value,
            "derived_reason": f"No EvalProfile found for task_type={eval_case.task_type}.",
            "passed": False,
        }
        passed = derived["passed"]
    else:
        derived = _evaluate_profile_outcome(
            trace=trace,
            score=score,
            compared_values=compared_values,
            profile=profile,
        )
        passed = derived["passed"]
        summary = f"Replay eval {derived['derived_outcome']} ({score:.4f})."
        details = f"{details}; derived_reason={derived['derived_reason']}"

    eval_result = EvalResultRecord(
        eval_result_id=new_id("evalres"),
        eval_case_id=eval_case.eval_case_id,
        trace_id=trace.trace_id,
        task_id=trace.task_id,
        created_at=now_iso(),
        updated_at=now_iso(),
        actor=actor,
        lane=lane,
        evaluator_kind=evaluator_kind,
        profile_id=eval_case.profile_id,
        profile_version=eval_case.profile_version,
        status="completed",
        score=score,
        passed=passed,
        veto_results=derived["veto_results"],
        quality_scores=derived["quality_scores"],
        derived_outcome=derived["derived_outcome"],
        derived_reason=derived["derived_reason"],
        metrics=derived["metrics"],
        notes=objective,
        summary=summary,
        details=details,
        compared_values=compared_values,
    )

    if emit_report_artifact:
        report_content = (
            f"# Replay Eval {eval_result.eval_result_id}\n\n"
            f"Trace: {trace.trace_id}\n"
            f"Trace kind: {trace.trace_kind}\n"
            f"Objective: {objective}\n"
            f"Eval profile: {eval_case.profile_id or 'none'}@{eval_case.profile_version or 'none'}\n"
            f"Score: {score:.4f}\n"
            f"Passed: {passed}\n\n"
            f"Derived outcome: {eval_result.derived_outcome}\n"
            f"Derived reason: {eval_result.derived_reason}\n\n"
            f"Summary: {summary}\n"
            f"Details: {details}\n\n"
            f"Veto results:\n{json.dumps(eval_result.veto_results, indent=2)}\n\n"
            f"Quality scores:\n{json.dumps(eval_result.quality_scores, indent=2)}\n\n"
            f"Metrics:\n{json.dumps(eval_result.metrics, indent=2)}\n\n"
            f"Compared values:\n{json.dumps(compared_values, indent=2)}\n"
        )
        artifact = write_text_artifact(
            task_id=trace.task_id,
            artifact_type="report",
            title=f"Replay eval report: {trace.trace_kind}",
            summary=summary,
            content=report_content,
            actor="eval",
            lane=lane,
            root=root_path,
            producer_kind="backend",
            execution_backend=EVALUATION_BACKEND_ID,
            backend_run_id=eval_result.eval_result_id,
            provenance_ref=f"eval:{trace.trace_id}",
        )
        eval_result.report_artifact_id = artifact["artifact_id"]

    save_eval_result(eval_result, root=root_path)
    replay_result_id = None
    source_refs = dict(trace.source_refs or {})
    for key in ("replay_result_id", "source_replay_result_id"):
        value = source_refs.get(key)
        if value:
            replay_result_id = str(value)
            break
    eval_outcome = EvalOutcomeRecord(
        eval_outcome_id=new_id("evalout"),
        eval_result_id=eval_result.eval_result_id,
        eval_case_id=eval_case.eval_case_id,
        task_id=trace.task_id,
        created_at=now_iso(),
        updated_at=now_iso(),
        profile_id=eval_case.profile_id,
        profile_version=eval_case.profile_version,
        replay_result_id=replay_result_id,
        trace_id=trace.trace_id,
        veto_results=dict(eval_result.veto_results),
        quality_scores=dict(eval_result.quality_scores),
        pass_fail=bool(eval_result.passed),
        metrics=dict(eval_result.metrics),
        notes=eval_result.notes,
        derived_outcome=eval_result.derived_outcome,
        derived_reason=eval_result.derived_reason,
        source_refs={
            "report_artifact_id": eval_result.report_artifact_id,
            "evaluator_kind": eval_result.evaluator_kind,
            "lane": eval_result.lane,
        },
    )
    save_eval_outcome(eval_outcome, root=root_path)
    eval_case.status = "completed"
    eval_case.latest_eval_result_id = eval_result.eval_result_id
    save_eval_case(eval_case, root=root_path)

    append_event(
        make_event(
            task_id=trace.task_id,
            event_type="replay_eval_recorded",
            actor="eval",
            lane=lane,
            summary=f"Replay eval recorded: {eval_result.eval_result_id}",
            execution_backend=EVALUATION_BACKEND_ID,
            backend_run_id=eval_result.eval_result_id,
            artifact_id=eval_result.report_artifact_id,
            details=summary,
        ),
        root=root_path,
    )

    return {
        "eval_case": eval_case.to_dict(),
        "eval_result": eval_result.to_dict(),
        "eval_outcome": eval_outcome.to_dict(),
        "report_artifact_id": eval_result.report_artifact_id,
    }
