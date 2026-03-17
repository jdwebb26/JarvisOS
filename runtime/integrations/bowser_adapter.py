#!/usr/bin/env python3
"""bowser_adapter — browser backend adapter for the OpenClaw task executor.

Bridges the generic backend_dispatch messages interface to the live
PinchTab browser backend via handle_browser_action().

Message protocol:
    The last message in the messages list should contain a JSON payload
    (either bare JSON or a JSON code block) with the browser action spec:

        {
            "action_type":     str,   # required
            "target_url":      str,   # required
            "target_selector": str,   # optional
            "action_params":   dict,  # optional
            "execute":         bool   # optional (default true)
        }

Direct API:
    run_bowser_browser_action() accepts explicit keyword args and is the
    preferred call surface for Jarvis / orchestration code.

Health probe:
    probe_bowser_runtime() checks PinchTab availability without side-effects.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.gateway.browser_action import handle_browser_action
from runtime.core.agent_status_store import update_agent_status
from runtime.core.backend_result_store import save_backend_result
from runtime.core.discord_event_router import emit_event as _route_event


BOWSER_BACKEND_ID = "browser_backend"
SUCCESS_STATUS = "completed"
FAILED_STATUS = "failed"
INVALID_REQUEST_STATUS = "invalid_request"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_browser_spec(messages: list[dict[str, str]]) -> dict[str, Any] | None:
    """Extract a browser action spec from the last message that contains one."""
    for msg in reversed(messages):
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        # Bare JSON
        try:
            payload = json.loads(content)
            if isinstance(payload, dict) and "action_type" in payload and "target_url" in payload:
                return payload
        except (json.JSONDecodeError, ValueError):
            pass
        # JSON inside a markdown code block
        for marker in ("```json", "```"):
            idx = content.find(marker)
            if idx == -1:
                continue
            start = idx + len(marker)
            end = content.find("```", start)
            if end > start:
                try:
                    payload = json.loads(content[start:end].strip())
                    if isinstance(payload, dict) and "action_type" in payload and "target_url" in payload:
                        return payload
                except (json.JSONDecodeError, ValueError):
                    pass
    return None


# ---------------------------------------------------------------------------
# Backend dispatch adapter (messages interface)
# ---------------------------------------------------------------------------

def execute_bowser_action(
    *,
    task_id: str,
    actor: str,
    lane: str,
    messages: list[dict[str, str]],
    routing_decision_id: Optional[str] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Backend dispatch adapter: parse browser spec from messages and execute.

    Conforms to the backend_dispatch adapter signature:
        (task_id, actor, lane, messages, *, routing_decision_id, root) -> dict
    """
    spec = _parse_browser_spec(messages)
    if spec is None:
        return {
            "status": INVALID_REQUEST_STATUS,
            "content": "",
            "usage": {},
            "error": (
                "bowser_adapter: no valid browser action spec found in messages. "
                "Last message must contain JSON with 'action_type' and 'target_url'."
            ),
            "execution_backend": BOWSER_BACKEND_ID,
            "dispatched": True,
            "request_id": None,
            "result_id": None,
        }

    action_type = str(spec.get("action_type", "")).strip()
    target_url = str(spec.get("target_url", "")).strip()
    target_selector = str(spec.get("target_selector", ""))
    action_params = dict(spec.get("action_params") or {})
    execute = bool(spec.get("execute", True))

    gateway_result = handle_browser_action(
        task_id=task_id,
        actor=actor,
        lane=lane,
        action_type=action_type,
        target_url=target_url,
        target_selector=target_selector,
        action_params=action_params,
        execute=execute,
        root=root,
    )

    kind = gateway_result.get("kind", "")

    if kind == "executed":
        backend_res = gateway_result.get("result", {})
        ok = backend_res.get("status") == "ok"
        status = SUCCESS_STATUS if ok else FAILED_STATUS
        content = backend_res.get("outcome_summary", "")
        error = backend_res.get("error") or ""
    elif kind == "accepted":
        status = SUCCESS_STATUS
        content = f"Browser action accepted (execute=False): {action_type} -> {target_url}"
        error = ""
    elif kind == "blocked":
        policy = gateway_result.get("policy", {})
        status = FAILED_STATUS
        content = ""
        error = f"Browser action blocked by policy: {policy.get('reason', 'unknown')}"
    elif kind == "pending_review":
        status = FAILED_STATUS
        content = ""
        error = f"Browser action requires review: {action_type} -> {target_url}"
    else:
        status = FAILED_STATUS
        content = ""
        error = f"Unexpected browser action result kind: {kind!r}"

    request_record = gateway_result.get("request") or {}
    result_record = gateway_result.get("result") or {}
    result_id = result_record.get("result_id", "")

    # --- Local truth stores + Discord event routing ---
    try:
        headline = (
            f"Bowser completed browser action on {target_url}."
            if status == SUCCESS_STATUS
            else f"Bowser FAILED browser action on {target_url}."
        )
        update_agent_status(
            "bowser",
            headline,
            state="idle" if status == SUCCESS_STATUS else "error",
            current_task_id=task_id,
            last_result=content or error,
            root=root,
        )
        bk_status = "ok" if status == SUCCESS_STATUS else "error"
        summary = (
            f"Browser {action_type} on {target_url}: "
            + (content or error or kind)
        )
        save_backend_result(
            task_id=task_id,
            agent_id="bowser",
            backend="browser_backend",
            status=bk_status,
            summary=summary,
            artifact_refs={
                "result_id": result_id,
                "request_id": request_record.get("request_id", ""),
            },
            error=error,
            root=root,
        )
        _route_event(
            "browser_result",
            "bowser",
            task_id=task_id,
            target=target_url,
            detail=(content or error or kind),
            root=root,
        )
    except Exception:  # never break the browser action itself
        pass

    return {
        "status": status,
        "content": content,
        "usage": {},
        "error": error,
        "execution_backend": BOWSER_BACKEND_ID,
        "dispatched": True,
        "kind": kind,
        "request_id": request_record.get("request_id"),
        "result_id": result_id,
        "browser_action_result": gateway_result,
    }


