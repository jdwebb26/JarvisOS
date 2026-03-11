#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from runtime.browser.protocol import browser_action_requests_dir, browser_action_results_dir


ROOT = Path(__file__).resolve().parents[2]


def _load_jsons(folder: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not folder.exists():
        return rows
    for path in folder.glob("*.json"):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(key=lambda row: (row.get("updated_at", ""), row.get("created_at", "")), reverse=True)
    return rows


def build_browser_action_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    resolved_root = Path(root or ROOT).resolve()
    requests = _load_jsons(browser_action_requests_dir(root=resolved_root))
    results = _load_jsons(browser_action_results_dir(root=resolved_root))

    confirmation_state_counts: dict[str, int] = {}
    request_status_counts: dict[str, int] = {}
    result_status_counts: dict[str, int] = {}
    for row in requests:
        confirmation_state = row.get("confirmation_state", "not_required")
        confirmation_state_counts[confirmation_state] = confirmation_state_counts.get(confirmation_state, 0) + 1
        request_status = row.get("status", "unknown")
        request_status_counts[request_status] = request_status_counts.get(request_status, 0) + 1
    for row in results:
        result_status = row.get("status", "unknown")
        result_status_counts[result_status] = result_status_counts.get(result_status, 0) + 1

    latest_request = requests[0] if requests else None
    latest_result = results[0] if results else None
    latest_evidence_refs = dict((latest_result or {}).get("evidence_refs") or {})
    latest_trace_refs = dict((latest_result or {}).get("trace_refs") or {})

    return {
        "browser_action_request_count": len(requests),
        "browser_action_result_count": len(results),
        "latest_browser_action_request": latest_request,
        "latest_browser_action_result": latest_result,
        "request_status_counts": request_status_counts,
        "result_status_counts": result_status_counts,
        "confirmation_required_count": sum(1 for row in requests if row.get("confirmation_required")),
        "pending_confirmation_count": confirmation_state_counts.get("pending_confirmation", 0),
        "confirmation_state_counts": confirmation_state_counts,
        "evidence_present_count": sum(1 for row in results if row.get("evidence_refs")),
        "screenshot_placeholder_count": sum(
            1 for row in results if ((row.get("evidence_refs") or {}).get("after_screenshot_ref"))
        ),
        "shared_run_trace_link_count": sum(
            1 for row in results if ((row.get("trace_refs") or {}).get("run_trace_id"))
        ),
        "latest_evidence_refs": latest_evidence_refs,
        "latest_trace_refs": latest_trace_refs,
    }
