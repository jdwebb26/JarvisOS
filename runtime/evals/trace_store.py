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
from runtime.core.models import EvalCaseRecord, EvalResultRecord, RunTraceRecord, new_id, now_iso
from runtime.core.task_events import append_event, make_event


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
    criteria: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> EvalCaseRecord:
    trace = load_run_trace(trace_id, root=root)
    if trace is None:
        raise ValueError(f"Run trace not found: {trace_id}")
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


def replay_trace_to_eval(
    *,
    trace_id: str,
    actor: str,
    lane: str,
    evaluator_kind: str,
    objective: str,
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
        criteria=criteria,
        root=root_path,
    )
    score, passed, summary, details, compared_values = _default_eval_for_trace(trace, eval_case.criteria)

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
        status="completed",
        score=score,
        passed=passed,
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
            f"Score: {score:.4f}\n"
            f"Passed: {passed}\n\n"
            f"Summary: {summary}\n"
            f"Details: {details}\n\n"
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
        "report_artifact_id": eval_result.report_artifact_id,
    }
