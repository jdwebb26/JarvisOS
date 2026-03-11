#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.controls.control_store import assert_control_allows
from runtime.core.approval_store import (
    latest_approval_for_task,
    load_approval_checkpoint,
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
from runtime.core.degradation_policy import (
    ensure_default_degradation_policies,
    load_degradation_policy_for_subsystem,
    record_degradation_event,
)
from runtime.core.models import ApprovalStatus, ReviewStatus, TaskStatus, new_id, now_iso
from runtime.core.models import HermesTaskRequestRecord as HermesTaskRequest
from runtime.core.models import HermesTaskResultRecord as HermesTaskResult
from runtime.core.review_store import latest_review_for_task, save_review
from runtime.core.task_events import append_event, make_event
from runtime.core.task_store import load_task, save_task, transition_task
from runtime.evals.trace_store import record_run_trace


HERMES_BACKEND_ID = "hermes_adapter"
HERMES_ALLOWED_FAMILIES = ["qwen3.5"]
SUCCESS_STATUS = "completed"
TIMEOUT_STATUS = "timeout"
UNREACHABLE_STATUS = "unreachable"
MALFORMED_STATUS = "malformed"
FAILED_STATUS = "failed"

Transport = Callable[["HermesTaskRequest"], dict[str, Any]]


class HermesTransportUnreachableError(ConnectionError):
    pass


class HermesResponseMalformedError(ValueError):
    pass


def _serialize(instance: Any) -> dict[str, Any]:
    return asdict(instance)


def hermes_requests_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "hermes_requests"
    path.mkdir(parents=True, exist_ok=True)
    return path


def hermes_results_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "hermes_results"
    path.mkdir(parents=True, exist_ok=True)
    return path


def request_path(request_id: str, *, root: Optional[Path] = None) -> Path:
    return hermes_requests_dir(root) / f"{request_id}.json"


def result_path(result_id: str, *, root: Optional[Path] = None) -> Path:
    return hermes_results_dir(root) / f"{result_id}.json"


def save_hermes_request(record: HermesTaskRequest, *, root: Optional[Path] = None) -> HermesTaskRequest:
    request_path(record.request_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def save_hermes_result(record: HermesTaskResult, *, root: Optional[Path] = None) -> HermesTaskResult:
    result_path(record.result_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_hermes_request(request_id: str, *, root: Optional[Path] = None) -> dict[str, Any]:
    return json.loads(request_path(request_id, root=root).read_text(encoding="utf-8"))


def load_hermes_result(result_id: str, *, root: Optional[Path] = None) -> dict[str, Any]:
    return json.loads(result_path(result_id, root=root).read_text(encoding="utf-8"))


def list_hermes_requests(root: Optional[Path] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(hermes_requests_dir(root).glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
    return rows


def list_hermes_results(root: Optional[Path] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(hermes_results_dir(root).glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(key=lambda row: row.get("received_at", ""), reverse=True)
    return rows


def build_hermes_summary(root: Optional[Path] = None) -> dict[str, Any]:
    requests = list_hermes_requests(root=root)
    results = list_hermes_results(root=root)
    status_counts: dict[str, int] = {}
    for row in results:
        status = row.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "hermes_request_count": len(requests),
        "hermes_result_count": len(results),
        "hermes_result_status_counts": status_counts,
        "latest_hermes_request": requests[0] if requests else None,
        "latest_hermes_result": results[0] if results else None,
    }


def build_hermes_task_request(
    *,
    task,
    actor: str,
    lane: str,
    timeout_seconds: int,
    metadata: Optional[dict[str, Any]] = None,
) -> HermesTaskRequest:
    routing_meta = (task.backend_metadata or {}).get("routing") or {}
    return HermesTaskRequest(
        request_id=new_id("hermesreq"),
        task_id=task.task_id,
        created_at=now_iso(),
        requested_by=actor,
        lane=lane,
        objective=task.normalized_request,
        timeout_seconds=timeout_seconds,
        execution_backend=HERMES_BACKEND_ID,
        sandbox_class="bounded",
        allowed_tools=["candidate_artifact_write", "bounded_research_synthesis"],
        model_override_policy={
            "allowed_families": list(HERMES_ALLOWED_FAMILIES),
            "provider_policy": "qwen_only",
        },
        max_tokens=(metadata or {}).get("max_tokens"),
        return_format="candidate_artifact",
        capability_declaration={
            "task_type": task.task_type,
            "required_capabilities": list(routing_meta.get("required_capabilities", [])),
        },
        callback_contract={
            "kind": "task_event",
            "task_id": task.task_id,
            "lane": lane,
        },
        metadata=dict(metadata or {}),
    )


def _parse_hermes_response(*, request: HermesTaskRequest, payload: dict[str, Any]) -> HermesTaskResult:
    if not isinstance(payload, dict):
        raise HermesResponseMalformedError("Hermes response must be a JSON object.")

    title = str(payload.get("title") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    content = str(payload.get("content") or "").strip()
    family = str(payload.get("family") or "qwen3.5").strip().lower()
    citations = list(payload.get("citations") or [])
    proposed_next_actions = list(payload.get("proposed_next_actions") or [])
    token_usage = dict(payload.get("token_usage") or {})
    if not title or not summary or not content:
        raise HermesResponseMalformedError("Hermes response must include non-empty `title`, `summary`, and `content`.")
    allowed_families = list((request.model_override_policy or {}).get("allowed_families") or HERMES_ALLOWED_FAMILIES)
    if not any(family.startswith(allowed) for allowed in allowed_families):
        raise HermesResponseMalformedError(
            f"Hermes response family `{family}` violates Qwen-first policy ({', '.join(allowed_families)})."
        )

    return HermesTaskResult(
        result_id=new_id("hermesres"),
        request_id=request.request_id,
        task_id=request.task_id,
        run_id=str(payload.get("run_id") or new_id("hrun")),
        received_at=now_iso(),
        status=SUCCESS_STATUS,
        execution_backend=HERMES_BACKEND_ID,
        family=family,
        model_name=str(payload.get("model_name") or ""),
        artifacts=[],
        checkpoint_summary=summary,
        citations=citations,
        proposed_next_actions=proposed_next_actions,
        token_usage=token_usage,
        error_summary="",
        title=title,
        summary=summary,
        content=content,
        raw_response=dict(payload),
    )


def _default_transport(_: HermesTaskRequest) -> dict[str, Any]:
    raise HermesTransportUnreachableError("Hermes transport is not configured.")


def _update_task_for_hermes(task, *, request: HermesTaskRequest, result: Optional[HermesTaskResult]) -> None:
    task.execution_backend = HERMES_BACKEND_ID
    task.backend_metadata.setdefault("hermes", {})
    hermes_meta = task.backend_metadata["hermes"]
    hermes_meta["last_request_id"] = request.request_id
    hermes_meta["last_requested_by"] = request.requested_by
    hermes_meta["last_requested_at"] = request.created_at
    if result is not None:
        hermes_meta["last_result_id"] = result.result_id
        hermes_meta["last_status"] = result.status
        hermes_meta["last_run_id"] = result.run_id
        hermes_meta["last_received_at"] = result.received_at
        hermes_meta["family"] = result.family
        if result.model_name:
            hermes_meta["model_name"] = result.model_name
        if result.candidate_artifact_id:
            hermes_meta["candidate_artifact_id"] = result.candidate_artifact_id
        task.backend_run_id = result.run_id


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


def _record_failed_result(
    *,
    request: HermesTaskRequest,
    status: str,
    error: str,
    raw_response: Optional[dict[str, Any]] = None,
    root: Path,
) -> HermesTaskResult:
    result = HermesTaskResult(
        result_id=new_id("hermesres"),
        request_id=request.request_id,
        task_id=request.task_id,
        run_id=new_id("hrun"),
        received_at=now_iso(),
        status=status,
        execution_backend=HERMES_BACKEND_ID,
        checkpoint_summary="",
        error_summary=error,
        error=error,
        raw_response=dict(raw_response or {}),
    )
    save_hermes_result(result, root=root)
    return result


def execute_hermes_task(
    *,
    task_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    timeout_seconds: int = 30,
    metadata: Optional[dict[str, Any]] = None,
    transport: Optional[Transport] = None,
) -> dict[str, Any]:
    root_path = Path(root or ROOT).resolve()
    ensure_default_degradation_policies(root=root_path)
    task = load_task(task_id, root=root_path)
    if task is None:
        raise ValueError(f"Task not found: {task_id}")

    if task.status not in {
        TaskStatus.QUEUED.value,
        TaskStatus.RUNNING.value,
        TaskStatus.WAITING_REVIEW.value,
        TaskStatus.WAITING_APPROVAL.value,
    }:
        raise ValueError(f"Task {task_id} is `{task.status}` and cannot be executed via Hermes from this state.")

    assert_control_allows(
        action="task_progress",
        root=root_path,
        task_id=task_id,
        subsystem=HERMES_BACKEND_ID,
    )

    original_status = task.status
    request = build_hermes_task_request(
        task=task,
        actor=actor,
        lane=lane,
        timeout_seconds=timeout_seconds,
        metadata=metadata,
    )
    _update_task_for_hermes(task, request=request, result=None)
    save_task(task, root=root_path)
    save_hermes_request(request, root=root_path)
    routing_meta = (task.backend_metadata or {}).get("routing") or {}
    execution_identity = resolve_execution_identity(task=task, routing_meta=routing_meta)
    execution_request = record_backend_execution_request(
        task_id=task_id,
        actor=actor,
        lane=lane,
        request_kind="hermes_task",
        execution_backend=HERMES_BACKEND_ID,
        provider_id=execution_identity["provider_id"],
        model_name=execution_identity["model_name"],
        routing_decision_id=routing_meta.get("routing_decision_id"),
        provider_adapter_result_id=routing_meta.get("provider_adapter_result_id"),
        input_summary=request.objective,
        input_refs={"hermes_request_id": request.request_id},
        source_refs={
            "routing_request_id": routing_meta.get("routing_request_id"),
            "task_source_message_id": task.source_message_id,
        },
        root=root_path,
    )

    if original_status == TaskStatus.QUEUED.value:
        transition_task(
            task_id=task_id,
            to_status=TaskStatus.RUNNING.value,
            actor=actor,
            lane=lane,
            summary=f"Hermes backend started: {request.request_id}",
            root=root_path,
            details="Hermes adapter claimed queued task for bounded backend execution.",
        )

    append_event(
        make_event(
            task_id=task_id,
            event_type="hermes_request_started",
            actor=actor,
            lane=lane,
            summary=f"Hermes request started: {request.request_id}",
            from_status=original_status,
            to_status=TaskStatus.RUNNING.value if original_status == TaskStatus.QUEUED.value else original_status,
            execution_backend=HERMES_BACKEND_ID,
            details=request.objective,
        ),
        root=root_path,
    )

    use_transport = transport or _default_transport
    try:
        payload = use_transport(request)
        result = _parse_hermes_response(request=request, payload=payload)
    except TimeoutError as exc:
        result = _record_failed_result(
            request=request,
            status=TIMEOUT_STATUS,
            error=str(exc) or "Hermes request timed out.",
            root=root_path,
        )
    except HermesTransportUnreachableError as exc:
        result = _record_failed_result(
            request=request,
            status=UNREACHABLE_STATUS,
            error=str(exc) or "Hermes backend unreachable.",
            root=root_path,
        )
    except (ConnectionError, OSError) as exc:
        result = _record_failed_result(
            request=request,
            status=UNREACHABLE_STATUS,
            error=str(exc) or "Hermes backend unreachable.",
            root=root_path,
        )
    except HermesResponseMalformedError as exc:
        result = _record_failed_result(
            request=request,
            status=MALFORMED_STATUS,
            error=str(exc),
            raw_response=payload if "payload" in locals() and isinstance(payload, dict) else {},
            root=root_path,
        )
    except Exception as exc:
        result = _record_failed_result(
            request=request,
            status=FAILED_STATUS,
            error=f"{type(exc).__name__}: {exc}",
            raw_response=payload if "payload" in locals() and isinstance(payload, dict) else {},
            root=root_path,
        )
    else:
        save_hermes_result(result, root=root_path)

    execution_request.status = "completed" if result.status == SUCCESS_STATUS else "failed"
    execution_request.backend_run_id = result.run_id
    save_backend_execution_request(execution_request, root=root_path)

    task = load_task(task_id, root=root_path)
    if task is None:
        raise ValueError(f"Task disappeared during Hermes execution: {task_id}")
    _update_task_for_hermes(task, request=request, result=result)

    if result.status == SUCCESS_STATUS:
        artifact = write_text_artifact(
            task_id=task_id,
            artifact_type="report",
            title=result.title,
            summary=result.summary,
            content=result.content,
            actor="hermes",
            lane=lane,
            root=root_path,
            producer_kind="backend",
            execution_backend=HERMES_BACKEND_ID,
            backend_run_id=result.run_id,
            provenance_ref=f"hermes:{result.run_id}",
        )
        result.candidate_artifact_id = artifact["artifact_id"]
        result.artifacts = [
            {
                "artifact_id": artifact["artifact_id"],
                "artifact_type": artifact["artifact_type"],
                "lifecycle_state": artifact["lifecycle_state"],
            }
        ]
        result.checkpoint_summary = f"Hermes candidate stored: {artifact['artifact_id']}"
        save_hermes_result(result, root=root_path)
        _update_task_for_hermes(task, request=request, result=result)
        task.checkpoint_summary = f"Hermes candidate stored: {artifact['artifact_id']}"
        save_task(task, root=root_path)
        _link_candidate_to_pending_records(task_id=task_id, artifact_id=artifact["artifact_id"], root=root_path)

        if original_status == TaskStatus.QUEUED.value:
            transition_task(
                task_id=task_id,
                to_status=TaskStatus.QUEUED.value,
                actor=actor,
                lane=lane,
                summary=f"Hermes backend completed: {result.run_id}",
                root=root_path,
                details=f"Hermes candidate artifact stored: {artifact['artifact_id']}",
            )

        append_event(
            make_event(
                task_id=task_id,
                event_type="hermes_result_recorded",
                actor="hermes",
                lane=lane,
                summary=f"Hermes candidate artifact stored: {artifact['artifact_id']}",
                from_status=original_status,
                to_status=TaskStatus.QUEUED.value if original_status == TaskStatus.QUEUED.value else task.status,
                artifact_id=artifact["artifact_id"],
                artifact_type=artifact["artifact_type"],
                artifact_title=artifact["title"],
                execution_backend=HERMES_BACKEND_ID,
                backend_run_id=result.run_id,
                from_lifecycle_state=task.lifecycle_state,
                to_lifecycle_state=task.lifecycle_state,
                details=result.summary,
            ),
            root=root_path,
        )
    else:
        degradation_policy = load_degradation_policy_for_subsystem(HERMES_BACKEND_ID, root=root_path)
        failure_category = "backend_failure"
        if result.status == TIMEOUT_STATUS:
            failure_category = "timeout"
        elif result.status == UNREACHABLE_STATUS:
            failure_category = "unreachable_backend"
        elif result.status == MALFORMED_STATUS:
            failure_category = "malformed_response"
        fallback_allowed = bool(
            degradation_policy
            and degradation_policy.fallback_action in {"local_fallback_allowed", "local_fallback"}
        )
        degradation_reason = (
            f"Hermes degradation applied: {failure_category}; "
            f"fallback_action={degradation_policy.fallback_action if degradation_policy else 'none'}; "
            f"retry_policy={json.dumps((degradation_policy.retry_policy if degradation_policy else {}), sort_keys=True)}; "
            f"operator_notification_required={bool(degradation_policy.requires_operator_notification) if degradation_policy else False}"
        )
        degradation_event = record_degradation_event(
            subsystem=HERMES_BACKEND_ID,
            actor=actor,
            lane=lane,
            task_id=task_id,
            failure_category=failure_category,
            reason=result.error or degradation_reason,
            source_refs={
                "hermes_request_id": request.request_id,
                "hermes_result_id": result.result_id,
                "fallback_allowed": fallback_allowed,
            },
            status="applied",
            root=root_path,
        )
        task.checkpoint_summary = f"Hermes {result.status}: {result.error}"
        task.backend_metadata.setdefault("degradation", {})
        task.backend_metadata["degradation"] = {
            "failure_category": failure_category,
            "degradation_policy_id": degradation_event.degradation_policy_id,
            "degradation_event_id": degradation_event.degradation_event_id,
            "fallback_action": degradation_event.fallback_action,
            "fallback_allowed": fallback_allowed,
            "retry_policy": dict(degradation_event.retry_policy),
            "requires_operator_notification": degradation_event.requires_operator_notification,
        }
        save_task(task, root=root_path)
        transition_task(
            task_id=task_id,
            to_status=TaskStatus.FAILED.value if result.status in {TIMEOUT_STATUS, UNREACHABLE_STATUS} else TaskStatus.BLOCKED.value,
            actor=actor,
            lane=lane,
            summary=f"Hermes backend {result.status}: {request.request_id}",
            root=root_path,
            details=degradation_reason,
            error=f"{failure_category}: {result.error}",
        )
        append_event(
            make_event(
                task_id=task_id,
                event_type="hermes_degradation_applied",
                actor="hermes",
                lane=lane,
                summary=f"Hermes degradation applied: {request.request_id}",
                from_status=original_status,
                to_status=TaskStatus.FAILED.value if result.status in {TIMEOUT_STATUS, UNREACHABLE_STATUS} else TaskStatus.BLOCKED.value,
                execution_backend=HERMES_BACKEND_ID,
                backend_run_id=result.run_id,
                error=f"{failure_category}: {result.error}",
                details=degradation_reason,
            ),
            root=root_path,
        )

    final_task = load_task(task_id, root=root_path)
    trace = record_run_trace(
        task_id=task_id,
        trace_kind="hermes_task",
        actor=actor,
        lane=lane,
        execution_backend=HERMES_BACKEND_ID,
        backend_run_id=result.run_id,
        status=result.status,
        request_summary=request.objective,
        response_summary=result.summary or result.error_summary or result.error,
        decision_summary=(
            f"Hermes candidate artifact stored: {result.candidate_artifact_id}"
            if result.candidate_artifact_id
            else f"Hermes run ended without candidate artifact: {result.status}"
        ),
        request_payload=request.to_dict(),
        response_payload=result.to_dict(),
        replay_payload={
            "expected_status": result.status,
            "family": result.family,
            "model_name": result.model_name,
            "required_response_fields": ["title", "summary", "content"] if result.status == SUCCESS_STATUS else [],
        },
        source_refs={
            "request_id": request.request_id,
            "result_id": result.result_id,
        },
        candidate_artifact_id=result.candidate_artifact_id,
        error=result.error,
        root=root_path,
    )
    result.trace_id = trace.trace_id
    save_hermes_result(result, root=root_path)
    execution_result = record_backend_execution_result(
        backend_execution_request_id=execution_request.backend_execution_request_id,
        task_id=task_id,
        actor=actor,
        lane=lane,
        request_kind="hermes_task",
        execution_backend=HERMES_BACKEND_ID,
        provider_id=execution_identity["provider_id"],
        model_name=str(result.model_name or execution_identity["model_name"]),
        status=result.status,
        backend_run_id=result.run_id,
        candidate_artifact_id=result.candidate_artifact_id,
        trace_id=result.trace_id,
        outcome_summary=result.summary or result.error,
        error=result.error,
        source_refs={
            "routing_decision_id": routing_meta.get("routing_decision_id"),
            "provider_adapter_result_id": routing_meta.get("provider_adapter_result_id"),
            "hermes_request_id": request.request_id,
            "hermes_result_id": result.result_id,
        },
        metadata={
            "family": result.family,
            "request_status": execution_request.status,
            "failure_category": failure_category if result.status != SUCCESS_STATUS else "",
            "degradation_policy_id": (
                ((final_task.backend_metadata if final_task else {}) or {}).get("degradation", {})
            ).get("degradation_policy_id"),
            "token_usage": dict(result.token_usage),
        },
        root=root_path,
    )
    final_task = load_task(task_id, root=root_path)
    if final_task is not None:
        final_task.backend_metadata.setdefault("execution_contracts", {})
        final_task.backend_metadata["execution_contracts"]["latest_backend_execution_request_id"] = (
            execution_request.backend_execution_request_id
        )
        final_task.backend_metadata["execution_contracts"]["latest_backend_execution_result_id"] = (
            execution_result.backend_execution_result_id
        )
        save_task(final_task, root=root_path)
    return {
        "request": request.to_dict(),
        "result": result.to_dict(),
        "task_status": final_task.status if final_task else None,
        "candidate_artifact_id": result.candidate_artifact_id,
    }


def _build_cli_transport(args: argparse.Namespace) -> Transport:
    if args.simulate_timeout:
        def timeout_transport(_: HermesTaskRequest) -> dict[str, Any]:
            raise TimeoutError("Hermes request exceeded timeout budget.")
        return timeout_transport

    if args.simulate_unreachable:
        def unreachable_transport(_: HermesTaskRequest) -> dict[str, Any]:
            raise HermesTransportUnreachableError("Hermes backend is unreachable.")
        return unreachable_transport

    if args.simulate_malformed:
        def malformed_transport(_: HermesTaskRequest) -> dict[str, Any]:
            return {"summary": "missing title/content"}
        return malformed_transport

    if args.response_file:
        payload = json.loads(Path(args.response_file).read_text(encoding="utf-8"))
        def response_transport(_: HermesTaskRequest) -> dict[str, Any]:
            return dict(payload)
        return response_transport

    return _default_transport


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded Hermes backend pass for a task.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="hermes", help="Lane name")
    parser.add_argument("--timeout-seconds", type=int, default=30, help="Hermes timeout budget")
    parser.add_argument("--response-file", default="", help="Path to a mock Hermes JSON response payload")
    parser.add_argument("--simulate-timeout", action="store_true", help="Simulate a Hermes timeout")
    parser.add_argument("--simulate-unreachable", action="store_true", help="Simulate an unreachable Hermes backend")
    parser.add_argument("--simulate-malformed", action="store_true", help="Simulate a malformed Hermes response")
    args = parser.parse_args()

    result = execute_hermes_task(
        task_id=args.task_id,
        actor=args.actor,
        lane=args.lane,
        root=Path(args.root).resolve(),
        timeout_seconds=args.timeout_seconds,
        transport=_build_cli_transport(args),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
