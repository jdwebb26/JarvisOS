#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.browser.backends.pinchtab import PinchTabBackend
from runtime.browser.protocol import complete_browser_action, request_browser_action
from runtime.browser.tracing import save_browser_snapshot, save_browser_trace
from runtime.core.task_events import append_event, make_event


def handle_browser_action(
    *,
    task_id: str,
    actor: str,
    lane: str,
    action_type: str,
    target_url: str,
    target_selector: str = "",
    action_params: Optional[dict[str, Any]] = None,
    execute: bool = False,
    backend: str = "pinchtab",
    root: Optional[Path] = None,
) -> dict[str, Any]:
    resolved_root = Path(root or ROOT).resolve()
    request_payload = request_browser_action(
        task_id=task_id,
        actor=actor,
        lane=lane,
        action_type=action_type,
        target_url=target_url,
        target_selector=target_selector,
        action_params=action_params,
        root=resolved_root,
    )
    request = request_payload["request"]
    policy = request_payload["policy"]

    append_event(
        make_event(
            task_id=task_id,
            event_type="browser_action_requested",
            actor=actor,
            lane=lane,
            checkpoint_summary=f"Browser action requested: {action_type}",
            reason=policy["reason"],
            execution_backend=backend,
        ),
        root=resolved_root,
    )

    if not policy["allowed"]:
        return {
            "kind": "blocked",
            "request": request,
            "policy": policy,
            "executed": False,
        }

    if request["review_required"]:
        append_event(
            make_event(
                task_id=task_id,
                event_type="browser_action_pending_review",
                actor=actor,
                lane=lane,
                checkpoint_summary=f"Browser action pending review: {action_type}",
                reason="review_required",
                execution_backend=backend,
            ),
            root=resolved_root,
        )
        return {
            "kind": "pending_review",
            "request": request,
            "policy": policy,
            "executed": False,
        }

    if not execute:
        return {
            "kind": "accepted",
            "request": request,
            "policy": policy,
            "executed": False,
        }

    if backend != "pinchtab":
        raise ValueError(f"Unsupported browser backend: {backend}")

    backend_impl = PinchTabBackend()
    backend_result = backend_impl.execute_action(
        type(
            "BrowserActionRequestShim",
            (),
            {
                "request_id": request["request_id"],
                "task_id": request["task_id"],
                "actor": request["actor"],
                "lane": request["lane"],
            },
        )()
    )

    snapshot = save_browser_snapshot(
        task_id=task_id,
        actor=actor,
        lane=lane,
        snapshot_kind="browser_action_stub_snapshot",
        payload={
            "target_url": target_url,
            "action_type": action_type,
            "backend": backend,
            "status": backend_result.status,
        },
        request_id=request["request_id"],
        root=resolved_root,
    )
    trace = save_browser_trace(
        task_id=task_id,
        actor=actor,
        lane=lane,
        trace_kind="browser_action_stub_trace",
        steps=[
            {
                "step": "request_accepted",
                "action_type": action_type,
                "target_url": target_url,
                "risk_tier": request["risk_tier"],
            },
            {
                "step": "stub_backend_execute",
                "backend": backend,
                "status": backend_result.status,
                "error": backend_result.error,
            },
        ],
        request_id=request["request_id"],
        snapshot_refs={"after": snapshot["snapshot_id"]},
        root=resolved_root,
    )
    completion = complete_browser_action(
        request_id=request["request_id"],
        actor=actor,
        lane=lane,
        status=backend_result.status,
        outcome_summary=backend_result.outcome_summary,
        snapshot_refs={"after": snapshot["snapshot_id"]},
        trace_refs={"trace_id": trace["trace_id"]},
        error=backend_result.error,
        root=resolved_root,
    )

    append_event(
        make_event(
            task_id=task_id,
            event_type="browser_action_executed",
            actor=actor,
            lane=lane,
            checkpoint_summary=f"Browser action executed via {backend}",
            reason=backend_result.error or backend_result.outcome_summary,
            execution_backend=backend,
            backend_run_id=completion["result"]["result_id"],
        ),
        root=resolved_root,
    )

    return {
        "kind": "executed",
        "request": completion["request"],
        "policy": policy,
        "result": completion["result"],
        "trace": trace,
        "snapshot": snapshot,
        "executed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Thin gateway for bounded browser action orchestration.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="browser", help="Lane name")
    parser.add_argument("--action-type", required=True, help="Browser action type")
    parser.add_argument("--target-url", required=True, help="Target URL")
    parser.add_argument("--target-selector", default="", help="Target selector")
    parser.add_argument("--action-params-json", default="", help="Inline JSON action params")
    parser.add_argument("--execute", action="store_true", help="Execute accepted action via stub backend")
    parser.add_argument("--backend", default="pinchtab", help="Backend name")
    args = parser.parse_args()

    result = handle_browser_action(
        task_id=args.task_id,
        actor=args.actor,
        lane=args.lane,
        action_type=args.action_type,
        target_url=args.target_url,
        target_selector=args.target_selector,
        action_params=json.loads(args.action_params_json) if args.action_params_json else None,
        execute=args.execute,
        backend=args.backend,
        root=Path(args.root).resolve(),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
