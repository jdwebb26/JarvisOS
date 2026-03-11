#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from runtime.browser.policy import evaluate_browser_action
from runtime.core.models import BrowserActionRequestRecord, BrowserActionResultRecord, new_id, now_iso
from runtime.controls.control_store import assert_control_allows


ROOT = Path(__file__).resolve().parents[2]


def browser_action_requests_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "browser_action_requests"
    path.mkdir(parents=True, exist_ok=True)
    return path


def browser_action_results_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "browser_action_results"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _request_path(request_id: str, *, root: Optional[Path] = None) -> Path:
    return browser_action_requests_dir(root) / f"{request_id}.json"


def _result_path(result_id: str, *, root: Optional[Path] = None) -> Path:
    return browser_action_results_dir(root) / f"{result_id}.json"


def save_browser_action_request(record: BrowserActionRequestRecord, *, root: Optional[Path] = None) -> BrowserActionRequestRecord:
    record.updated_at = now_iso()
    _request_path(record.request_id, root=root).write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return record


def save_browser_action_result(record: BrowserActionResultRecord, *, root: Optional[Path] = None) -> BrowserActionResultRecord:
    record.updated_at = now_iso()
    _result_path(record.result_id, root=root).write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return record


def load_browser_action_request(request_id: str, *, root: Optional[Path] = None) -> Optional[BrowserActionRequestRecord]:
    path = _request_path(request_id, root=root)
    if not path.exists():
        return None
    return BrowserActionRequestRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def request_browser_action(
    *,
    task_id: str,
    actor: str,
    lane: str,
    action_type: str,
    target_url: str,
    target_selector: str = "",
    action_params: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    assert_control_allows(
        action="browser_action",
        root=root,
        task_id=task_id,
        subsystem="browser_backend",
        actor=actor,
        lane=lane,
    )
    policy = evaluate_browser_action(action_type, target_url, action_params=action_params, root=root)
    status = "blocked" if not policy["allowed"] else ("pending_review" if policy["review_required"] else "accepted")
    record = save_browser_action_request(
        BrowserActionRequestRecord(
            request_id=new_id("breq"),
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            action_type=action_type,
            target_url=target_url,
            target_selector=target_selector,
            action_params=dict(action_params or {}),
            risk_tier=policy["risk_tier"],
            review_required=bool(policy["review_required"]),
            status=status,
            allowlist_ref=policy["allowlist_ref"],
        ),
        root=root,
    )
    return {"request": record.to_dict(), "policy": policy}


def complete_browser_action(
    *,
    request_id: str,
    actor: str,
    lane: str,
    status: str,
    outcome_summary: str,
    snapshot_refs: Optional[dict[str, Any]] = None,
    trace_refs: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    request = load_browser_action_request(request_id, root=root)
    if request is None:
        raise ValueError(f"Unknown browser action request: {request_id}")
    result = save_browser_action_result(
        BrowserActionResultRecord(
            result_id=new_id("bres"),
            request_id=request.request_id,
            task_id=request.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            status=status,
            outcome_summary=outcome_summary,
            snapshot_refs=dict(snapshot_refs or {}),
            trace_refs=dict(trace_refs or {}),
            error=error,
        ),
        root=root,
    )
    request.status = status
    save_browser_action_request(request, root=root)
    return {"request": request.to_dict(), "result": result.to_dict()}
