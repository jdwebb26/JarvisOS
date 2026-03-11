#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.controls.control_store import assert_control_allows
from runtime.core.models import DesktopActionRequestRecord, new_id, now_iso
from runtime.desktop.executor import execute_desktop_action, save_desktop_action_request
from runtime.desktop.policy import evaluate_desktop_action


def handle_desktop_action(
    *,
    task_id,
    actor,
    lane,
    action_type,
    target_app="",
    target_path="",
    action_params=None,
    execute=False,
    root=None,
) -> dict:
    resolved_root = Path(root or ROOT).resolve()
    assert_control_allows(
        action="desktop_action",
        root=resolved_root,
        task_id=task_id,
        subsystem="desktop_executor",
        actor=actor,
        lane=lane,
    )
    policy = evaluate_desktop_action(
        action_type,
        target_app=target_app,
        target_path=target_path,
        action_params=action_params,
        root=resolved_root,
    )
    status = "blocked" if not policy["allowed"] else ("pending_review" if policy["review_required"] else "accepted")
    request = save_desktop_action_request(
        DesktopActionRequestRecord(
            request_id=new_id("dreq"),
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            action_type=action_type,
            target_app=target_app,
            target_path=target_path,
            action_params=dict(action_params or {}),
            risk_tier=policy["risk_tier"],
            review_required=bool(policy["review_required"]),
            status=status,
        ),
        root=resolved_root,
    )

    if not policy["allowed"]:
        return {
            "kind": "blocked",
            "request": request.to_dict(),
            "policy": policy,
            "executed": False,
        }

    if request.review_required:
        return {
            "kind": "pending_review",
            "request": request.to_dict(),
            "policy": policy,
            "executed": False,
        }

    if not execute:
        return {
            "kind": "accepted",
            "request": request.to_dict(),
            "policy": policy,
            "executed": False,
        }

    result = execute_desktop_action(request, root=resolved_root)
    return {
        "kind": "executed",
        "request": request.to_dict(),
        "policy": policy,
        "result": result.to_dict(),
        "executed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Thin gateway for bounded desktop action orchestration.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="desktop", help="Lane name")
    parser.add_argument("--action-type", required=True, help="Desktop action type")
    parser.add_argument("--target-app", default="", help="Target app")
    parser.add_argument("--target-path", default="", help="Target path")
    parser.add_argument("--action-params-json", default="", help="Inline JSON action params")
    parser.add_argument("--execute", action="store_true", help="Execute accepted action via stub executor")
    args = parser.parse_args()

    result = handle_desktop_action(
        task_id=args.task_id,
        actor=args.actor,
        lane=args.lane,
        action_type=args.action_type,
        target_app=args.target_app,
        target_path=args.target_path,
        action_params=json.loads(args.action_params_json) if args.action_params_json else None,
        execute=args.execute,
        root=Path(args.root).resolve(),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
