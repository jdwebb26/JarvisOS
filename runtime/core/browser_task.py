#!/usr/bin/env python3
"""browser_task — direct browser task creation, bypassing LLM model routing.

Browser tasks don't need an LLM backend — they execute via PinchTab through
the browser_backend adapter.  This module creates valid TaskRecords with
execution_backend="browser_backend" and a JSON spec as normalized_request
(the format bowser_adapter expects), without going through route_task_intent().

Entry points:
    create_browser_task()        — explicit params
    create_browser_task_from_text() — free-form text (Jarvis/Discord path)
    infer_browser_action_spec()  — text → {action_type, target_url}
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import (
    Priority,
    RiskLevel,
    TaskRecord,
    TaskStatus,
    TriggerType,
    new_id,
    now_iso,
)
from runtime.core.task_store import create_task


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BROWSER_TASK_TYPE = "browser"
BROWSER_EXECUTION_BACKEND = "browser_backend"
BROWSER_ASSIGNED_MODEL = "pinchtab"
BROWSER_ASSIGNED_ROLE = "bowser"

# URL regex — matches http(s):// and bare hostnames like finance.yahoo.com/path
_URL_RE = re.compile(
    r"https?://[^\s\"'<>]+|"
    r"(?:^|\s)((?:www\.|(?:[a-z0-9-]+\.)+[a-z]{2,6})(?:/[^\s\"'<>]*)?)"
)

# Hostname/domain-only patterns (no scheme) - only match if they look like real domains
_HOST_RE = re.compile(r"\b([a-z0-9-]+\.(?:com|org|net|gov|io|finance|xyz)(?:/[^\s\"'<>]*)?)\b")


# ---------------------------------------------------------------------------
# Action inference
# ---------------------------------------------------------------------------

def infer_browser_action_spec(text: str) -> dict[str, str]:
    """Extract {action_type, target_url} from free-form text.

    Returns action_type in the set recognized by PinchTabBackend, and the
    best-guess target_url.  Falls back to action_type="snapshot" and
    target_url="" if nothing can be inferred.
    """
    lower = text.lower()

    # Extract URL — prefer explicit http(s) links
    target_url = ""
    http_match = re.search(r"https?://[^\s\"'<>]+", text)
    if http_match:
        target_url = http_match.group(0).rstrip(".,;)")
    else:
        # Try bare domain
        for m in _HOST_RE.finditer(lower):
            candidate = m.group(1)
            if candidate:
                target_url = "https://" + candidate
                break

    # Infer action_type
    if any(w in lower for w in ("screenshot", "capture", "screengrab")):
        action_type = "screenshot"
    elif any(w in lower for w in ("snapshot", "inspect", "accessibility", "tree")):
        action_type = "snapshot"
    elif any(w in lower for w in ("text", "read", "extract", "content", "scrape", "fetch", "get")):
        action_type = "text"
    elif any(w in lower for w in ("navigate", "open", "goto", "visit", "load")):
        action_type = "navigate_allowlisted_page"
    else:
        # Default: snapshot (reliable, returns accessibility tree)
        action_type = "snapshot"

    return {"action_type": action_type, "target_url": target_url}


# ---------------------------------------------------------------------------
# Task creation
# ---------------------------------------------------------------------------

def create_browser_task(
    *,
    action_type: str,
    target_url: str,
    target_selector: str = "",
    action_params: Optional[dict[str, Any]] = None,
    actor: str,
    lane: str,
    source_channel: str = "browser",
    source_message_id: str = "",
    source_user: str = "",
    task_id: Optional[str] = None,
    parent_task_id: Optional[str] = None,
    priority: str = Priority.NORMAL.value,
    autonomy_mode: str = "step_mode",
    root: Optional[Path] = None,
) -> TaskRecord:
    """Create a browser TaskRecord directly (no LLM routing).

    The normalized_request is set to a JSON browser action spec, which
    execute_once passes as the messages content to bowser_adapter.
    """
    tid = task_id or new_id("task")
    spec = {
        "action_type": action_type,
        "target_url": target_url,
        "target_selector": target_selector,
        "action_params": dict(action_params or {}),
        "execute": True,
    }
    normalized = json.dumps(spec)
    human_summary = f"Browse {target_url} ({action_type})"

    record = TaskRecord(
        task_id=tid,
        created_at=now_iso(),
        updated_at=now_iso(),
        source_lane=lane,
        source_channel=source_channel,
        source_message_id=source_message_id or new_id("msg"),
        source_user=source_user or actor,
        trigger_type=TriggerType.EXPLICIT_TASK_COLON.value,
        raw_request=human_summary,
        normalized_request=normalized,
        task_type=BROWSER_TASK_TYPE,
        priority=priority,
        risk_level=RiskLevel.NORMAL.value,
        status=TaskStatus.QUEUED.value,
        assigned_role=BROWSER_ASSIGNED_ROLE,
        assigned_model=BROWSER_ASSIGNED_MODEL,
        backend_assignment_id=new_id("bassign"),
        execution_backend=BROWSER_EXECUTION_BACKEND,
        backend_metadata={
            "routing_policy": "browser_direct",
            "routing": {
                "routing_request_id": None,
                "routing_decision_id": None,
                "provider_id": "browser",
                "model_name": BROWSER_ASSIGNED_MODEL,
                "workload_type": BROWSER_TASK_TYPE,
                "required_capabilities": ["browser_automation"],
            },
        },
        review_required=False,
        approval_required=False,
        autonomy_mode=autonomy_mode,
        parent_task_id=parent_task_id,
    )
    return create_task(record, root=root)


def run_browser_task(
    *,
    action_type: str,
    target_url: str,
    target_selector: str = "",
    action_params: Optional[dict[str, Any]] = None,
    actor: str = "jarvis",
    lane: str = "browser",
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Create a browser task and immediately execute it, returning the full result.

    This is the preferred call surface for Jarvis and orchestration code that
    want a browser result *now* without worrying about queue ordering.

    The task is created with a unique task_id so it can be targeted by the
    executor's `task_id` param, bypassing any other queued work.

    Returns a dict with:
      task_id, status, final_outcome, artifact_id (if written),
      browser_result (full gateway result), dispatch_result
    """
    from runtime.executor.execute_once import execute_once

    resolved_root = Path(root or ROOT).resolve()

    record = create_browser_task(
        action_type=action_type,
        target_url=target_url,
        target_selector=target_selector,
        action_params=action_params,
        actor=actor,
        lane=lane,
        root=resolved_root,
    )

    exec_result = execute_once(
        root=resolved_root,
        actor=actor,
        lane=lane,
        allow_parallel=True,
        task_id=record.task_id,
    )

    dispatch = exec_result.get("dispatch_result") or {}
    finish = exec_result.get("finish_result") or {}
    return {
        "task_id": record.task_id,
        "status": finish.get("status", "unknown"),
        "final_outcome": finish.get("final_outcome", ""),
        "artifact_id": finish.get("artifact_id"),
        "artifact_result": exec_result.get("artifact_result"),
        "browser_result": dispatch.get("browser_action_result", {}),
        "dispatch_result": dispatch,
        "execute_result": exec_result,
    }