# ---------------------------------------------------------------------------
# Direct orchestration API (preferred for Jarvis / agent code)
# ---------------------------------------------------------------------------

def run_bowser_browser_action(
    *,
    task_id: str,
    actor: str,
    lane: str,
    action_type: str,
    target_url: str,
    target_selector: str = "",
    action_params: Optional[dict[str, Any]] = None,
    execute: bool = True,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Direct API: trigger a browser action without the messages wrapping.

    Preferred call surface for Jarvis and orchestration code.  Accepts explicit
    browser params and returns the same structured result as execute_bowser_action.
    """
    return execute_bowser_action(
        task_id=task_id,
        actor=actor,
        lane=lane,
        messages=[
            {
                "role": "user",
                "content": json.dumps({
                    "action_type": action_type,
                    "target_url": target_url,
                    "target_selector": target_selector,
                    "action_params": action_params or {},
                    "execute": execute,
                }),
            }
        ],
        root=root,
    )


# ---------------------------------------------------------------------------
# Health probe
# ---------------------------------------------------------------------------

def probe_bowser_runtime(*, root: Optional[Path] = None) -> dict[str, Any]:  # noqa: ARG001
    """Probe PinchTab health without side-effects."""
    from runtime.browser.backends.pinchtab import PinchTabBackend
    try:
        health = PinchTabBackend().health_check()
        return {
            "reachable": health.get("status") == "ok",
            "status": health.get("status", "unknown"),
            "version": health.get("version"),
            "instances": health.get("instances"),
            "error": None,
        }
    except Exception as exc:
        return {
            "reachable": False,
            "status": "error",
            "version": None,
            "instances": None,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bowser browser backend adapter (direct CLI).",
    )
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", default="", help="Task id")
    parser.add_argument("--actor", default="jarvis", help="Actor name")
    parser.add_argument("--lane", default="browser", help="Lane name")
    parser.add_argument("--action-type", default="", help="Browser action type")
    parser.add_argument("--target-url", default="", help="Target URL")
    parser.add_argument("--target-selector", default="", help="CSS/accessibility selector")
    parser.add_argument("--action-params-json", default="", help="Inline JSON action params")
    parser.add_argument("--execute", action="store_true", default=True,
                        help="Execute the accepted action (default: true)")
    parser.add_argument("--no-execute", dest="execute", action="store_false",
                        help="Accept but do not execute")
    parser.add_argument("--probe", action="store_true",
                        help="Probe PinchTab health and exit")
    args = parser.parse_args()

    resolved_root = Path(args.root).resolve()

    if args.probe:
        print(json.dumps(probe_bowser_runtime(root=resolved_root), indent=2))
        return 0

    if not args.task_id or not args.action_type or not args.target_url:
        parser.error("--task-id, --action-type, and --target-url are required unless --probe")

    result = run_bowser_browser_action(
        task_id=args.task_id,
        actor=args.actor,
        lane=args.lane,
        action_type=args.action_type,
        target_url=args.target_url,
        target_selector=args.target_selector,
        action_params=json.loads(args.action_params_json) if args.action_params_json else None,
        execute=args.execute,
        root=resolved_root,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == SUCCESS_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
