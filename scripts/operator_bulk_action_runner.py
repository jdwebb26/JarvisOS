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
from scripts.operator_checkpoint_action_pack import resolve_action_pack
from scripts.operator_queue_runner import _evaluate_policy


def operator_bulk_runs_dir(root: Path) -> Path:
    path = root / "state" / "operator_bulk_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_bulk_run(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_bulk_runs_dir(root) / f"{record['bulk_run_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def _ordered_action_ids(pack: dict[str, Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for row in pack.get("recommended_execution_order", []):
        action_id = row.get("action_id")
        if action_id and action_id not in seen:
            ordered.append(action_id)
            seen.add(action_id)
    for action_id in sorted((pack.get("action_index") or {}).keys()):
        if action_id not in seen:
            ordered.append(action_id)
            seen.add(action_id)
    return ordered


def _select_actions(
    pack: dict[str, Any],
    *,
    category: str | None,
    task_id: str | None,
    action_id_prefix: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    action_index = pack.get("action_index", {})
    for action_id in _ordered_action_ids(pack):
        action = action_index.get(action_id)
        if not action:
            continue
        if category and action.get("category") != category:
            continue
        if task_id and action.get("task_id") != task_id:
            continue
        if action_id_prefix and not str(action_id).startswith(action_id_prefix):
            continue
        rows.append(action)
    if limit is not None:
        rows = rows[:limit]
    return rows


def run_bulk(
    root: Path,
    *,
    category: str | None = None,
    task_id: str | None = None,
    action_id_prefix: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    continue_on_failure: bool = False,
    force: bool = False,
    action_pack_limit: int = 10,
) -> tuple[dict[str, Any], int]:
    pack, pack_path, pack_meta, pack_error = resolve_action_pack(root, limit=action_pack_limit)
    if pack_error is not None or pack is None:
        payload = {
            "ok": False,
            "error": pack_error or "Unable to load action pack.",
            "source_action_pack_path": str(pack_path),
            "pack_validation_status": pack_meta.get("status"),
            "action_pack_validation": pack_meta,
        }
        return payload, 1

    bulk_run = {
        "bulk_run_id": new_id("opbulk"),
        "source_action_pack_path": str(pack_path),
        "source_action_pack_id": pack.get("action_pack_id"),
        "source_action_pack_fingerprint": pack.get("action_pack_fingerprint"),
        "pack_validation_status": pack_meta.get("status", "valid"),
        "pack_resolution": pack_meta.get("resolution", "current"),
        "pack_rebuild_reason": pack_meta.get("rebuild_reason") or "",
        "started_at": now_iso(),
        "completed_at": None,
        "selectors": {
            "category": category,
            "task_id": task_id,
            "action_id_prefix": action_id_prefix,
            "limit": limit,
            "dry_run": dry_run,
            "continue_on_failure": continue_on_failure,
            "force": force,
        },
        "ok": True,
        "attempted_count": 0,
        "succeeded_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "stop_reason": "",
        "per_action_results": [],
        "executed_actions": [],
        "skipped_actions": [],
    }

    selected = _select_actions(
        pack,
        category=category,
        task_id=task_id,
        action_id_prefix=action_id_prefix,
        limit=limit,
    )
    for action in selected:
        action_id = action["action_id"]
        allowed, policy_reason = _evaluate_policy(
            action,
            allow_categories={"pending_review"},
            deny_categories=set(),
            allow_approval=False,
            allow_ship=False,
        )
        if not allowed:
            skipped = {
                "action_id": action_id,
                "category": action.get("category"),
                "task_id": action.get("task_id"),
                "allowed": False,
                "skip_kind": "policy",
                "skip_reason": policy_reason,
            }
            bulk_run["skipped_count"] += 1
            bulk_run["skipped_actions"].append(skipped)
            bulk_run["per_action_results"].append(skipped)
            continue

        if not dry_run and not force:
            previous_success = latest_successful_action_for_action_id(root, action_id)
            if previous_success is not None:
                skipped = {
                    "action_id": action_id,
                    "category": action.get("category"),
                    "task_id": action.get("task_id"),
                    "allowed": False,
                    "skip_kind": "idempotency",
                    "skip_reason": "Action already has a successful non-dry-run execution record.",
                    "prior_execution_id": previous_success.get("execution_id"),
                }
                bulk_run["skipped_count"] += 1
                bulk_run["skipped_actions"].append(skipped)
                bulk_run["per_action_results"].append(skipped)
                continue

        still_applicable, stale_kind, stale_reason = revalidate_selected_action(root, action=action)
        if not still_applicable:
            result, _ = execute_selected_action(
                root,
                action_id=action_id,
                action=action,
                action_pack_path=pack_path,
                invoked_by="bulk",
                dry_run=dry_run,
                force=force,
                source_action_pack_id=pack.get("action_pack_id"),
                source_action_pack_fingerprint=pack.get("action_pack_fingerprint"),
                source_action_pack_validation_status=pack_meta.get("status", "valid"),
                source_action_pack_resolution=pack_meta.get("resolution", "current"),
                source_action_pack_rebuild_reason=pack_meta.get("rebuild_reason") or "",
                source_action_pack_requested_explicit=bool(pack_meta.get("requested_explicit")),
            )
            skipped = {
                "action_id": action_id,
                "category": action.get("category"),
                "task_id": action.get("task_id"),
                "allowed": False,
                "skip_kind": stale_kind,
                "skip_reason": stale_reason,
                "execution_id": (result.get("execution_record") or {}).get("execution_id"),
            }
            bulk_run["skipped_count"] += 1
            bulk_run["skipped_actions"].append(skipped)
            bulk_run["per_action_results"].append(skipped)
            continue

        result, exit_code = execute_selected_action(
            root,
            action_id=action_id,
            action=action,
            action_pack_path=pack_path,
            invoked_by="bulk",
            dry_run=dry_run,
            force=force,
            source_action_pack_id=pack.get("action_pack_id"),
            source_action_pack_fingerprint=pack.get("action_pack_fingerprint"),
            source_action_pack_validation_status=pack_meta.get("status", "valid"),
            source_action_pack_resolution=pack_meta.get("resolution", "current"),
            source_action_pack_rebuild_reason=pack_meta.get("rebuild_reason") or "",
            source_action_pack_requested_explicit=bool(pack_meta.get("requested_explicit")),
        )
        summary = {
            "action_id": action_id,
            "category": action.get("category"),
            "task_id": action.get("task_id"),
            "ok": result.get("ok", False),
            "dry_run": result.get("dry_run", False),
            "execution_id": (result.get("execution_record") or {}).get("execution_id"),
            "ack_summary": result.get("ack_summary") or (result.get("execution_record") or {}).get("ack_summary", ""),
        }
        bulk_run["attempted_count"] += 1
        bulk_run["per_action_results"].append(summary)
        bulk_run["executed_actions"].append(summary)
        if exit_code == 0 and result.get("ok"):
            bulk_run["succeeded_count"] += 1
            continue

        bulk_run["failed_count"] += 1
        bulk_run["ok"] = False
        bulk_run["stop_reason"] = f"failed_action:{action_id}"
        if not continue_on_failure:
            break

    bulk_run["completed_at"] = now_iso()
    if bulk_run["failed_count"] == 0:
        bulk_run["ok"] = True
    save_bulk_run(root, bulk_run)
    return bulk_run, 0 if bulk_run["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded bulk selection over the current operator action pack.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--category", default="", help="Filter by action category")
    parser.add_argument("--task-id", default="", help="Filter by task id")
    parser.add_argument("--action-id-prefix", default="", help="Filter by stable action-id prefix")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of selected actions")
    parser.add_argument("--dry-run", action="store_true", help="Resolve selected actions without executing them")
    parser.add_argument("--continue-on-failure", action="store_true", help="Continue after a failed action")
    parser.add_argument("--force", action="store_true", help="Re-execute actions even if they already succeeded previously")
    parser.add_argument("--action-pack-limit", type=int, default=10, help="Implicit action-pack rebuild limit if needed")
    args = parser.parse_args()

    payload, exit_code = run_bulk(
        Path(args.root).resolve(),
        category=args.category or None,
        task_id=args.task_id or None,
        action_id_prefix=args.action_id_prefix or None,
        limit=args.limit,
        dry_run=args.dry_run,
        continue_on_failure=args.continue_on_failure,
        force=args.force,
        action_pack_limit=args.action_pack_limit,
    )
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
