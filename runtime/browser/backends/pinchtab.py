#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Optional

from runtime.core.models import BrowserActionRequestRecord, BrowserActionResultRecord, new_id, now_iso


class PinchTabBackend:
    def __init__(self, config: Optional[dict[str, Any]] = None):
        self.config = dict(config or {})

    def health_check(self) -> dict[str, Any]:
        return {
            "backend": "pinchtab",
            "connected": False,
            "ok": True,
            "status": "stubbed",
            "reason": "pinchtab_backend_not_connected",
            "config": dict(self.config),
        }

    def execute_action(self, request: BrowserActionRequestRecord) -> BrowserActionResultRecord:
        return BrowserActionResultRecord(
            result_id=new_id("bres"),
            request_id=request.request_id,
            task_id=request.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=request.actor,
            lane=request.lane,
            status="stubbed",
            outcome_summary="browser backend stubbed; no live PinchTab connection",
            snapshot_refs={},
            trace_refs={},
            error="pinchtab_backend_not_connected",
        )
