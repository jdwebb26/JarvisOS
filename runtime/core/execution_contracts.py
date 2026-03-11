#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import (
    BackendExecutionRequestRecord,
    BackendExecutionResultRecord,
    new_id,
    now_iso,
)
from runtime.core.token_budget import (
    apply_budget_usage,
    assert_token_budget_allows_execution,
    build_token_budget_summary,
    extract_usage_from_metadata,
)


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def backend_execution_requests_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("backend_execution_requests", root=root)


def backend_execution_results_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("backend_execution_results", root=root)


def _path(folder: Path, record_id: str) -> Path:
    return folder / f"{record_id}.json"


def _save(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def save_backend_execution_request(
    record: BackendExecutionRequestRecord,
    *,
    root: Optional[Path] = None,
) -> BackendExecutionRequestRecord:
    record.updated_at = now_iso()
    _save(_path(backend_execution_requests_dir(root), record.backend_execution_request_id), record.to_dict())
    return record


def save_backend_execution_result(
    record: BackendExecutionResultRecord,
    *,
    root: Optional[Path] = None,
) -> BackendExecutionResultRecord:
    record.updated_at = now_iso()
    _save(_path(backend_execution_results_dir(root), record.backend_execution_result_id), record.to_dict())
    return record


def _load_rows(folder: Path, model) -> list:
    rows = []
    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(model.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def list_backend_execution_requests(root: Optional[Path] = None) -> list[BackendExecutionRequestRecord]:
    return _load_rows(backend_execution_requests_dir(root), BackendExecutionRequestRecord)


def list_backend_execution_results(root: Optional[Path] = None) -> list[BackendExecutionResultRecord]:
    return _load_rows(backend_execution_results_dir(root), BackendExecutionResultRecord)


def load_backend_execution_request(
    backend_execution_request_id: str,
    *,
    root: Optional[Path] = None,
) -> Optional[BackendExecutionRequestRecord]:
    path = _path(backend_execution_requests_dir(root), backend_execution_request_id)
    if not path.exists():
        return None
    return BackendExecutionRequestRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def load_backend_execution_result(
    backend_execution_result_id: str,
    *,
    root: Optional[Path] = None,
) -> Optional[BackendExecutionResultRecord]:
    path = _path(backend_execution_results_dir(root), backend_execution_result_id)
    if not path.exists():
        return None
    return BackendExecutionResultRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def latest_backend_execution_result(root: Optional[Path] = None) -> Optional[BackendExecutionResultRecord]:
    rows = list_backend_execution_results(root=root)
    return rows[0] if rows else None


def resolve_execution_identity(
    *,
    task=None,
    routing_meta: Optional[dict] = None,
    provider_id: Optional[str] = None,
    model_name: Optional[str] = None,
) -> dict[str, str]:
    routing = dict(routing_meta or {})
    if task is not None:
        routing = dict(((getattr(task, "backend_metadata", None) or {}).get("routing") or {})) | routing

    resolved_model_name = str(
        model_name
        or routing.get("model_name")
        or getattr(task, "assigned_model", "")
        or "unassigned"
    )
    resolved_provider_id = str(provider_id or routing.get("provider_id") or "").strip()
    if not resolved_provider_id:
        if resolved_model_name.lower().startswith("qwen"):
            resolved_provider_id = "qwen"
        else:
            resolved_provider_id = "unassigned"

    return {
        "provider_id": resolved_provider_id,
        "model_name": resolved_model_name,
    }


def record_backend_execution_request(
    *,
    task_id: str,
    actor: str,
    lane: str,
    request_kind: str,
    execution_backend: str,
    provider_id: str,
    model_name: str,
    routing_decision_id: Optional[str] = None,
    provider_adapter_result_id: Optional[str] = None,
    backend_run_id: Optional[str] = None,
    input_summary: str = "",
    input_refs: Optional[dict] = None,
    source_refs: Optional[dict] = None,
    status: str = "pending",
    root: Optional[Path] = None,
) -> BackendExecutionRequestRecord:
    assert_token_budget_allows_execution(
        task_id=task_id,
        actor=actor,
        lane=lane,
        execution_backend=execution_backend,
        root=root,
    )
    return save_backend_execution_request(
        BackendExecutionRequestRecord(
            backend_execution_request_id=new_id("breq"),
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            request_kind=request_kind,
            execution_backend=execution_backend,
            provider_id=provider_id,
            model_name=model_name,
            routing_decision_id=routing_decision_id,
            provider_adapter_result_id=provider_adapter_result_id,
            backend_run_id=backend_run_id,
            input_summary=input_summary,
            input_refs=dict(input_refs or {}),
            source_refs=dict(source_refs or {}),
            status=status,
        ),
        root=root,
    )


def record_backend_execution_result(
    *,
    backend_execution_request_id: str,
    task_id: str,
    actor: str,
    lane: str,
    request_kind: str,
    execution_backend: str,
    provider_id: str,
    model_name: str,
    status: str,
    backend_run_id: Optional[str] = None,
    candidate_artifact_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    outcome_summary: str = "",
    error: str = "",
    source_refs: Optional[dict] = None,
    metadata: Optional[dict] = None,
    root: Optional[Path] = None,
) -> BackendExecutionResultRecord:
    record = save_backend_execution_result(
        BackendExecutionResultRecord(
            backend_execution_result_id=new_id("bres"),
            backend_execution_request_id=backend_execution_request_id,
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            request_kind=request_kind,
            execution_backend=execution_backend,
            provider_id=provider_id,
            model_name=model_name,
            status=status,
            backend_run_id=backend_run_id,
            candidate_artifact_id=candidate_artifact_id,
            trace_id=trace_id,
            outcome_summary=outcome_summary,
            error=error,
            source_refs=dict(source_refs or {}),
            metadata=dict(metadata or {}),
        ),
        root=root,
    )
    token_usage, cost_usd = extract_usage_from_metadata(metadata)
    apply_budget_usage(
        task_id=task_id,
        execution_backend=execution_backend,
        token_usage=token_usage,
        cost_usd=cost_usd,
        root=root,
    )
    return record


def build_execution_contract_summary(root: Optional[Path] = None) -> dict:
    requests = list_backend_execution_requests(root=root)
    results = list_backend_execution_results(root=root)
    token_budget_summary = build_token_budget_summary(root=root)
    status_counts: dict[str, int] = {}
    request_kind_counts: dict[str, int] = {}
    for row in results:
        status_counts[row.status] = status_counts.get(row.status, 0) + 1
        request_kind_counts[row.request_kind] = request_kind_counts.get(row.request_kind, 0) + 1
    return {
        "backend_execution_request_count": len(requests),
        "backend_execution_result_count": len(results),
        "backend_execution_status_counts": status_counts,
        "backend_execution_kind_counts": request_kind_counts,
        "latest_backend_execution_request": requests[0].to_dict() if requests else None,
        "latest_backend_execution_result": results[0].to_dict() if results else None,
        "token_budget_summary": token_budget_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current backend execution contract summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_execution_contract_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
