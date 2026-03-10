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
from scripts.operator_action_executor import execute_selected_action, revalidate_selected_action
from scripts.operator_action_ledger import latest_successful_action_for_action_id
from scripts.operator_triage_support import (
    build_task_intervention_summaries,
    load_current_action_pack_summary,
    resolve_newest_valid_pack,
    save_task_intervention_record,
)


def _select_action(pack: dict[str, Any], *, task_id: str) -> dict[str, Any] | None:
    action_index = pack.get("action_index", {})
    recommended = next((row for row in pack.get("recommended_execution_order", []) if row.get("task_id") == task_id), None)
    if recommended:
        action = action_index.get(recommended.get("action_id"))
        if action:
            return action
    for action in action_index.values():
        if action.get("task_id") == task_id:
            return action
    return None


def intervene_on_task(
    root: Path,
    *,
    task_id: str,
    dry_run: bool = False,
    force: bool = False,
    action_pack_path: Path | None = None,
    prefer_recorded_pack: bool = False,
    limit: int = 10,
) -> tuple[dict[str, Any], int]:
    pack_override = action_pack_path
    if prefer_recorded_pack:
        interventions = build_task_intervention_summaries(root, pack=None, task_limit=100)
        summary = next((row for row in interventions if row.get("task_id") == task_id), None)
        last_failure = (summary or {}).get("latest_failed_operator_action") or {}
        if last_failure.get("source_action_pack_requested_explicit") and last_failure.get("source_action_pack_path"):
            pack_override = Path(str(last_failure["source_action_pack_path"]))

    pack, pack_path, pack_meta, pack_error = resolve_newest_valid_pack(root, limit=limit) if pack_override is None else __import__(
        "scripts.operator_checkpoint_action_pack", fromlist=["resolve_action_pack"]
    ).resolve_action_pack(root, explicit_pack_path=pack_override, limit=limit)
    if pack is None or pack_error is not None:
        record = {
            "intervention_id": new_id("opint"),
            "task_id": task_id,
            "dry_run": dry_run,
            "selected_action_id": None,
            "selected_command": "",
            "blocker_summary": [pack_error or "Unable to load a valid action pack."],
            "source_action_pack_path": str(pack_path),
            "source_action_pack_id": None,
            "source_action_pack_fingerprint": None,
            "source_action_pack_validation_status": pack_meta.get("status", "malformed"),
            "started_at": now_iso(),
            "completed_at": now_iso(),
            "ok": False,
            "execution_record_id": None,
        }
        save_task_intervention_record(root, record)
        return {
            "ok": False,
            "task_id": task_id,
            "failure": {"kind": "invalid_action_pack", "error": pack_error or "Unable to load action pack."},
            "intervention_record": record,
        }, 1

    task_summary = next((row for row in build_task_intervention_summaries(root, pack=pack, task_limit=100) if row.get("task_id") == task_id), None)
    action = _select_action(pack, task_id=task_id)
    blockers: list[str] = []
    open_manual_blockers = list((task_summary or {}).get("open_manual_blockers", []))
    current_pack = load_current_action_pack_summary(root)

    if action is None:
        blockers.append("no_action_in_current_pack")
        record = {
            "intervention_id": new_id("opint"),
            "task_id": task_id,
            "dry_run": dry_run,
            "selected_action_id": None,
            "selected_command": "",
            "blocker_summary": blockers,
            "source_action_pack_path": str(pack_path),
            "source_action_pack_id": pack.get("action_pack_id"),
            "source_action_pack_fingerprint": pack.get("action_pack_fingerprint"),
            "source_action_pack_validation_status": pack_meta.get("status", "valid"),
            "started_at": now_iso(),
            "completed_at": now_iso(),
            "ok": False,
            "execution_record_id": None,
        }
        save_task_intervention_record(root, record)
        return {
            "ok": False,
            "task_id": task_id,
            "intervention_summary": task_summary,
            "suggested_action_ids": [],
            "suggested_commands": [],
            "blockers_preventing_safe_execution": blockers,
            "open_manual_blockers": open_manual_blockers,
            "should_rebuild_pack_first": current_pack.get("status") != "valid",
            "intervention_record": record,
        }, 1

    suggested_action_ids = [action["action_id"]]
    suggested_commands = [action["command"]["command"]]

    if not dry_run and not force:
        previous_success = latest_successful_action_for_action_id(root, action["action_id"])
        if previous_success is not None:
            blockers.append("already_executed")

    still_applicable, _, stale_reason = revalidate_selected_action(root, action=action)
    if not still_applicable:
        blockers.append(stale_reason)

    record = {
        "intervention_id": new_id("opint"),
        "task_id": task_id,
        "dry_run": dry_run,
        "selected_action_id": action["action_id"],
        "selected_command": action["command"]["command"],
        "blocker_summary": blockers,
        "source_action_pack_path": str(pack_path),
        "source_action_pack_id": pack.get("action_pack_id"),
        "source_action_pack_fingerprint": pack.get("action_pack_fingerprint"),
        "source_action_pack_validation_status": pack_meta.get("status", "valid"),
        "started_at": now_iso(),
        "completed_at": None,
        "ok": False,
        "execution_record_id": None,
    }

    if blockers and not dry_run:
        record["completed_at"] = now_iso()
        save_task_intervention_record(root, record)
        return {
            "ok": False,
            "task_id": task_id,
            "intervention_summary": task_summary,
            "suggested_action_ids": suggested_action_ids,
            "suggested_commands": suggested_commands,
            "blockers_preventing_safe_execution": blockers,
            "open_manual_blockers": open_manual_blockers,
            "should_rebuild_pack_first": current_pack.get("status") != "valid",
            "intervention_record": record,
        }, 1

    result, exit_code = execute_selected_action(
        root,
        action_id=action["action_id"],
        action=action,
        action_pack_path=pack_path,
        invoked_by="intervene",
        dry_run=dry_run,
        force=force,
        source_action_pack_id=pack.get("action_pack_id"),
        source_action_pack_fingerprint=pack.get("action_pack_fingerprint"),
        source_action_pack_validation_status=pack_meta.get("status", "valid"),
        source_action_pack_resolution=pack_meta.get("resolution", "current"),
        source_action_pack_rebuild_reason=pack_meta.get("rebuild_reason") or "",
        source_action_pack_requested_explicit=bool(pack_meta.get("requested_explicit")),
    )
    record["completed_at"] = now_iso()
    record["ok"] = bool(result.get("ok"))
    record["execution_record_id"] = (result.get("execution_record") or {}).get("execution_id")
    save_task_intervention_record(root, record)

    payload = {
        "ok": bool(result.get("ok")),
        "task_id": task_id,
        "intervention_summary": task_summary,
        "suggested_action_ids": suggested_action_ids,
        "suggested_commands": suggested_commands,
        "blockers_preventing_safe_execution": blockers,
        "open_manual_blockers": open_manual_blockers,
        "should_rebuild_pack_first": current_pack.get("status") != "valid",
        "intervention_record": record,
        "execution": result,
    }
    return payload, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect one task and optionally execute one bounded operator intervention.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id to inspect")
    parser.add_argument("--dry-run", action="store_true", help="Resolve the intervention without executing it")
    parser.add_argument("--force", action="store_true", help="Allow re-execution even if the action already succeeded")
    parser.add_argument("--action-pack-path", default="", help="Explicit pinned action-pack path to use")
    parser.add_argument(
        "--prefer-recorded-pack",
        action="store_true",
        help="Prefer the task's latest explicitly pinned action-pack provenance when available",
    )
    parser.add_argument("--action-pack-limit", type=int, default=10, help="Implicit action-pack rebuild limit if needed")
    args = parser.parse_args()

    payload, exit_code = intervene_on_task(
        Path(args.root).resolve(),
        task_id=args.task_id,
        dry_run=args.dry_run,
        force=args.force,
        action_pack_path=Path(args.action_pack_path).resolve() if args.action_pack_path else None,
        prefer_recorded_pack=args.prefer_recorded_pack,
        limit=args.action_pack_limit,
    )
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
