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

from scripts.operator_action_ledger import list_operator_action_executions
from scripts.operator_checkpoint_action_pack import classify_action_pack


def _load_jsons(folder: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return rows


def _sort_recent(rows: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: tuple(str(row.get(key, "")) for key in keys), reverse=True)


def _match_action(row: dict[str, Any], *, action_id: str | None, task_id: str | None) -> bool:
    if action_id:
        return row.get("action_id") == action_id
    if task_id:
        selected = row.get("selected_action") or {}
        return selected.get("task_id") == task_id
    return True


def _find_queue_match(rows: list[dict[str, Any]], *, action_id: str | None, task_id: str | None) -> dict[str, Any] | None:
    for row in _sort_recent(rows, "completed_at", "started_at"):
        for skipped in row.get("skipped_actions", []):
            if action_id and skipped.get("action_id") == action_id:
                return {"kind": "queue_skip", "run": row, "entry": skipped}
            if task_id and skipped.get("task_id") == task_id:
                return {"kind": "queue_skip", "run": row, "entry": skipped}
        for executed in row.get("executed_actions", []):
            if action_id and executed.get("action_id") == action_id:
                return {"kind": "queue_execute", "run": row, "entry": executed}
            if task_id and executed.get("task_id") == task_id:
                return {"kind": "queue_execute", "run": row, "entry": executed}
    return None


def _find_bulk_match(rows: list[dict[str, Any]], *, action_id: str | None, task_id: str | None) -> dict[str, Any] | None:
    for row in _sort_recent(rows, "completed_at", "started_at"):
        for skipped in row.get("skipped_actions", []):
            if action_id and skipped.get("action_id") == action_id:
                return {"kind": "bulk_skip", "run": row, "entry": skipped}
            if task_id and skipped.get("task_id") == task_id:
                return {"kind": "bulk_skip", "run": row, "entry": skipped}
        for executed in row.get("executed_actions", []):
            if action_id and executed.get("action_id") == action_id:
                return {"kind": "bulk_execute", "run": row, "entry": executed}
            if task_id and executed.get("task_id") == task_id:
                return {"kind": "bulk_execute", "run": row, "entry": executed}
    return None


def explain_action(
    root: Path,
    *,
    action_id: str | None,
    task_id: str | None,
    execution_id: str | None,
    queue_run_id: str | None,
    bulk_run_id: str | None,
) -> dict[str, Any]:
    execution_rows = _load_jsons(root / "state" / "operator_action_executions")
    queue_rows = _load_jsons(root / "state" / "operator_queue_runs")
    bulk_rows = _load_jsons(root / "state" / "operator_bulk_runs")

    execution_match = None
    if execution_id:
        execution_match = next((row for row in execution_rows if row.get("execution_id") == execution_id), None)
    else:
        matches = [row for row in execution_rows if _match_action(row, action_id=action_id, task_id=task_id)]
        execution_match = _sort_recent(matches, "completed_at", "started_at")[0] if matches else None

    queue_match = None
    if queue_run_id:
        queue = next((row for row in queue_rows if row.get("queue_run_id") == queue_run_id), None)
        if queue:
            queue_match = _find_queue_match([queue], action_id=action_id, task_id=task_id)
    else:
        queue_match = _find_queue_match(queue_rows, action_id=action_id, task_id=task_id)

    bulk_match = None
    if bulk_run_id:
        bulk = next((row for row in bulk_rows if row.get("bulk_run_id") == bulk_run_id), None)
        if bulk:
            bulk_match = _find_bulk_match([bulk], action_id=action_id, task_id=task_id)
    else:
        bulk_match = _find_bulk_match(bulk_rows, action_id=action_id, task_id=task_id)

    current_pack_path = root / "state" / "logs" / "operator_checkpoint_action_pack.json"
    current_pack_summary = {"exists": current_pack_path.exists(), "path": str(current_pack_path)}
    current_pack_action_present = None
    if current_pack_path.exists():
        try:
            current_pack = json.loads(current_pack_path.read_text(encoding="utf-8"))
            current_pack_summary.update(classify_action_pack(current_pack))
            if action_id:
                current_pack_action_present = action_id in (current_pack.get("action_index") or {})
        except Exception as exc:
            current_pack_summary.update({"status": "malformed", "reason": str(exc), "fresh": False})

    explanation = "No matching action history was found."
    outcome = "unknown"
    if execution_match is not None:
        if execution_match.get("success"):
            outcome = "executed"
            explanation = f"Action `{execution_match['action_id']}` executed successfully."
        elif execution_match.get("failure_kind") in {"expired_pack", "pinned_pack_validation_failed"}:
            outcome = str(execution_match.get("failure_kind"))
            explanation = str(execution_match.get("failure_reason") or execution_match.get("stderr_snapshot") or "Pinned pack validation blocked execution.")
        elif "already has a successful" in execution_match.get("stderr_snapshot", ""):
            outcome = "idempotency_skip"
            explanation = execution_match["stderr_snapshot"]
        elif "no longer" in execution_match.get("stderr_snapshot", "") or "cannot accept" in execution_match.get("stderr_snapshot", ""):
            outcome = "stale_skip"
            explanation = execution_match["stderr_snapshot"]
    if queue_match is not None and queue_match["kind"] == "queue_skip":
        outcome = f"{queue_match['entry'].get('skip_kind')}_skip"
        explanation = queue_match["entry"].get("skip_reason", explanation)
    if bulk_match is not None and bulk_match["kind"] == "bulk_skip":
        outcome = f"{bulk_match['entry'].get('skip_kind')}_skip"
        explanation = bulk_match["entry"].get("skip_reason", explanation)
    if action_id and current_pack_action_present is False and outcome == "unknown":
        outcome = "missing_from_newest_pack"
        explanation = f"Action `{action_id}` does not exist in the newest checkpoint action pack."

    return {
        "ok": True,
        "query": {
            "action_id": action_id,
            "task_id": task_id,
            "execution_id": execution_id,
            "queue_run_id": queue_run_id,
            "bulk_run_id": bulk_run_id,
        },
        "outcome": outcome,
        "explanation": explanation,
        "latest_execution": execution_match,
        "latest_queue_match": queue_match,
        "latest_bulk_match": bulk_match,
        "current_action_pack": current_pack_summary,
        "current_pack_action_present": current_pack_action_present,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain why an operator action executed, skipped, or refused.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--action-id", default="", help="Stable action id selector")
    parser.add_argument("--task-id", default="", help="Task id selector")
    parser.add_argument("--execution-id", default="", help="Specific execution ledger id")
    parser.add_argument("--queue-run-id", default="", help="Specific queue-run ledger id")
    parser.add_argument("--bulk-run-id", default="", help="Specific bulk-run ledger id")
    args = parser.parse_args()

    payload = explain_action(
        Path(args.root).resolve(),
        action_id=args.action_id or None,
        task_id=args.task_id or None,
        execution_id=args.execution_id or None,
        queue_run_id=args.queue_run_id or None,
        bulk_run_id=args.bulk_run_id or None,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
