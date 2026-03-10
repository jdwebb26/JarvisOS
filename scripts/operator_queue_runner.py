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
from scripts.operator_action_executor import execute_selected_action
from scripts.operator_action_ledger import latest_successful_action_for_action_id
from scripts.operator_checkpoint_action_pack import build_operator_checkpoint_action_pack


DEFAULT_ALLOWED_CATEGORIES = {"pending_review"}
LOW_RISK_ARTIFACT_VERBS = {"inspect", "inspect_artifact_json"}


def operator_queue_runs_dir(root: Path) -> Path:
    path = root / "state" / "operator_queue_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_queue_run(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_queue_runs_dir(root) / f"{record['queue_run_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def _load_or_build_action_pack(root: Path, *, limit: int) -> tuple[dict[str, Any], Path]:
    pack_path = root / "state" / "logs" / "operator_checkpoint_action_pack.json"
    if pack_path.exists():
        try:
            return json.loads(pack_path.read_text(encoding="utf-8")), pack_path
        except Exception:
            pass
    result = build_operator_checkpoint_action_pack(root, limit=limit)
    return result["pack"], Path(result["json_path"])


def _filtered_actions(
    pack: dict[str, Any],
    *,
    task_id: str | None,
    category: str | None,
    max_actions: int | None,
) -> list[dict[str, Any]]:
    rows = list(pack.get("recommended_execution_order", []))
    if task_id:
        rows = [row for row in rows if row.get("task_id") == task_id]
    if category:
        rows = [row for row in rows if row.get("category") == category]
    if max_actions is not None:
        rows = rows[:max_actions]
    return rows


def _summary_entry(result: dict[str, Any], *, action_id: str) -> dict[str, Any]:
    selected = result.get("selected_action") or {}
    return {
        "action_id": action_id,
        "ok": result.get("ok", False),
        "dry_run": result.get("dry_run", False),
        "task_id": selected.get("task_id"),
        "category": selected.get("category"),
        "execution_id": (result.get("execution_record") or {}).get("execution_id"),
        "ack_summary": result.get("ack_summary") or (result.get("execution_record") or {}).get("ack_summary", ""),
    }


def _policy_summary(
    *,
    allow_categories: set[str],
    deny_categories: set[str],
    allow_approval: bool,
    allow_ship: bool,
    force: bool,
) -> dict[str, Any]:
    return {
        "default_allowed_categories": sorted(DEFAULT_ALLOWED_CATEGORIES),
        "effective_allow_categories": sorted(allow_categories),
        "deny_categories": sorted(deny_categories),
        "allow_approval": allow_approval,
        "allow_ship": allow_ship,
        "force": force,
    }


def _evaluate_policy(
    action: dict[str, Any],
    *,
    allow_categories: set[str],
    deny_categories: set[str],
    allow_approval: bool,
    allow_ship: bool,
) -> tuple[bool, str]:
    category = str(action.get("category") or "")
    verb = str(action.get("verb") or "")

    if category in deny_categories:
        return False, f"Category `{category}` denied by explicit policy."

    if category == "pending_approval":
        if allow_approval:
            return True, "Approval actions allowed by explicit policy."
        return False, "Approval actions blocked by default policy."

    if category == "artifact_followup":
        if verb in LOW_RISK_ARTIFACT_VERBS:
            return True, "Low-risk artifact inspection allowed by default policy."
        if allow_ship:
            return True, "Ship/publish artifact follow-up allowed by explicit policy."
        return False, "Ship/publish artifact follow-up blocked by default policy."

    if category in allow_categories:
        return True, f"Category `{category}` allowed by policy."

    return False, f"Category `{category}` blocked by default safe policy."


def run_queue(
    root: Path,
    *,
    task_id: str | None = None,
    category: str | None = None,
    max_actions: int | None = None,
    dry_run: bool = False,
    continue_on_failure: bool = False,
    allow_categories: set[str] | None = None,
    deny_categories: set[str] | None = None,
    allow_approval: bool = False,
    allow_ship: bool = False,
    force: bool = False,
    limit: int = 10,
) -> tuple[dict[str, Any], int]:
    pack, pack_path = _load_or_build_action_pack(root, limit=limit)
    allowed_categories = set(DEFAULT_ALLOWED_CATEGORIES)
    allowed_categories.update(allow_categories or set())
    denied_categories = set(deny_categories or set())
    queue_run = {
        "queue_run_id": new_id("opqueue"),
        "started_at": now_iso(),
        "completed_at": None,
        "source_action_pack_path": str(pack_path),
        "filters": {
            "task_id": task_id,
            "category": category,
            "max_actions": max_actions,
            "dry_run": dry_run,
            "continue_on_failure": continue_on_failure,
            "allow_categories": sorted(allow_categories or set()),
            "deny_categories": sorted(denied_categories),
            "allow_approval": allow_approval,
            "allow_ship": allow_ship,
            "force": force,
        },
        "policy_summary": _policy_summary(
            allow_categories=allowed_categories,
            deny_categories=denied_categories,
            allow_approval=allow_approval,
            allow_ship=allow_ship,
            force=force,
        ),
        "ok": True,
        "attempted_count": 0,
        "succeeded_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "stopped_on_action_id": None,
        "executed_actions": [],
        "skipped_actions": [],
    }

    actions = _filtered_actions(pack, task_id=task_id, category=category, max_actions=max_actions)
    for item in actions:
        action_id = item["action_id"]
        action = pack.get("action_index", {}).get(action_id)
        if action is None:
            result = {
                "ok": False,
                "selected_action": None,
                "execution_record": None,
                "failure": {"error": f"Action id missing from action_index: {action_id}"},
            }
            queue_run["executed_actions"].append(
                {
                    "action_id": action_id,
                    "ok": False,
                    "failure": result["failure"],
                }
            )
            queue_run["attempted_count"] += 1
            queue_run["failed_count"] += 1
            queue_run["ok"] = False
            queue_run["stopped_on_action_id"] = action_id
            if not continue_on_failure:
                break
            continue

        allowed, policy_reason = _evaluate_policy(
            action,
            allow_categories=allowed_categories,
            deny_categories=denied_categories,
            allow_approval=allow_approval,
            allow_ship=allow_ship,
        )
        if not allowed:
            queue_run["skipped_count"] += 1
            queue_run["skipped_actions"].append(
                {
                    "action_id": action_id,
                    "category": action.get("category"),
                    "task_id": action.get("task_id"),
                    "allowed": False,
                    "skip_kind": "policy",
                    "skip_reason": policy_reason,
                    "policy_reason": policy_reason,
                }
            )
            continue

        if not dry_run and not force:
            previous_success = latest_successful_action_for_action_id(root, action_id)
            if previous_success is not None:
                skip_reason = (
                    "Action already has a successful non-dry-run execution record and queue replay is blocked by default."
                )
                queue_run["skipped_count"] += 1
                queue_run["skipped_actions"].append(
                    {
                        "action_id": action_id,
                        "category": action.get("category"),
                        "task_id": action.get("task_id"),
                        "allowed": False,
                        "skip_kind": "idempotency",
                        "skip_reason": skip_reason,
                        "prior_execution_id": previous_success.get("execution_id"),
                    }
                )
                continue

        result, exit_code = execute_selected_action(
            root,
            action_id=action_id,
            action=action,
            action_pack_path=pack_path,
            dry_run=dry_run,
            force=force,
        )
        queue_run["attempted_count"] += 1
        if exit_code == 0 and result.get("ok"):
            queue_run["succeeded_count"] += 1
        else:
            queue_run["failed_count"] += 1
            queue_run["ok"] = False
            queue_run["stopped_on_action_id"] = action_id
        executed = _summary_entry(result, action_id=action_id)
        executed["allowed"] = True
        executed["policy_reason"] = policy_reason
        queue_run["executed_actions"].append(executed)
        if exit_code != 0 and not continue_on_failure:
            break

    if queue_run["failed_count"] == 0:
        queue_run["ok"] = True
    queue_run["completed_at"] = now_iso()
    save_queue_run(root, queue_run)
    return queue_run, 0 if queue_run["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run operator checkpoint actions in recommended queue order.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", default="", help="Filter queue to one task")
    parser.add_argument("--category", default="", help="Filter queue to one action category")
    parser.add_argument("--max-actions", type=int, default=None, help="Maximum actions to attempt")
    parser.add_argument("--dry-run", action="store_true", help="Resolve all queued actions without executing them")
    parser.add_argument("--continue-on-failure", action="store_true", help="Continue after a failed queued action")
    parser.add_argument("--allow-category", action="append", default=[], help="Explicitly allow an action category")
    parser.add_argument("--deny-category", action="append", default=[], help="Explicitly deny an action category")
    parser.add_argument("--allow-approval", action="store_true", help="Allow approval actions")
    parser.add_argument("--allow-ship", action="store_true", help="Allow ship/publish artifact follow-up actions")
    parser.add_argument("--force", action="store_true", help="Re-execute actions even if they already succeeded previously")
    parser.add_argument("--limit", type=int, default=10, help="Action-pack rebuild limit if needed")
    args = parser.parse_args()

    payload, exit_code = run_queue(
        Path(args.root).resolve(),
        task_id=args.task_id or None,
        category=args.category or None,
        max_actions=args.max_actions,
        dry_run=args.dry_run,
        continue_on_failure=args.continue_on_failure,
        allow_categories=set(args.allow_category),
        deny_categories=set(args.deny_category),
        allow_approval=args.allow_approval,
        allow_ship=args.allow_ship,
        force=args.force,
        limit=args.limit,
    )
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
