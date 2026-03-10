#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import new_id, now_iso
from scripts.operator_action_explain import explain_action
from scripts.operator_action_executor import execute_selected_action
from scripts.operator_checkpoint_action_pack import build_operator_checkpoint_action_pack
from scripts.operator_triage_support import (
    build_reply_plan,
    load_jsons,
    resolve_decision_inbox,
    resolve_newest_valid_pack,
    save_reply_apply_record,
)


def _load_plan(root: Path, plan_id: str) -> dict[str, Any] | None:
    for row in load_jsons(root / "state" / "operator_reply_plans"):
        if row.get("plan_id") == plan_id:
            return row
    return None


def apply_reply(
    root: Path,
    *,
    reply_string: str | None,
    plan_id: str | None,
    dry_run: bool,
    continue_on_failure: bool,
) -> tuple[dict[str, Any], int]:
    inbox, inbox_path = resolve_decision_inbox(root)
    plan = _load_plan(root, plan_id) if plan_id else build_reply_plan(root, reply_string=reply_string or "")
    if plan is None:
        payload = {"ok": False, "error": f"Reply plan not found: {plan_id}"}
        return payload, 1

    pack, pack_path, pack_meta, _ = resolve_newest_valid_pack(root, limit=10)
    reply_apply = {
        "reply_apply_id": new_id("opreplyapply"),
        "source_inbox_path": str(inbox_path),
        "source_inbox_generated_at": inbox.get("generated_at"),
        "source_action_pack_id": (pack or {}).get("action_pack_id"),
        "source_action_pack_validation_status": pack_meta.get("status"),
        "reply_string": reply_string or plan.get("reply_string", ""),
        "plan_id": plan.get("plan_id"),
        "started_at": now_iso(),
        "completed_at": None,
        "ok": True,
        "attempted_count": 0,
        "succeeded_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "per_step_results": [],
        "stop_reason": "",
    }
    if plan.get("unknown_tokens"):
        for token in plan.get("unknown_tokens", []):
            reply_apply["per_step_results"].append({"reply_code": token, "status": "invalid_reply", "reason": "Unknown reply token."})
            reply_apply["failed_count"] += 1
        reply_apply["ok"] = False
        reply_apply["stop_reason"] = "invalid_reply"
        reply_apply["completed_at"] = now_iso()
        save_reply_apply_record(root, reply_apply)
        return reply_apply, 1
    item_by_id = {row.get("inbox_item_id"): row for row in inbox.get("items", [])}
    action_index = (pack or {}).get("action_index", {})

    for step in plan.get("steps", []):
        item = item_by_id.get(step.get("inbox_item_id"))
        if item is None:
            result = {"reply_code": step.get("reply_code"), "status": "plan_blocked", "reason": "Inbox item no longer exists in the current inbox."}
            reply_apply["per_step_results"].append(result)
            reply_apply["failed_count"] += 1
            reply_apply["ok"] = False
            reply_apply["stop_reason"] = "plan_blocked"
            if not continue_on_failure:
                break
            continue

        operation = step.get("planned_operation_kind")
        if operation == "explain":
            payload = explain_action(root, action_id=step.get("action_id"), task_id=step.get("task_id"), execution_id=None, queue_run_id=None, bulk_run_id=None)
            reply_apply["per_step_results"].append({"reply_code": step.get("reply_code"), "status": "explain_only", "payload": payload})
            reply_apply["skipped_count"] += 1
            continue
        if operation == "rebuild_only":
            rebuilt = build_operator_checkpoint_action_pack(root, limit=10)
            reply_apply["per_step_results"].append(
                {
                    "reply_code": step.get("reply_code"),
                    "status": "rebuild_only",
                    "payload": {"action_pack_id": rebuilt["pack"]["action_pack_id"], "json_path": rebuilt["json_path"]},
                }
            )
            reply_apply["skipped_count"] += 1
            continue

        action = action_index.get(step.get("action_id") or "")
        if action is None:
            result = {"reply_code": step.get("reply_code"), "status": "skipped_stale", "reason": "Action no longer exists in the current pack."}
            reply_apply["per_step_results"].append(result)
            reply_apply["skipped_count"] += 1
            continue

        result, exit_code = execute_selected_action(
            root,
            action_id=action["action_id"],
            action=action,
            action_pack_path=pack_path,
            invoked_by="reply_apply",
            dry_run=dry_run,
            force=bool(step.get("requires_force")),
            source_action_pack_id=(pack or {}).get("action_pack_id"),
            source_action_pack_fingerprint=(pack or {}).get("action_pack_fingerprint"),
            source_action_pack_validation_status=pack_meta.get("status", "valid"),
            source_action_pack_resolution=pack_meta.get("resolution", "current"),
            source_action_pack_rebuild_reason=pack_meta.get("rebuild_reason") or "",
            source_action_pack_requested_explicit=bool(pack_meta.get("requested_explicit")),
        )
        reply_apply["attempted_count"] += 1
        if result.get("ok") and exit_code == 0:
            reply_apply["succeeded_count"] += 1
            status = "executed" if not dry_run else "executed"
        else:
            reply_apply["failed_count"] += 1
            reply_apply["ok"] = False
            failure_kind = ((result.get("failure") or {}).get("kind") or (result.get("execution_record") or {}).get("failure_kind") or "failed_execution")
            status = {
                "already_executed": "skipped_idempotency",
                "stale_action": "skipped_stale",
            }.get(failure_kind, "failed_execution")
            reply_apply["stop_reason"] = failure_kind
            if not continue_on_failure:
                reply_apply["per_step_results"].append({"reply_code": step.get("reply_code"), "status": status, "payload": result})
                break
        reply_apply["per_step_results"].append({"reply_code": step.get("reply_code"), "status": status, "payload": result})

    reply_apply["completed_at"] = now_iso()
    save_reply_apply_record(root, reply_apply)
    return reply_apply, 0 if reply_apply["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a compact operator reply string or saved reply plan through existing wrappers.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--reply", default="", help='Reply string such as "A1 X2"')
    parser.add_argument("--plan-id", default="", help="Saved plan id to apply")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-failure", action="store_true")
    args = parser.parse_args()

    payload, exit_code = apply_reply(
        Path(args.root).resolve(),
        reply_string=args.reply or None,
        plan_id=args.plan_id or None,
        dry_run=args.dry_run,
        continue_on_failure=args.continue_on_failure,
    )
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
