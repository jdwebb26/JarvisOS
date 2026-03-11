#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from runtime.core.models import DesktopActionRequestRecord, DesktopActionResultRecord, new_id, now_iso


ROOT = Path(__file__).resolve().parents[2]


def desktop_action_requests_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "desktop_action_requests"
    path.mkdir(parents=True, exist_ok=True)
    return path


def desktop_action_results_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "desktop_action_results"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _request_path(request_id: str, *, root: Optional[Path] = None) -> Path:
    return desktop_action_requests_dir(root) / f"{request_id}.json"


def _result_path(result_id: str, *, root: Optional[Path] = None) -> Path:
    return desktop_action_results_dir(root) / f"{result_id}.json"


def save_desktop_action_request(
    record: DesktopActionRequestRecord, *, root: Optional[Path] = None
) -> DesktopActionRequestRecord:
    record.updated_at = now_iso()
    _request_path(record.request_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def save_desktop_action_result(
    record: DesktopActionResultRecord, *, root: Optional[Path] = None
) -> DesktopActionResultRecord:
    record.updated_at = now_iso()
    _result_path(record.result_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_desktop_action_request(
    request_id: str, *, root: Optional[Path] = None
) -> Optional[DesktopActionRequestRecord]:
    path = _request_path(request_id, root=root)
    if not path.exists():
        return None
    return DesktopActionRequestRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def execute_desktop_action(
    request: DesktopActionRequestRecord, *, root: Optional[Path] = None
) -> DesktopActionResultRecord:
    result = DesktopActionResultRecord(
        result_id=new_id("dres"),
        request_id=request.request_id,
        task_id=request.task_id,
        created_at=now_iso(),
        updated_at=now_iso(),
        actor=request.actor,
        lane=request.lane,
        status="stubbed",
        outcome_summary=f"Desktop action stubbed: {request.action_type}",
        error="desktop_executor_not_connected",
    )
    save_desktop_action_result(result, root=root)
    request.status = result.status
    save_desktop_action_request(request, root=root)
    return result