def create_browser_task_from_text(
    *,
    text: str,
    actor: str,
    lane: str,
    source_channel: str = "browser",
    source_message_id: str = "",
    parent_task_id: Optional[str] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Parse free-form text and create a browser task.

    Returns the same shape as intake.create_task_from_message() for drop-in
    compatibility.
    """
    spec = infer_browser_action_spec(text)
    if not spec["target_url"]:
        return {
            "kind": "browser_task_refused",
            "ok": False,
            "task_created": False,
            "error": "No URL could be extracted from the request.",
            "text": text,
        }

    record = create_browser_task(
        action_type=spec["action_type"],
        target_url=spec["target_url"],
        actor=actor,
        lane=lane,
        source_channel=source_channel,
        source_message_id=source_message_id,
        source_user=actor,
        parent_task_id=parent_task_id,
        root=root,
    )

    return {
        "kind": "task_created",
        "ok": True,
        "task_created": True,
        "task_id": record.task_id,
        "short_summary": record.raw_request,
        "initial_status": record.status,
        "final_status": record.status,
        "progress_lane": "#tasks",
        "review_expected": record.review_required,
        "approval_expected": record.approval_required,
        "task_type": record.task_type,
        "priority": record.priority,
        "risk_level": record.risk_level,
        "assigned_model": record.assigned_model,
        "execution_backend": record.execution_backend,
        "browser_action_spec": json.loads(record.normalized_request),
    }
