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
from scripts.operator_action_executor import execute_selected_action, revalidate_selected_action
from scripts.operator_triage_pack import build_operator_triage_pack
from scripts.operator_triage_support import resolve_newest_valid_pack, save_safe_autofix_record


def run_safe_autofix(
    root: Path,
    *,
    dry_run_top_action: bool = False,
    execute_safe_review: bool = False,
    limit: int = 10,
) -> tuple[dict[str, Any], int]:
    before_pack, before_path, before_meta, before_error = resolve_newest_valid_pack(root, limit=limit)
    triage_payload = build_operator_triage_pack(root, limit=limit)
    triage = triage_payload["pack"]
    after_pack, after_path, after_meta, after_error = resolve_newest_valid_pack(root, limit=limit)

    explanations: list[dict[str, Any]] = []
    for row in triage.get("recommended_operator_interventions", [])[:3]:
        action_id = row.get("action_id")
        task_id = row.get("task_id")
        if action_id or task_id:
            explanations.append(explain_action(root, action_id=action_id, task_id=task_id, execution_id=None, queue_run_id=None, bulk_run_id=None))

    selected_action = None
    execution_payload = None
    exit_code = 0
    if after_pack is not None:
        for row in after_pack.get("recommended_execution_order", []):
            action = (after_pack.get("action_index") or {}).get(row.get("action_id"))
            if not action:
                continue
            if action.get("category") == "pending_review" and action.get("verb") == "approve":
                still_applicable, _, _ = revalidate_selected_action(root, action=action)
                if still_applicable:
                    selected_action = action
                    break

    if selected_action is not None and (dry_run_top_action or execute_safe_review):
        execution_payload, exit_code = execute_selected_action(
            root,
            action_id=selected_action["action_id"],
            action=selected_action,
            action_pack_path=after_path,
            invoked_by="safe_autofix",
            dry_run=not execute_safe_review,
            force=False,
            source_action_pack_id=(after_pack or {}).get("action_pack_id"),
            source_action_pack_fingerprint=(after_pack or {}).get("action_pack_fingerprint"),
            source_action_pack_validation_status=after_meta.get("status", "valid"),
            source_action_pack_resolution=after_meta.get("resolution", "current"),
            source_action_pack_rebuild_reason=after_meta.get("rebuild_reason") or "",
            source_action_pack_requested_explicit=bool(after_meta.get("requested_explicit")),
        )

    record = {
        "autofix_run_id": new_id("opauto"),
        "started_at": now_iso(),
        "completed_at": now_iso(),
        "ok": exit_code == 0 and after_error is None,
        "current_pack_before": {
            "path": str(before_path),
            "status": before_meta.get("status"),
            "resolution": before_meta.get("resolution"),
            "error": before_error,
        },
        "current_pack_after": {
            "path": str(after_path),
            "status": after_meta.get("status"),
            "resolution": after_meta.get("resolution"),
            "error": after_error,
            "action_pack_id": (after_pack or {}).get("action_pack_id"),
            "action_pack_fingerprint": (after_pack or {}).get("action_pack_fingerprint"),
        },
        "rebuild_happened": before_meta.get("resolution") == "rebuilt" or after_meta.get("resolution") == "rebuilt",
        "top_recommendations_considered": triage.get("recommended_operator_interventions", [])[:3],
        "explanations": explanations,
        "safe_action_selected": selected_action["action_id"] if selected_action else None,
        "safe_action_executed": bool(execution_payload and execute_safe_review),
        "safe_action_dry_run": bool(execution_payload and not execute_safe_review),
        "execution_record_id": ((execution_payload or {}).get("execution_record") or {}).get("execution_id"),
    }
    save_safe_autofix_record(root, record)

    return {
        "ok": record["ok"],
        "rebuild_happened": record["rebuild_happened"],
        "triage_pack_path": triage_payload["json_path"],
        "top_recommendations_considered": record["top_recommendations_considered"],
        "explanations": explanations,
        "selected_safe_action_id": record["safe_action_selected"],
        "execution": execution_payload,
        "autofix_record": record,
    }, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Perform only the safest bounded operator wrapper interventions.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument(
        "--dry-run-top-action",
        action="store_true",
        help="Resolve and dry-run the top safe review action if one exists",
    )
    parser.add_argument(
        "--execute-safe-review",
        action="store_true",
        help="Execute exactly one safe review approval if it exists in the newest valid pack",
    )
    parser.add_argument("--limit", type=int, default=10, help="Maximum recent items to inspect")
    args = parser.parse_args()

    payload, exit_code = run_safe_autofix(
        Path(args.root).resolve(),
        dry_run_top_action=args.dry_run_top_action,
        execute_safe_review=args.execute_safe_review,
        limit=args.limit,
    )
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
