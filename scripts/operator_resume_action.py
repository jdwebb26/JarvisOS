#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_action_executor import execute_selected_action
from scripts.operator_checkpoint_action_pack import resolve_action_pack
from scripts.operator_action_ledger import (
    latest_action_by_category,
    latest_action_for_task,
    latest_failed_action_for_task,
    latest_successful_action_for_task,
    list_operator_action_executions,
)


def _select_record(
    root: Path,
    *,
    task_id: str | None,
    category: str | None,
    replay_success: bool,
) -> dict | None:
    if task_id:
        if replay_success:
            return latest_successful_action_for_task(root, task_id)
        failed = list_operator_action_executions(root, task_id=task_id, category=category, success=False)
        if failed:
            return failed[0]
        dry_runs = list_operator_action_executions(root, task_id=task_id, category=category, dry_run=True)
        if dry_runs:
            return dry_runs[0]
        return latest_action_for_task(root, task_id)

    if category:
        if replay_success:
            successful = list_operator_action_executions(root, category=category, success=True)
            return successful[0] if successful else None
        failed = list_operator_action_executions(root, category=category, success=False)
        if failed:
            return failed[0]
        dry_runs = list_operator_action_executions(root, category=category, dry_run=True)
        if dry_runs:
            return dry_runs[0]
        return latest_action_by_category(root, category)

    rows = list_operator_action_executions(root, success=True if replay_success else None)
    if replay_success:
        return rows[0] if rows else None
    failed = [row for row in rows if row.get("failure")]
    if failed:
        return failed[0]
    dry_runs = [row for row in rows if row.get("dry_run")]
    if dry_runs:
        return dry_runs[0]
    return rows[0] if rows else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume or replay a recorded operator action from the execution ledger.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", default="", help="Task id selector")
    parser.add_argument("--category", default="", help="Action category selector")
    parser.add_argument(
        "--replay-success",
        action="store_true",
        help="Replay the latest successful action instead of preferring failed/dry-run records.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Resolve the recorded action but do not execute it")
    parser.add_argument("--force", action="store_true", help="Re-execute even if the action already has a successful record")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    record = _select_record(
        root,
        task_id=args.task_id or None,
        category=args.category or None,
        replay_success=args.replay_success,
    )
    if record is None:
        payload = {
            "ok": False,
            "error": "No matching operator action execution record found.",
            "selectors": {
                "task_id": args.task_id or None,
                "category": args.category or None,
                "replay_success": args.replay_success,
            },
        }
        print(json.dumps(payload, indent=2))
        return 1

    selected_action = record.get("selected_action")
    if not selected_action:
        payload = {
            "ok": False,
            "error": "Selected execution record does not contain replayable action metadata.",
            "matched_record": record,
        }
        print(json.dumps(payload, indent=2))
        return 1

    source_action_pack_path = Path(record["source_action_pack_path"])
    source_action_pack_id = record.get("source_action_pack_id")
    source_action_pack_fingerprint = record.get("source_action_pack_fingerprint")
    if record.get("source_action_pack_requested_explicit"):
        pack, _, pack_meta, pack_error = resolve_action_pack(
            root,
            limit=10,
            explicit_pack_path=source_action_pack_path,
            expected_action_pack_id=source_action_pack_id,
            expected_action_pack_fingerprint=source_action_pack_fingerprint,
            allow_rebuild=False,
        )
    else:
        pack, _, pack_meta, pack_error = resolve_action_pack(root, limit=10)
    if pack_error is not None or pack is None:
        payload = {
            "ok": False,
            "error": pack_error or "Unable to validate recorded source action pack.",
            "failure": {
                "kind": "expired_pack" if pack_meta.get("status") == "expired" else "pinned_pack_validation_failed",
                "error": pack_error or "Unable to validate recorded source action pack.",
            },
            "action_pack_validation": pack_meta,
            "matched_record": record,
        }
        print(json.dumps(payload, indent=2))
        return 1

    payload, exit_code = execute_selected_action(
        root,
        action_id=record["action_id"],
        action=selected_action,
        action_pack_path=source_action_pack_path,
        invoked_by="resume",
        dry_run=args.dry_run,
        force=args.force,
        source_action_pack_id=pack.get("action_pack_id"),
        source_action_pack_fingerprint=pack.get("action_pack_fingerprint"),
        source_action_pack_validation_status=pack_meta.get("status", "valid"),
        source_action_pack_resolution=pack_meta.get("resolution", "pinned"),
        source_action_pack_rebuild_reason=pack_meta.get("rebuild_reason") or "",
        source_action_pack_requested_explicit=bool(pack_meta.get("requested_explicit")),
    )
    payload["resumed_from_execution_id"] = record["execution_id"]
    payload["action_pack_validation"] = pack_meta
    payload["selectors"] = {
        "task_id": args.task_id or None,
        "category": args.category or None,
        "replay_success": args.replay_success,
    }
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
