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
    latest_approval_for_task,
    load_approval_checkpoint,
    save_approval,
    save_approval_checkpoint,
)
from runtime.core.artifact_store import write_text_artifact
from runtime.core.models import ApprovalStatus, ReviewStatus, TaskStatus, new_id, now_iso
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


@dataclass
class HermesTaskRequest:
    request_id: str
    task_id: str
    created_at: str
    requested_by: str
    lane: str
    summary: str
    task_type: str
    timeout_seconds: int
    execution_backend: str = HERMES_BACKEND_ID
    allowed_families: list[str] = field(default_factory=lambda: list(HERMES_ALLOWED_FAMILIES))
    sandbox_class: str = "bounded"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "v5.1"

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass
class HermesTaskResult:
    result_id: str
    request_id: str
    task_id: str
    run_id: str
    received_at: str
    status: str
    execution_backend: str = HERMES_BACKEND_ID
    family: str = "qwen3.5"
    model_name: str = ""
    title: str = ""
    summary: str = ""
    content: str = ""
    error: str = ""
    candidate_artifact_id: Optional[str] = None
    trace_id: Optional[str] = None
    raw_response: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "v5.1"

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


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


def build_hermes_task_request(
    *,
    task,
    actor: str,
    lane: str,
    timeout_seconds: int,
    metadata: Optional[dict[str, Any]] = None,
) -> HermesTaskRequest:
    return HermesTaskRequest(
        request_id=new_id("hermesreq"),
        task_id=task.task_id,
        created_at=now_iso(),
        requested_by=actor,
        lane=lane,
        summary=task.normalized_request,
        task_type=task.task_type,
        timeout_seconds=timeout_seconds,
        metadata=dict(metadata or {}),
    )


def _parse_hermes_response(*, request: HermesTaskRequest, payload: dict[str, Any]) -> HermesTaskResult:
    if not isinstance(payload, dict):
        raise HermesResponseMalformedError("Hermes response must be a JSON object.")

    title = str(payload.get("title") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    content = str(payload.get("content") or "").strip()
    family = str(payload.get("family") or "qwen3.5").strip().lower()
    if not title or not summary or not content:
        raise HermesResponseMalformedError("Hermes response must include non-empty `title`, `summary`, and `content`.")
    if not any(family.startswith(allowed) for allowed in request.allowed_families):
        raise HermesResponseMalformedError(
            f"Hermes response family `{family}` violates Qwen-first policy ({', '.join(request.allowed_families)})."
        )

    return HermesTaskResult(
        result_id=new_id("hermesres"),
        request_id=request.request_id,
        task_id=request.task_id,
        run_id=str(payload.get("run_id") or new_id("hrun")),
        received_at=now_iso(),
        status=SUCCESS_STATUS,
        family=family,
        model_name=str(payload.get("model_name") or ""),
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
            details=request.summary,
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
        task.checkpoint_summary = f"Hermes {result.status}: {result.error}"
        save_task(task, root=root_path)
        transition_task(
            task_id=task_id,
            to_status=TaskStatus.BLOCKED.value,
            actor=actor,
            lane=lane,
            summary=f"Hermes backend {result.status}: {request.request_id}",
            root=root_path,
            details=result.error,
        )
        append_event(
            make_event(
                task_id=task_id,
                event_type="hermes_result_failed",
                actor="hermes",
                lane=lane,
                summary=f"Hermes result {result.status}: {request.request_id}",
                from_status=original_status,
                to_status=TaskStatus.BLOCKED.value,
                execution_backend=HERMES_BACKEND_ID,
                backend_run_id=result.run_id,
                error=result.error,
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
        request_summary=request.summary,
        response_summary=result.summary or result.error,
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
