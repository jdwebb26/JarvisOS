#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import now_iso


def load_jsons(folder: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return rows


def sort_recent(rows: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: tuple(str(row.get(key, "")) for key in keys), reverse=True)


def current_action_pack_path(root: Path) -> Path:
    return root / "state" / "logs" / "operator_checkpoint_action_pack.json"


def triage_logs_dir(root: Path) -> Path:
    path = root / "state" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_task_interventions_dir(root: Path) -> Path:
    path = root / "state" / "operator_task_interventions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_safe_autofix_runs_dir(root: Path) -> Path:
    path = root / "state" / "operator_safe_autofix_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_reply_plans_dir(root: Path) -> Path:
    path = root / "state" / "operator_reply_plans"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_reply_applies_dir(root: Path) -> Path:
    path = root / "state" / "operator_reply_applies"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_task_intervention_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_task_interventions_dir(root) / f"{record['intervention_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def save_safe_autofix_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_safe_autofix_runs_dir(root) / f"{record['autofix_run_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def save_reply_plan_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_reply_plans_dir(root) / f"{record['plan_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def save_reply_apply_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_reply_applies_dir(root) / f"{record['reply_apply_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def list_task_interventions(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_task_interventions_dir(root)), "completed_at", "started_at")


def list_safe_autofix_runs(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_safe_autofix_runs_dir(root)), "completed_at", "started_at")


def list_reply_plans(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_reply_plans_dir(root)), "created_at", "started_at")


def list_reply_applies(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_reply_applies_dir(root)), "completed_at", "started_at")


def load_current_action_pack_summary(root: Path) -> dict[str, Any]:
    path = current_action_pack_path(root)
    summary = {
        "path": str(path),
        "status": "malformed",
        "reason": "Current action pack not found.",
        "action_pack_id": None,
        "action_pack_fingerprint": None,
        "generated_at": None,
        "expires_at": None,
        "recommended_ttl_seconds": None,
        "stale_after_reason": None,
        "fresh": False,
    }
    if not path.exists():
        return summary
    try:
        from scripts.operator_checkpoint_action_pack import classify_action_pack

        payload = json.loads(path.read_text(encoding="utf-8"))
        return {"path": str(path), **classify_action_pack(payload)}
    except Exception as exc:
        return {"path": str(path), "status": "malformed", "reason": str(exc), "fresh": False}


def resolve_newest_valid_pack(root: Path, *, limit: int = 10) -> tuple[dict[str, Any] | None, Path, dict[str, Any], str | None]:
    from scripts.operator_checkpoint_action_pack import resolve_action_pack

    return resolve_action_pack(root, limit=limit)


def inspect_current_pack_only(root: Path) -> tuple[dict[str, Any] | None, Path, dict[str, Any], str | None]:
    path = current_action_pack_path(root)
    summary = load_current_action_pack_summary(root)
    if not path.exists():
        return None, path, summary, summary.get("reason") or "Current action pack not found."
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, path, summary, str(exc)
    if summary.get("status") != "valid":
        return None, path, summary, summary.get("reason") or f"Current action pack status is {summary.get('status')}."
    meta = dict(summary)
    meta.setdefault("resolution", "current")
    meta.setdefault("requested_explicit", False)
    meta.setdefault("rebuild_reason", "")
    return payload, path, meta, None


def latest_queue_run_for_task(queue_runs: list[dict[str, Any]], task_id: str) -> dict[str, Any] | None:
    for row in sort_recent(queue_runs, "completed_at", "started_at"):
        if any(item.get("task_id") == task_id for item in row.get("executed_actions", [])):
            return row
        if any(item.get("task_id") == task_id for item in row.get("skipped_actions", [])):
            return row
    return None


def latest_bulk_run_for_task(bulk_runs: list[dict[str, Any]], task_id: str) -> dict[str, Any] | None:
    for row in sort_recent(bulk_runs, "completed_at", "started_at"):
        if any(item.get("task_id") == task_id for item in row.get("executed_actions", [])):
            return row
        if any(item.get("task_id") == task_id for item in row.get("skipped_actions", [])):
            return row
    return None


def latest_execution_for_task(
    executions: list[dict[str, Any]],
    task_id: str,
    *,
    success: bool | None = None,
) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = []
    for row in sort_recent(executions, "completed_at", "started_at"):
        selected = row.get("selected_action") or {}
        if selected.get("task_id") != task_id:
            continue
        if success is not None and bool(row.get("success", False)) != success:
            continue
        matches.append(row)
    return matches[0] if matches else None


def _record_group_key(task_id: str | None, action_id: str | None, target_id: str | None) -> str:
    return f"{task_id or 'unknown'}::{action_id or target_id or 'unknown'}"


def _summarize_grouped_rows(
    groups: dict[str, list[dict[str, Any]]],
    *,
    count_key: str = "count",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for items in groups.values():
        if not items:
            continue
        latest = sort_recent(items, "completed_at", "started_at")[0]
        row = dict(latest)
        row[count_key] = len(items)
        rows.append(row)
    return sort_recent(rows, "count", "completed_at", "started_at")


def detect_repeated_problems(
    root: Path,
    *,
    pack: dict[str, Any] | None = None,
    recent_limit: int = 50,
) -> dict[str, Any]:
    executions = sort_recent(load_jsons(root / "state" / "operator_action_executions"), "completed_at", "started_at")[:recent_limit]
    queue_runs = sort_recent(load_jsons(root / "state" / "operator_queue_runs"), "completed_at", "started_at")[:recent_limit]
    bulk_runs = sort_recent(load_jsons(root / "state" / "operator_bulk_runs"), "completed_at", "started_at")[:recent_limit]
    action_index = None if pack is None else (pack.get("action_index") or {})

    stale_groups: dict[str, list[dict[str, Any]]] = {}
    idempotency_groups: dict[str, list[dict[str, Any]]] = {}
    pinned_groups: dict[str, list[dict[str, Any]]] = {}
    expired_groups: dict[str, list[dict[str, Any]]] = {}
    queue_stop_groups: dict[str, list[dict[str, Any]]] = {}
    bulk_fail_groups: dict[str, list[dict[str, Any]]] = {}
    missing_pack_groups: dict[str, list[dict[str, Any]]] = {}

    for row in executions:
        selected = row.get("selected_action") or {}
        action_id = row.get("action_id")
        task_id = selected.get("task_id")
        target_id = selected.get("target_id")
        failure_kind = row.get("failure_kind")
        if failure_kind == "stale_action":
            key = _record_group_key(task_id, action_id, target_id)
            stale_groups.setdefault(key, []).append(
                {
                    "task_id": task_id,
                    "action_id": action_id,
                    "target_id": target_id,
                    "completed_at": row.get("completed_at"),
                    "started_at": row.get("started_at"),
                    "reason": row.get("failure_reason") or row.get("stderr_snapshot", ""),
                }
            )
        if failure_kind == "already_executed":
            key = action_id or ""
            idempotency_groups.setdefault(key, []).append(
                {
                    "task_id": task_id,
                    "action_id": action_id,
                    "completed_at": row.get("completed_at"),
                    "started_at": row.get("started_at"),
                    "reason": row.get("failure_reason") or row.get("stderr_snapshot", ""),
                }
            )
        if failure_kind == "pinned_pack_validation_failed":
            key = str(row.get("source_action_pack_path") or row.get("source_action_pack_id") or "unknown")
            pinned_groups.setdefault(key, []).append(
                {
                    "task_id": task_id,
                    "action_id": action_id,
                    "source_action_pack_id": row.get("source_action_pack_id"),
                    "source_action_pack_path": row.get("source_action_pack_path"),
                    "completed_at": row.get("completed_at"),
                    "started_at": row.get("started_at"),
                    "reason": row.get("failure_reason") or row.get("stderr_snapshot", ""),
                }
            )
        if failure_kind == "expired_pack":
            key = str(row.get("source_action_pack_path") or row.get("source_action_pack_id") or "unknown")
            expired_groups.setdefault(key, []).append(
                {
                    "task_id": task_id,
                    "action_id": action_id,
                    "source_action_pack_id": row.get("source_action_pack_id"),
                    "source_action_pack_path": row.get("source_action_pack_path"),
                    "completed_at": row.get("completed_at"),
                    "started_at": row.get("started_at"),
                    "reason": row.get("failure_reason") or row.get("stderr_snapshot", ""),
                }
            )
        if action_index is not None and action_id and action_id not in action_index:
            key = _record_group_key(task_id, action_id, target_id)
            missing_pack_groups.setdefault(key, []).append(
                {
                    "task_id": task_id,
                    "action_id": action_id,
                    "target_id": target_id,
                    "completed_at": row.get("completed_at"),
                    "started_at": row.get("started_at"),
                    "reason": "Action referenced in execution history is not present in the newest valid pack.",
                }
            )

    for queue_run in queue_runs:
        stopped_on = queue_run.get("stopped_on_action_id")
        if stopped_on:
            failed_entry = next((item for item in queue_run.get("executed_actions", []) if item.get("action_id") == stopped_on), None)
            stop_category = (failed_entry or {}).get("category") or "unknown"
            queue_stop_groups.setdefault(stop_category, []).append(
                {
                    "category": stop_category,
                    "queue_run_id": queue_run.get("queue_run_id"),
                    "completed_at": queue_run.get("completed_at"),
                    "started_at": queue_run.get("started_at"),
                    "reason": queue_run.get("stop_reason") or f"Queue stopped on {stopped_on}.",
                }
            )
        for skipped in queue_run.get("skipped_actions", []):
            if skipped.get("skip_kind") == "stale_action":
                key = _record_group_key(skipped.get("task_id"), skipped.get("action_id"), None)
                stale_groups.setdefault(key, []).append(
                    {
                        "task_id": skipped.get("task_id"),
                        "action_id": skipped.get("action_id"),
                        "target_id": None,
                        "completed_at": queue_run.get("completed_at"),
                        "started_at": queue_run.get("started_at"),
                        "reason": skipped.get("skip_reason", ""),
                    }
                )
            if skipped.get("skip_kind") == "idempotency":
                key = str(skipped.get("action_id") or "")
                idempotency_groups.setdefault(key, []).append(
                    {
                        "task_id": skipped.get("task_id"),
                        "action_id": skipped.get("action_id"),
                        "completed_at": queue_run.get("completed_at"),
                        "started_at": queue_run.get("started_at"),
                        "reason": skipped.get("skip_reason", ""),
                    }
                )
            if action_index is not None and skipped.get("action_id") and skipped.get("action_id") not in action_index:
                key = _record_group_key(skipped.get("task_id"), skipped.get("action_id"), None)
                missing_pack_groups.setdefault(key, []).append(
                    {
                        "task_id": skipped.get("task_id"),
                        "action_id": skipped.get("action_id"),
                        "completed_at": queue_run.get("completed_at"),
                        "started_at": queue_run.get("started_at"),
                        "reason": "Skipped action is no longer present in the newest valid pack.",
                    }
                )

    for bulk_run in bulk_runs:
        for row in bulk_run.get("per_action_results", []):
            if row.get("ok") is False and row.get("category"):
                category = str(row.get("category"))
                bulk_fail_groups.setdefault(category, []).append(
                    {
                        "category": category,
                        "bulk_run_id": bulk_run.get("bulk_run_id"),
                        "completed_at": bulk_run.get("completed_at"),
                        "started_at": bulk_run.get("started_at"),
                        "reason": bulk_run.get("stop_reason") or f"Bulk action failed in category {category}.",
                    }
                )
        for skipped in bulk_run.get("skipped_actions", []):
            if skipped.get("skip_kind") == "stale_action":
                key = _record_group_key(skipped.get("task_id"), skipped.get("action_id"), None)
                stale_groups.setdefault(key, []).append(
                    {
                        "task_id": skipped.get("task_id"),
                        "action_id": skipped.get("action_id"),
                        "target_id": None,
                        "completed_at": bulk_run.get("completed_at"),
                        "started_at": bulk_run.get("started_at"),
                        "reason": skipped.get("skip_reason", ""),
                    }
                )
            if skipped.get("skip_kind") == "idempotency":
                key = str(skipped.get("action_id") or "")
                idempotency_groups.setdefault(key, []).append(
                    {
                        "task_id": skipped.get("task_id"),
                        "action_id": skipped.get("action_id"),
                        "completed_at": bulk_run.get("completed_at"),
                        "started_at": bulk_run.get("started_at"),
                        "reason": skipped.get("skip_reason", ""),
                    }
                )
            if action_index is not None and skipped.get("action_id") and skipped.get("action_id") not in action_index:
                key = _record_group_key(skipped.get("task_id"), skipped.get("action_id"), None)
                missing_pack_groups.setdefault(key, []).append(
                    {
                        "task_id": skipped.get("task_id"),
                        "action_id": skipped.get("action_id"),
                        "completed_at": bulk_run.get("completed_at"),
                        "started_at": bulk_run.get("started_at"),
                        "reason": "Bulk action is no longer present in the newest valid pack.",
                    }
                )

    return {
        "repeated_stale_actions": [row for row in _summarize_grouped_rows(stale_groups) if row["count"] >= 2],
        "repeated_idempotency_skips": [row for row in _summarize_grouped_rows(idempotency_groups) if row["count"] >= 2],
        "repeated_pinned_pack_validation_failures": [row for row in _summarize_grouped_rows(pinned_groups) if row["count"] >= 2],
        "repeated_expired_pack_refusals": [row for row in _summarize_grouped_rows(expired_groups) if row["count"] >= 2],
        "queue_repeated_stop_categories": [row for row in _summarize_grouped_rows(queue_stop_groups) if row["count"] >= 2],
        "bulk_repeated_failure_categories": [row for row in _summarize_grouped_rows(bulk_fail_groups) if row["count"] >= 2],
        "actions_missing_from_newest_pack": _summarize_grouped_rows(missing_pack_groups),
    }


def build_task_intervention_summaries(
    root: Path,
    *,
    pack: dict[str, Any] | None,
    task_limit: int = 10,
) -> list[dict[str, Any]]:
    tasks = sort_recent(load_jsons(root / "state" / "tasks"), "updated_at", "created_at")[:task_limit]
    executions = load_jsons(root / "state" / "operator_action_executions")
    queue_runs = load_jsons(root / "state" / "operator_queue_runs")
    bulk_runs = load_jsons(root / "state" / "operator_bulk_runs")
    reviews = [row for row in load_jsons(root / "state" / "reviews") if row.get("status") == "pending"]
    approvals = [row for row in load_jsons(root / "state" / "approvals") if row.get("status") == "pending"]
    memory_candidates = [
        row
        for row in load_jsons(root / "state" / "memory_candidates")
        if row.get("lifecycle_state") == "candidate" and row.get("decision_status") == "candidate"
    ]
    pack_index = (pack or {}).get("action_index", {})
    recommended_rows = (pack or {}).get("recommended_execution_order", [])

    summaries: list[dict[str, Any]] = []
    for task in tasks:
        task_id = task.get("task_id")
        latest_success = latest_execution_for_task(executions, task_id, success=True)
        latest_failure = latest_execution_for_task(executions, task_id, success=False)
        latest_queue = latest_queue_run_for_task(queue_runs, task_id)
        latest_bulk = latest_bulk_run_for_task(bulk_runs, task_id)
        blockers: list[str] = []
        if any(row.get("task_id") == task_id for row in reviews):
            blockers.append("pending_review")
        if any(row.get("task_id") == task_id for row in approvals):
            blockers.append("pending_approval")
        if any(row.get("task_id") == task_id for row in memory_candidates):
            blockers.append("memory_candidate")
        if latest_queue and latest_queue.get("failed_count", 0) > 0:
            blockers.append("queue_failure")
        if latest_bulk and latest_bulk.get("failed_count", 0) > 0:
            blockers.append("bulk_failure")

        recommended = next((row for row in recommended_rows if row.get("task_id") == task_id), None)
        history_action_id = (latest_failure or latest_success or {}).get("action_id")
        history_points_to_outdated_pack = bool(
            (latest_failure or {}).get("source_action_pack_validation_status") in {"expired", "fingerprint_invalid", "malformed"}
            or (latest_failure or {}).get("source_action_pack_id") and (pack or {}).get("action_pack_id") != (latest_failure or {}).get("source_action_pack_id")
            or (history_action_id and history_action_id not in pack_index)
        )
        summaries.append(
            {
                "task_id": task_id,
                "status": task.get("status"),
                "latest_successful_operator_action": latest_success,
                "latest_failed_operator_action": latest_failure,
                "latest_queue_run": latest_queue,
                "latest_bulk_run": latest_bulk,
                "open_manual_blockers": blockers,
                "recommended_next_action_id": (recommended or {}).get("action_id"),
                "recommended_next_command": (recommended or {}).get("recommended_command"),
                "recommended_next_reason": (recommended or {}).get("reason"),
                "history_points_to_outdated_pack": history_points_to_outdated_pack,
            }
        )
    return summaries


def _recommendation(
    *,
    category: str,
    priority: str,
    reason: str,
    suggestion: str,
    task_id: str | None = None,
    action_id: str | None = None,
) -> dict[str, Any]:
    target = action_id or task_id or category
    return {
        "recommendation_id": f"triage:{category}:{str(target).replace(':', '_')}",
        "category": category,
        "priority": priority,
        "task_id": task_id,
        "action_id": action_id,
        "reason": reason,
        "suggested_command": suggestion,
    }


def build_triage_data(root: Path, *, limit: int = 10, allow_pack_rebuild: bool = True) -> dict[str, Any]:
    if allow_pack_rebuild:
        pack, pack_path, pack_meta, pack_error = resolve_newest_valid_pack(root, limit=limit)
    else:
        pack, pack_path, pack_meta, pack_error = inspect_current_pack_only(root)
    current_pack = load_current_action_pack_summary(root)
    executions = sort_recent(load_jsons(root / "state" / "operator_action_executions"), "completed_at", "started_at")
    queue_runs = sort_recent(load_jsons(root / "state" / "operator_queue_runs"), "completed_at", "started_at")
    bulk_runs = sort_recent(load_jsons(root / "state" / "operator_bulk_runs"), "completed_at", "started_at")
    reviews = [row for row in load_jsons(root / "state" / "reviews") if row.get("status") == "pending"]
    approvals = [row for row in load_jsons(root / "state" / "approvals") if row.get("status") == "pending"]
    memory_candidates = [
        row
        for row in load_jsons(root / "state" / "memory_candidates")
        if row.get("lifecycle_state") == "candidate" and row.get("decision_status") == "candidate"
    ]
    repeated = detect_repeated_problems(root, pack=pack)
    pack_index = (pack or {}).get("action_index", {})
    recommended_order = (pack or {}).get("recommended_execution_order", [])

    queue_failures = [row for row in queue_runs if row.get("failed_count", 0) > 0][:limit]
    bulk_failures = [row for row in bulk_runs if row.get("failed_count", 0) > 0][:limit]
    expired_pack_refusals = [
        row for row in executions if row.get("failure_kind") == "expired_pack"
    ][:limit]
    pinned_pack_failures = [
        row for row in executions if row.get("failure_kind") == "pinned_pack_validation_failed"
    ][:limit]

    per_task = build_task_intervention_summaries(root, pack=pack, task_limit=limit)
    recommendations: list[dict[str, Any]] = []

    if pack_error is not None or current_pack.get("status") != "valid":
        recommendations.append(
            _recommendation(
                category="action_pack",
                priority="high",
                reason=f"Current action pack status is `{current_pack.get('status')}`; refresh the bounded snapshot before resuming manual operations.",
                suggestion=f"python3 scripts/operator_checkpoint_action_pack.py --root {root}",
            )
        )

    if reviews and recommended_order:
        first = next((row for row in recommended_order if row.get("category") == "pending_review"), None)
        if first:
            recommendations.append(
                _recommendation(
                    category="pending_review",
                    priority="high",
                    task_id=first.get("task_id"),
                    action_id=first.get("action_id"),
                    reason="Pending reviews are the highest-priority manual blockers in the current pack.",
                    suggestion=f"python3 scripts/operator_action_executor.py --root {root} --action-id {first['action_id']}",
                )
            )

    if approvals:
        first = next((row for row in recommended_order if row.get("category") == "pending_approval"), None)
        if first:
            recommendations.append(
                _recommendation(
                    category="pending_approval",
                    priority="high",
                    task_id=first.get("task_id"),
                    action_id=first.get("action_id"),
                    reason="Pending approvals still need explicit operator decisions and remain blocked by default queue policy.",
                    suggestion=f"python3 scripts/operator_action_executor.py --root {root} --action-id {first['action_id']}",
                )
            )

    if memory_candidates:
        first = next((row for row in recommended_order if row.get("category") == "memory_candidate"), None)
        if first:
            recommendations.append(
                _recommendation(
                    category="memory_candidate",
                    priority="medium",
                    task_id=first.get("task_id"),
                    action_id=first.get("action_id"),
                    reason="Ralph-produced memory candidates remain candidates until explicitly promoted or rejected.",
                    suggestion=f"python3 scripts/operator_action_executor.py --root {root} --action-id {first['action_id']}",
                )
            )

    if queue_failures:
        latest = queue_failures[0]
        recommendations.append(
            _recommendation(
                category="queue_failure",
                priority="high",
                reason="A recent queue run failed and needs inspection before unattended wrapper automation continues.",
                suggestion=f"python3 -m json.tool {root / 'state' / 'operator_queue_runs' / (latest['queue_run_id'] + '.json')}",
            )
        )

    if bulk_failures:
        latest = bulk_failures[0]
        recommendations.append(
            _recommendation(
                category="bulk_failure",
                priority="medium",
                reason="A recent bulk run failed; inspect the bounded per-action results before retrying.",
                suggestion=f"python3 -m json.tool {root / 'state' / 'operator_bulk_runs' / (latest['bulk_run_id'] + '.json')}",
            )
        )

    if repeated["repeated_idempotency_skips"]:
        row = repeated["repeated_idempotency_skips"][0]
        if row.get("action_id") in pack_index:
            recommendations.append(
                _recommendation(
                    category="idempotency",
                    priority="medium",
                    task_id=row.get("task_id"),
                    action_id=row.get("action_id"),
                    reason="The same action keeps being skipped because it already succeeded. Only rerun it if you truly intend to override duplicate protection.",
                    suggestion=f"python3 scripts/operator_action_executor.py --root {root} --action-id {row['action_id']} --force",
                )
            )

    if repeated["repeated_stale_actions"]:
        row = repeated["repeated_stale_actions"][0]
        recommendations.append(
            _recommendation(
                category="stale_action",
                priority="high",
                task_id=row.get("task_id"),
                action_id=row.get("action_id"),
                reason="This action keeps resolving as stale. Do not rerun it; inspect the new pack or explain the ledger history first.",
                suggestion=f"python3 scripts/operator_action_explain.py --root {root} --action-id {row.get('action_id')}",
            )
        )

    if repeated["actions_missing_from_newest_pack"]:
        row = repeated["actions_missing_from_newest_pack"][0]
        recommendations.append(
            _recommendation(
                category="missing_from_newest_pack",
                priority="high",
                task_id=row.get("task_id"),
                action_id=row.get("action_id"),
                reason="Ledger history references an action that no longer exists in the newest valid pack. Regenerate the pack or select a new action id.",
                suggestion=f"python3 scripts/operator_checkpoint_action_pack.py --root {root}",
            )
        )

    health = {
        "pending_review_count": len(reviews),
        "pending_approval_count": len(approvals),
        "candidate_memory_count": len(memory_candidates),
        "queue_failure_count": len(queue_failures),
        "bulk_failure_count": len(bulk_failures),
        "policy_skip_count": sum(1 for row in queue_runs for item in row.get("skipped_actions", []) if item.get("skip_kind") == "policy")
        + sum(1 for row in bulk_runs for item in row.get("skipped_actions", []) if item.get("skip_kind") == "policy"),
        "stale_skip_count": sum(1 for row in queue_runs for item in row.get("skipped_actions", []) if item.get("skip_kind") == "stale_action")
        + sum(1 for row in bulk_runs for item in row.get("skipped_actions", []) if item.get("skip_kind") == "stale_action"),
        "idempotency_skip_count": sum(1 for row in queue_runs for item in row.get("skipped_actions", []) if item.get("skip_kind") == "idempotency")
        + sum(1 for row in bulk_runs for item in row.get("skipped_actions", []) if item.get("skip_kind") == "idempotency"),
        "expired_pack_refusal_count": len(expired_pack_refusals),
        "pinned_pack_validation_failure_count": len(pinned_pack_failures),
        "current_action_pack_freshness_status": current_pack.get("status"),
        "current_action_pack_expiry_time": current_pack.get("expires_at"),
    }

    return {
        "generated_at": now_iso(),
        "current_action_pack": current_pack,
        "newest_valid_action_pack": {
            "path": str(pack_path),
            "action_pack_id": (pack or {}).get("action_pack_id"),
            "action_pack_fingerprint": (pack or {}).get("action_pack_fingerprint"),
            "validation_status": pack_meta.get("status"),
            "resolution": pack_meta.get("resolution"),
            "rebuild_reason": pack_meta.get("rebuild_reason"),
            "error": pack_error,
        },
        "highest_priority_manual_blockers": {
            "pending_reviews": reviews[:limit],
            "pending_approvals": approvals[:limit],
            "memory_candidates_needing_decision": memory_candidates[:limit],
            "queue_failures": queue_failures,
            "bulk_failures": bulk_failures,
            "repeated_stale_actions": repeated["repeated_stale_actions"][:limit],
            "repeated_idempotency_skips": repeated["repeated_idempotency_skips"][:limit],
            "pinned_pack_validation_failures": pinned_pack_failures,
            "expired_pack_refusals": expired_pack_refusals,
            "actions_missing_from_newest_pack": repeated["actions_missing_from_newest_pack"][:limit],
        },
        "per_task_intervention_summary": per_task,
        "control_plane_health_summary": health,
        "repeated_problem_detectors": repeated,
        "recommended_operator_interventions": recommendations[: max(limit, 5)],
    }


def build_triage_markdown(pack: dict[str, Any]) -> str:
    lines = [
        "# Operator Triage Pack",
        "",
        f"Generated at: {pack['generated_at']}",
        "",
        "## Control-Plane Health",
    ]
    health = pack.get("control_plane_health_summary", {})
    for key, value in health.items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Highest-Priority Manual Blockers"])
    blockers = pack.get("highest_priority_manual_blockers", {})
    for key, value in blockers.items():
        lines.append(f"- {key}: {len(value) if isinstance(value, list) else value}")

    lines.extend(["", "## Recommended Operator Interventions"])
    for row in pack.get("recommended_operator_interventions", []):
        lines.append(
            f"- [{row['priority']}] {row['category']} task={row.get('task_id')} action={row.get('action_id')} reason={row['reason']}"
        )
        if row.get("suggested_command"):
            lines.append(f"  command: `{row['suggested_command']}`")
    if not pack.get("recommended_operator_interventions"):
        lines.append("- none")

    lines.extend(["", "## Per-Task Intervention Summary"])
    for row in pack.get("per_task_intervention_summary", []):
        lines.append(
            f"- {row['task_id']}: blockers={row['open_manual_blockers']} next_action={row.get('recommended_next_action_id')} outdated_history={row['history_points_to_outdated_pack']}"
        )

    return "\n".join(lines).strip() + "\n"


def latest_failed_queue_run(root: Path) -> dict[str, Any] | None:
    rows = [row for row in sort_recent(load_jsons(root / "state" / "operator_queue_runs"), "completed_at", "started_at") if row.get("failed_count", 0) > 0]
    return rows[0] if rows else None


def latest_failed_bulk_run(root: Path) -> dict[str, Any] | None:
    rows = [row for row in sort_recent(load_jsons(root / "state" / "operator_bulk_runs"), "completed_at", "started_at") if row.get("failed_count", 0) > 0]
    return rows[0] if rows else None


def _category_risk_level(category: str, action_id: str | None = None) -> str:
    if category in {"queue_failure", "bulk_failure", "action_pack", "stale_action", "missing_from_newest_pack"}:
        return "low"
    if category == "pending_review":
        return "low"
    if category in {"pending_approval", "memory_candidate"}:
        return "medium"
    if category == "artifact_followup" and action_id and ("ship" in action_id or "publish" in action_id):
        return "high"
    return "medium"


def build_ranked_next_commands(root: Path, *, triage: dict[str, Any] | None = None, limit: int = 10) -> list[dict[str, Any]]:
    triage = triage or build_triage_data(root, limit=limit)
    current_pack = triage.get("current_action_pack", {})
    pack_rebuild_first = current_pack.get("status") != "valid"
    commands: list[dict[str, Any]] = []
    for index, row in enumerate(triage.get("recommended_operator_interventions", [])[:limit], start=1):
        category = str(row.get("category") or "")
        action_id = row.get("action_id")
        risk_level = _category_risk_level(category, action_id)
        requires_force = category == "idempotency"
        requires_pinned_pack = category == "pinned_pack_validation_failed"
        stale_risk = "high" if category in {"stale_action", "missing_from_newest_pack"} else "low"
        commands.append(
            {
                "command_id": f"ccmd_{index:02d}",
                "priority": row.get("priority", "medium"),
                "category": category,
                "task_id": row.get("task_id"),
                "action_id": action_id,
                "command": row.get("suggested_command") or "",
                "why_now": row.get("reason") or "",
                "risk_level": risk_level,
                "requires_force": requires_force,
                "requires_pinned_pack": requires_pinned_pack,
                "stale_risk": stale_risk,
                "pack_rebuild_first": pack_rebuild_first,
            }
        )
    return commands


def _health_label(triage: dict[str, Any]) -> str:
    current_pack = triage.get("current_action_pack", {})
    health = triage.get("control_plane_health_summary", {})
    repeated = triage.get("repeated_problem_detectors", {})
    if current_pack.get("status") != "valid":
        return "red"
    if health.get("queue_failure_count", 0) > 0 or health.get("bulk_failure_count", 0) > 0:
        return "red"
    if repeated.get("repeated_stale_actions") or repeated.get("repeated_pinned_pack_validation_failures"):
        return "red"
    if health.get("pending_review_count", 0) or health.get("pending_approval_count", 0) or health.get("candidate_memory_count", 0):
        return "yellow"
    return "green"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def compare_command_center_views(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if previous is None:
        return {
            "newly_appeared_blockers": current.get("comparison_basis", {}).get("blocker_keys", []),
            "resolved_blockers": [],
            "newly_failed_queue_runs": current.get("comparison_basis", {}).get("failed_queue_run_ids", []),
            "newly_failed_bulk_runs": current.get("comparison_basis", {}).get("failed_bulk_run_ids", []),
            "newly_repeated_stale_issues": current.get("comparison_basis", {}).get("repeated_stale_keys", []),
            "newly_repeated_idempotency_issues": current.get("comparison_basis", {}).get("repeated_idempotency_keys", []),
            "pack_change": {"before": None, "after": current.get("comparison_basis", {}).get("pack_signature")},
            "new_recommended_interventions": current.get("comparison_basis", {}).get("recommendation_ids", []),
            "disappeared_recommendations": [],
        }

    prev_basis = previous.get("comparison_basis", {})
    curr_basis = current.get("comparison_basis", {})
    return {
        "newly_appeared_blockers": sorted(set(curr_basis.get("blocker_keys", [])) - set(prev_basis.get("blocker_keys", []))),
        "resolved_blockers": sorted(set(prev_basis.get("blocker_keys", [])) - set(curr_basis.get("blocker_keys", []))),
        "newly_failed_queue_runs": sorted(set(curr_basis.get("failed_queue_run_ids", [])) - set(prev_basis.get("failed_queue_run_ids", []))),
        "newly_failed_bulk_runs": sorted(set(curr_basis.get("failed_bulk_run_ids", [])) - set(prev_basis.get("failed_bulk_run_ids", []))),
        "newly_repeated_stale_issues": sorted(set(curr_basis.get("repeated_stale_keys", [])) - set(prev_basis.get("repeated_stale_keys", []))),
        "newly_repeated_idempotency_issues": sorted(set(curr_basis.get("repeated_idempotency_keys", [])) - set(prev_basis.get("repeated_idempotency_keys", []))),
        "pack_change": {
            "before": prev_basis.get("pack_signature"),
            "after": curr_basis.get("pack_signature"),
            "changed": prev_basis.get("pack_signature") != curr_basis.get("pack_signature"),
        },
        "new_recommended_interventions": sorted(set(curr_basis.get("recommendation_ids", [])) - set(prev_basis.get("recommendation_ids", []))),
        "disappeared_recommendations": sorted(set(prev_basis.get("recommendation_ids", [])) - set(curr_basis.get("recommendation_ids", []))),
    }


def _lane_summary_from_executions(executions: list[dict[str, Any]], lane: str) -> dict[str, Any]:
    rows = [row for row in executions if row.get("invoked_by", "executor") == lane]
    recent = sort_recent(rows, "completed_at", "started_at")
    recent_failures = [row for row in recent if not row.get("success", False)]
    recent_skips = [
        row
        for row in recent
        if row.get("failure_kind") in {"already_executed", "stale_action", "expired_pack", "pinned_pack_validation_failed"}
    ]
    last_bad = recent_failures[0] if recent_failures else None
    return {
        "recent_success_count": sum(1 for row in recent if row.get("success", False)),
        "recent_failure_count": len(recent_failures),
        "recent_skip_count": len(recent_skips),
        "recent_stale_count": sum(1 for row in recent if row.get("failure_kind") == "stale_action"),
        "recent_idempotency_count": sum(1 for row in recent if row.get("failure_kind") == "already_executed"),
        "recent_policy_count": 0,
        "last_run_timestamp": (recent[0] if recent else {}).get("completed_at"),
        "last_bad_outcome_summary": (last_bad or {}).get("failure_reason") or (last_bad or {}).get("stderr_snapshot", ""),
    }


def build_per_lane_health(root: Path, *, triage: dict[str, Any] | None = None) -> dict[str, Any]:
    triage = triage or build_triage_data(root, limit=10)
    executions = load_jsons(root / "state" / "operator_action_executions")
    queue_runs = sort_recent(load_jsons(root / "state" / "operator_queue_runs"), "completed_at", "started_at")
    bulk_runs = sort_recent(load_jsons(root / "state" / "operator_bulk_runs"), "completed_at", "started_at")
    interventions = list_task_interventions(root)
    autofix_runs = list_safe_autofix_runs(root)
    triage_pack = _read_json(root / "state" / "logs" / "operator_triage_pack.json")

    queue_last_bad = next((row for row in queue_runs if row.get("failed_count", 0) > 0), None)
    bulk_last_bad = next((row for row in bulk_runs if row.get("failed_count", 0) > 0), None)
    repeated = triage.get("repeated_problem_detectors", {})
    return {
        "executor": _lane_summary_from_executions(executions, "executor"),
        "resume": _lane_summary_from_executions(executions, "resume"),
        "queue": {
            "recent_success_count": sum(1 for row in queue_runs if row.get("ok", False)),
            "recent_failure_count": sum(1 for row in queue_runs if not row.get("ok", False)),
            "recent_skip_count": sum(row.get("skipped_count", 0) for row in queue_runs[:10]),
            "recent_stale_count": sum(1 for row in queue_runs[:10] for item in row.get("skipped_actions", []) if item.get("skip_kind") == "stale_action"),
            "recent_idempotency_count": sum(1 for row in queue_runs[:10] for item in row.get("skipped_actions", []) if item.get("skip_kind") == "idempotency"),
            "recent_policy_count": sum(1 for row in queue_runs[:10] for item in row.get("skipped_actions", []) if item.get("skip_kind") == "policy"),
            "last_run_timestamp": (queue_runs[0] if queue_runs else {}).get("completed_at"),
            "last_bad_outcome_summary": (queue_last_bad or {}).get("stop_reason", ""),
        },
        "bulk": {
            "recent_success_count": sum(1 for row in bulk_runs if row.get("ok", False)),
            "recent_failure_count": sum(1 for row in bulk_runs if not row.get("ok", False)),
            "recent_skip_count": sum(row.get("skipped_count", 0) for row in bulk_runs[:10]),
            "recent_stale_count": sum(1 for row in bulk_runs[:10] for item in row.get("skipped_actions", []) if item.get("skip_kind") == "stale_action"),
            "recent_idempotency_count": sum(1 for row in bulk_runs[:10] for item in row.get("skipped_actions", []) if item.get("skip_kind") == "idempotency"),
            "recent_policy_count": sum(1 for row in bulk_runs[:10] for item in row.get("skipped_actions", []) if item.get("skip_kind") == "policy"),
            "last_run_timestamp": (bulk_runs[0] if bulk_runs else {}).get("completed_at"),
            "last_bad_outcome_summary": (bulk_last_bad or {}).get("stop_reason", ""),
        },
        "triage": {
            "recent_success_count": 1 if triage_pack else 0,
            "recent_failure_count": 0 if triage_pack else 1,
            "recent_skip_count": 0,
            "recent_stale_count": len(repeated.get("repeated_stale_actions", [])),
            "recent_idempotency_count": len(repeated.get("repeated_idempotency_skips", [])),
            "recent_policy_count": 0,
            "last_run_timestamp": (triage_pack or {}).get("generated_at"),
            "last_bad_outcome_summary": "" if triage_pack else "No triage pack has been generated.",
        },
        "intervene": {
            "recent_success_count": sum(1 for row in interventions if row.get("ok", False)),
            "recent_failure_count": sum(1 for row in interventions if not row.get("ok", False)),
            "recent_skip_count": 0,
            "recent_stale_count": sum(1 for row in interventions[:10] if any("no longer" in str(item) for item in row.get("blocker_summary", []))),
            "recent_idempotency_count": sum(1 for row in interventions[:10] if "already_executed" in row.get("blocker_summary", [])),
            "recent_policy_count": 0,
            "last_run_timestamp": (interventions[0] if interventions else {}).get("completed_at"),
            "last_bad_outcome_summary": "; ".join((interventions[0] or {}).get("blocker_summary", [])) if interventions and not interventions[0].get("ok", False) else "",
        },
        "safe_autofix": {
            "recent_success_count": sum(1 for row in autofix_runs if row.get("ok", False)),
            "recent_failure_count": sum(1 for row in autofix_runs if not row.get("ok", False)),
            "recent_skip_count": 0,
            "recent_stale_count": 0,
            "recent_idempotency_count": 0,
            "recent_policy_count": 0,
            "last_run_timestamp": (autofix_runs[0] if autofix_runs else {}).get("completed_at"),
            "last_bad_outcome_summary": "" if not autofix_runs or autofix_runs[0].get("ok", False) else "Latest safe-autofix run did not finish cleanly.",
        },
    }


def compare_triage_snapshots(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    current_blockers = current.get("highest_priority_manual_blockers", {})
    current_recs = {row.get("recommendation_id") for row in current.get("recommended_operator_interventions", [])}
    if previous is None:
        return {
            "blockers_added": sorted(k for k, v in current_blockers.items() if v),
            "blockers_removed": [],
            "recommendations_added": sorted(current_recs),
            "recommendations_removed": [],
            "repeated_problem_changes": current.get("repeated_problem_detectors", {}),
            "per_task_changes": current.get("per_task_intervention_summary", []),
            "health_deltas": current.get("control_plane_health_summary", {}),
        }
    previous_blockers = previous.get("highest_priority_manual_blockers", {})
    previous_recs = {row.get("recommendation_id") for row in previous.get("recommended_operator_interventions", [])}
    previous_health = previous.get("control_plane_health_summary", {})
    current_health = current.get("control_plane_health_summary", {})
    health_deltas = {}
    for key in sorted(set(previous_health) | set(current_health)):
        if previous_health.get(key) != current_health.get(key):
            health_deltas[key] = {"before": previous_health.get(key), "after": current_health.get(key)}
    return {
        "blockers_added": sorted(k for k, v in current_blockers.items() if v and not previous_blockers.get(k)),
        "blockers_removed": sorted(k for k, v in previous_blockers.items() if v and not current_blockers.get(k)),
        "recommendations_added": sorted(current_recs - previous_recs),
        "recommendations_removed": sorted(previous_recs - current_recs),
        "repeated_problem_changes": {
            key: {
                "before": len(previous.get("repeated_problem_detectors", {}).get(key, [])),
                "after": len(current.get("repeated_problem_detectors", {}).get(key, [])),
            }
            for key in sorted(set(previous.get("repeated_problem_detectors", {})) | set(current.get("repeated_problem_detectors", {})))
            if len(previous.get("repeated_problem_detectors", {}).get(key, [])) != len(current.get("repeated_problem_detectors", {}).get(key, []))
        },
        "per_task_changes": [
            row
            for row in current.get("per_task_intervention_summary", [])
            if next((prev for prev in previous.get("per_task_intervention_summary", []) if prev.get("task_id") == row.get("task_id")), {}) != row
        ],
        "health_deltas": health_deltas,
    }


def compare_action_pack_payloads(
    current_pack: dict[str, Any],
    other_pack: dict[str, Any],
    *,
    referenced_action_ids: set[str] | None = None,
) -> dict[str, Any]:
    current_index = current_pack.get("action_index", {})
    other_index = other_pack.get("action_index", {})
    current_ids = set(current_index)
    other_ids = set(other_index)
    categories_changed = []
    for action_id in sorted(current_ids & other_ids):
        if current_index[action_id].get("category") != other_index[action_id].get("category"):
            categories_changed.append(
                {
                    "action_id": action_id,
                    "before": other_index[action_id].get("category"),
                    "after": current_index[action_id].get("category"),
                }
            )
    current_order = [row.get("action_id") for row in current_pack.get("recommended_execution_order", [])]
    other_order = [row.get("action_id") for row in other_pack.get("recommended_execution_order", [])]
    referenced_action_ids = referenced_action_ids or set()
    return {
        "current_action_pack_id": current_pack.get("action_pack_id"),
        "other_action_pack_id": other_pack.get("action_pack_id"),
        "action_ids_added": sorted(current_ids - other_ids),
        "action_ids_removed": sorted(other_ids - current_ids),
        "categories_changed": categories_changed,
        "recommended_execution_order_added": [action_id for action_id in current_order if action_id not in other_order],
        "recommended_execution_order_removed": [action_id for action_id in other_order if action_id not in current_order],
        "freshness": {
            "current": {
                "generated_at": current_pack.get("generated_at"),
                "expires_at": current_pack.get("expires_at"),
            },
            "other": {
                "generated_at": other_pack.get("generated_at"),
                "expires_at": other_pack.get("expires_at"),
            },
        },
        "previously_referenced_action_ids_missing_now": sorted(action_id for action_id in referenced_action_ids if action_id not in current_ids),
    }


def build_command_center_data(root: Path, *, limit: int = 10, allow_pack_rebuild: bool = True) -> dict[str, Any]:
    triage = build_triage_data(root, limit=limit, allow_pack_rebuild=allow_pack_rebuild)
    next_commands = build_ranked_next_commands(root, triage=triage, limit=max(10, limit))
    latest_queue = sort_recent(load_jsons(root / "state" / "operator_queue_runs"), "completed_at", "started_at")
    latest_bulk = sort_recent(load_jsons(root / "state" / "operator_bulk_runs"), "completed_at", "started_at")
    interventions = list_task_interventions(root)
    autofix_runs = list_safe_autofix_runs(root)
    previous = _read_json(root / "state" / "logs" / "operator_command_center.json")
    top_tasks = [
        row["task_id"]
        for row in triage.get("per_task_intervention_summary", [])
        if row.get("open_manual_blockers") or row.get("recommended_next_action_id")
    ][:5]
    current_pack = triage.get("current_action_pack", {})
    repeated = triage.get("repeated_problem_detectors", {})
    pack_signature = {
        "action_pack_id": current_pack.get("action_pack_id"),
        "status": current_pack.get("status"),
        "resolution": triage.get("newest_valid_action_pack", {}).get("resolution"),
    }
    blocker_keys = [key for key, value in triage.get("highest_priority_manual_blockers", {}).items() if value]
    recommendation_ids = [row.get("recommendation_id") for row in triage.get("recommended_operator_interventions", [])]
    current = {
        "generated_at": now_iso(),
        "now": {
            "current_pack_freshness_state": current_pack,
            "top_blocker_categories": blocker_keys[:5],
            "top_recommended_interventions": triage.get("recommended_operator_interventions", [])[:5],
            "top_task_ids_needing_manual_action": top_tasks,
            "latest_queue_outcome": latest_queue[0] if latest_queue else None,
            "latest_bulk_outcome": latest_bulk[0] if latest_bulk else None,
            "latest_intervention_outcome": interventions[0] if interventions else None,
            "latest_safe_autofix_outcome": autofix_runs[0] if autofix_runs else None,
            "control_plane_health_label": _health_label(triage),
        },
        "next_actions": next_commands[:10],
        "recent_deltas": {},
        "per_lane_operator_control_health": build_per_lane_health(root, triage=triage),
        "fast_paths": {
            "rebuild_current_pack": f"python3 scripts/operator_checkpoint_action_pack.py --root {root}",
            "open_triage_pack": f"python3 -m json.tool {root / 'state' / 'logs' / 'operator_triage_pack.json'}",
            "explain_action": f"python3 scripts/operator_action_explain.py --root {root} --action-id ACTION_ID",
            "intervene_on_task": f"python3 scripts/operator_task_intervene.py --root {root} --task-id TASK_ID --dry-run",
            "safe_autofix_dry_run": f"python3 scripts/operator_safe_autofix.py --root {root} --dry-run-top-action",
            "safe_autofix_execute_safe_review": f"python3 scripts/operator_safe_autofix.py --root {root} --execute-safe-review",
            "inspect_latest_failed_queue_run": (
                f"python3 -m json.tool {root / 'state' / 'operator_queue_runs' / ((latest_failed_queue_run(root) or {}).get('queue_run_id', 'MISSING') + '.json')}"
                if latest_failed_queue_run(root)
                else ""
            ),
            "inspect_latest_failed_bulk_run": (
                f"python3 -m json.tool {root / 'state' / 'operator_bulk_runs' / ((latest_failed_bulk_run(root) or {}).get('bulk_run_id', 'MISSING') + '.json')}"
                if latest_failed_bulk_run(root)
                else ""
            ),
        },
        "list_counts": {
            "actions": len(list_actions_view(root, limit=100, allow_pack_rebuild=allow_pack_rebuild).get("rows", [])),
            "tasks": len(list_tasks_view(root, limit=100, allow_pack_rebuild=allow_pack_rebuild).get("rows", [])),
            "execution_runs": len(list_runs_view(root, kind="execution", limit=100).get("rows", [])),
            "queue_runs": len(list_runs_view(root, kind="queue", limit=100).get("rows", [])),
            "bulk_runs": len(list_runs_view(root, kind="bulk", limit=100).get("rows", [])),
            "intervention_runs": len(list_runs_view(root, kind="intervention", limit=100).get("rows", [])),
            "autofix_runs": len(list_runs_view(root, kind="autofix", limit=100).get("rows", [])),
        },
        "comparison_basis": {
            "blocker_keys": blocker_keys,
            "failed_queue_run_ids": [row.get("queue_run_id") for row in latest_queue if row.get("failed_count", 0) > 0][:10],
            "failed_bulk_run_ids": [row.get("bulk_run_id") for row in latest_bulk if row.get("failed_count", 0) > 0][:10],
            "repeated_stale_keys": [f"{row.get('task_id')}::{row.get('action_id')}" for row in repeated.get("repeated_stale_actions", [])],
            "repeated_idempotency_keys": [str(row.get("action_id")) for row in repeated.get("repeated_idempotency_skips", [])],
            "pack_signature": pack_signature,
            "recommendation_ids": recommendation_ids,
        },
        "triage_reference": {
            "current_action_pack": current_pack,
            "health": triage.get("control_plane_health_summary", {}),
        },
    }
    current["recent_deltas"] = compare_command_center_views(current, previous)
    return current


def build_command_center_markdown(pack: dict[str, Any]) -> str:
    lines = [
        "# Operator Command Center",
        "",
        f"Generated at: {pack['generated_at']}",
        f"Health: {pack['now']['control_plane_health_label']}",
        "",
        "## Now",
        f"- pack={pack['now']['current_pack_freshness_state'].get('action_pack_id')} status={pack['now']['current_pack_freshness_state'].get('status')} expires={pack['now']['current_pack_freshness_state'].get('expires_at')}",
        f"- blocker_categories={pack['now']['top_blocker_categories']}",
        f"- top_tasks={pack['now']['top_task_ids_needing_manual_action']}",
        "",
        "## Next Actions",
    ]
    for row in pack.get("next_actions", [])[:10]:
        lines.append(
            f"- [{row['priority']}] {row['category']} task={row.get('task_id')} action={row.get('action_id')} risk={row['risk_level']} stale_risk={row['stale_risk']}"
        )
        lines.append(f"  command: `{row['command']}`")
    if not pack.get("next_actions"):
        lines.append("- none")
    lines.extend(["", "## Recent Deltas"])
    for key, value in pack.get("recent_deltas", {}).items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines).strip() + "\n"


def build_decision_manifest_data(root: Path, *, limit: int = 10, allow_pack_rebuild: bool = True) -> dict[str, Any]:
    triage = build_triage_data(root, limit=limit, allow_pack_rebuild=allow_pack_rebuild)
    command_center = build_command_center_data(root, limit=limit, allow_pack_rebuild=allow_pack_rebuild)
    repeated = triage.get("repeated_problem_detectors", {})
    do_not_run = [
        {
            "action_id": row.get("action_id"),
            "task_id": row.get("task_id"),
            "reason": row.get("reason"),
        }
        for row in repeated.get("repeated_stale_actions", []) + repeated.get("actions_missing_from_newest_pack", [])
    ][:10]
    requires_force = [
        {
            "action_id": row.get("action_id"),
            "task_id": row.get("task_id"),
            "reason": row.get("reason"),
        }
        for row in repeated.get("repeated_idempotency_skips", [])
    ][:10]
    requires_pinned_pack = [
        {
            "action_id": row.get("action_id"),
            "task_id": row.get("task_id"),
            "reason": row.get("reason"),
            "source_action_pack_id": row.get("source_action_pack_id"),
        }
        for row in repeated.get("repeated_pinned_pack_validation_failures", [])
    ][:10]
    return {
        "generated_at": now_iso(),
        "current_pack_identity": triage.get("current_action_pack", {}),
        "ranked_next_commands": command_center.get("next_actions", [])[:10],
        "blockers_requiring_human_review": triage.get("highest_priority_manual_blockers", {}),
        "do_not_run_items": do_not_run,
        "actions_requiring_force": requires_force,
        "actions_requiring_pinned_pack": requires_pinned_pack,
        "actions_missing_from_newest_pack": repeated.get("actions_missing_from_newest_pack", [])[:10],
        "repeated_problem_alerts": repeated,
        "latest_intervention_context": list_task_interventions(root)[:3],
        "latest_safe_autofix_context": list_safe_autofix_runs(root)[:3],
    }


def build_decision_manifest_markdown(pack: dict[str, Any]) -> str:
    lines = [
        "# Operator Decision Manifest",
        "",
        f"Generated at: {pack['generated_at']}",
        f"Current pack: {pack['current_pack_identity'].get('action_pack_id')} status={pack['current_pack_identity'].get('status')}",
        "",
        "## Ranked Next Commands",
    ]
    for row in pack.get("ranked_next_commands", []):
        lines.append(f"- [{row['priority']}] {row['command_id']} {row['category']} task={row.get('task_id')} action={row.get('action_id')}")
        lines.append(f"  command: `{row['command']}`")
    lines.extend(["", "## Do Not Run"])
    for row in pack.get("do_not_run_items", []):
        lines.append(f"- task={row.get('task_id')} action={row.get('action_id')} reason={row.get('reason')}")
    if not pack.get("do_not_run_items"):
        lines.append("- none")
    return "\n".join(lines).strip() + "\n"


def list_actions_view(
    root: Path,
    *,
    category: str | None = None,
    task_id: str | None = None,
    prefix: str | None = None,
    limit: int = 20,
    only_safe: bool = False,
    only_blocked: bool = False,
    only_missing_from_newest_pack: bool = False,
    only_repeated_problems: bool = False,
    allow_pack_rebuild: bool = True,
) -> dict[str, Any]:
    triage = build_triage_data(root, limit=max(limit, 10), allow_pack_rebuild=allow_pack_rebuild)
    if allow_pack_rebuild:
        pack, _, _, _ = resolve_newest_valid_pack(root, limit=max(limit, 10))
    else:
        pack, _, _, _ = inspect_current_pack_only(root)
    repeated = triage.get("repeated_problem_detectors", {})
    repeated_action_ids = {
        row.get("action_id")
        for key in ("repeated_stale_actions", "repeated_idempotency_skips", "actions_missing_from_newest_pack")
        for row in repeated.get(key, [])
        if row.get("action_id")
    }
    missing_action_ids = {row.get("action_id") for row in repeated.get("actions_missing_from_newest_pack", []) if row.get("action_id")}
    action_rows: list[dict[str, Any]] = []
    rank_map = {row.get("action_id"): index for index, row in enumerate((pack or {}).get("recommended_execution_order", []), start=1)}
    for action in (pack or {}).get("action_index", {}).values():
        action_id = action.get("action_id")
        blockers: list[str] = []
        safe = True
        if any(row.get("action_id") == action_id for row in repeated.get("repeated_stale_actions", [])):
            blockers.append("repeated_stale_action")
            safe = False
        if any(row.get("action_id") == action_id for row in repeated.get("repeated_idempotency_skips", [])):
            blockers.append("repeated_idempotency_skip")
        if action_id in missing_action_ids:
            blockers.append("missing_from_newest_pack")
            safe = False
        if category and action.get("category") != category:
            continue
        if task_id and action.get("task_id") != task_id:
            continue
        if prefix and not str(action_id).startswith(prefix):
            continue
        if only_safe and not safe:
            continue
        if only_blocked and not blockers:
            continue
        if only_missing_from_newest_pack and action_id not in missing_action_ids:
            continue
        if only_repeated_problems and action_id not in repeated_action_ids:
            continue
        action_rows.append(
            {
                "action_id": action_id,
                "task_id": action.get("task_id"),
                "category": action.get("category"),
                "verb": action.get("verb"),
                "recommended_order_rank": rank_map.get(action_id),
                "current_pack_id": (pack or {}).get("action_pack_id"),
                "safe_to_run_now": safe,
                "blocker_reasons": blockers,
                "repeated_problem_flags": [reason for reason in blockers if reason.startswith("repeated_") or reason == "missing_from_newest_pack"],
                "suggested_command": (action.get("command") or {}).get("command", ""),
            }
        )
    if only_missing_from_newest_pack or only_repeated_problems:
        for missing in repeated.get("actions_missing_from_newest_pack", []):
            action_id = missing.get("action_id")
            if prefix and action_id and not str(action_id).startswith(prefix):
                continue
            if task_id and missing.get("task_id") != task_id:
                continue
            action_rows.append(
                {
                    "action_id": action_id,
                    "task_id": missing.get("task_id"),
                    "category": "missing_from_newest_pack",
                    "verb": "",
                    "recommended_order_rank": None,
                    "current_pack_id": (pack or {}).get("action_pack_id"),
                    "safe_to_run_now": False,
                    "blocker_reasons": ["missing_from_newest_pack"],
                    "repeated_problem_flags": ["missing_from_newest_pack"],
                    "suggested_command": f"python3 scripts/operator_action_explain.py --root {root} --action-id {action_id}" if action_id else "",
                }
            )
    return {
        "ok": True,
        "current_pack_id": (pack or {}).get("action_pack_id"),
        "rows": action_rows[:limit],
    }


def list_tasks_view(
    root: Path,
    *,
    needs_review: bool = False,
    needs_approval: bool = False,
    needs_memory_decision: bool = False,
    has_queue_failure: bool = False,
    has_bulk_failure: bool = False,
    has_repeated_problems: bool = False,
    limit: int = 20,
    allow_pack_rebuild: bool = True,
) -> dict[str, Any]:
    triage = build_triage_data(root, limit=max(limit, 10), allow_pack_rebuild=allow_pack_rebuild)
    repeated = triage.get("repeated_problem_detectors", {})
    repeated_task_ids = {
        row.get("task_id")
        for key in ("repeated_stale_actions", "actions_missing_from_newest_pack")
        for row in repeated.get(key, [])
        if row.get("task_id")
    }
    rows = []
    for row in triage.get("per_task_intervention_summary", []):
        blockers = row.get("open_manual_blockers", [])
        if needs_review and "pending_review" not in blockers:
            continue
        if needs_approval and "pending_approval" not in blockers:
            continue
        if needs_memory_decision and "memory_candidate" not in blockers:
            continue
        if has_queue_failure and "queue_failure" not in blockers:
            continue
        if has_bulk_failure and "bulk_failure" not in blockers:
            continue
        if has_repeated_problems and row.get("task_id") not in repeated_task_ids:
            continue
        latest_success = row.get("latest_successful_operator_action") or {}
        latest_failure = row.get("latest_failed_operator_action") or {}
        latest_queue = row.get("latest_queue_run") or {}
        latest_bulk = row.get("latest_bulk_run") or {}
        rows.append(
            {
                "task_id": row.get("task_id"),
                "status": row.get("status"),
                "blockers": blockers,
                "latest_successful_operator_action": latest_success.get("action_id"),
                "latest_failed_operator_action": latest_failure.get("action_id"),
                "latest_queue_run": latest_queue.get("queue_run_id"),
                "latest_bulk_run": latest_bulk.get("bulk_run_id"),
                "next_recommended_action_id": row.get("recommended_next_action_id"),
                "next_suggested_command": row.get("recommended_next_command"),
                "outdated_pack_history": row.get("history_points_to_outdated_pack"),
            }
        )
    return {"ok": True, "rows": rows[:limit]}


def list_runs_view(
    root: Path,
    *,
    kind: str,
    failed_only: bool = False,
    task_id: str | None = None,
    action_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    if kind == "execution":
        rows = sort_recent(load_jsons(root / "state" / "operator_action_executions"), "completed_at", "started_at")
        compact = []
        for row in rows:
            selected = row.get("selected_action") or {}
            if task_id and selected.get("task_id") != task_id:
                continue
            if action_id and row.get("action_id") != action_id:
                continue
            if failed_only and row.get("success", False):
                continue
            compact.append(
                {
                    "kind": kind,
                    "id": row.get("execution_id"),
                    "task_id": selected.get("task_id"),
                    "action_id": row.get("action_id"),
                    "ok": row.get("success", False),
                    "failure_kind": row.get("failure_kind"),
                    "completed_at": row.get("completed_at"),
                }
            )
        return {"ok": True, "rows": compact[:limit]}
    mapping = {
        "queue": ("operator_queue_runs", "queue_run_id"),
        "bulk": ("operator_bulk_runs", "bulk_run_id"),
        "intervention": ("operator_task_interventions", "intervention_id"),
        "autofix": ("operator_safe_autofix_runs", "autofix_run_id"),
    }
    folder_name, id_key = mapping[kind]
    rows = sort_recent(load_jsons(root / "state" / folder_name), "completed_at", "started_at")
    compact = []
    for row in rows:
        row_task_id = row.get("task_id")
        row_action_id = row.get("selected_action_id") or row.get("safe_action_selected")
        if task_id and row_task_id != task_id:
            if kind in {"queue", "bulk"} and not any(item.get("task_id") == task_id for item in row.get("executed_actions", []) + row.get("skipped_actions", [])):
                continue
        if action_id and row_action_id != action_id:
            if kind in {"queue", "bulk"} and not any(item.get("action_id") == action_id for item in row.get("executed_actions", []) + row.get("skipped_actions", [])):
                continue
        ok = row.get("ok", False)
        if failed_only and ok:
            continue
        compact.append(
            {
                "kind": kind,
                "id": row.get(id_key),
                "task_id": row_task_id,
                "action_id": row_action_id,
                "ok": ok,
                "completed_at": row.get("completed_at"),
            }
        )
    return {"ok": True, "rows": compact[:limit]}


def _action_related_codes(
    *,
    rank: int,
    category: str,
    action_id: str | None,
    pack: dict[str, Any] | None,
    default_pack_status: str,
    brief_reason: str,
    risk_level: str,
    stale_risk: str,
) -> dict[str, Any]:
    action_index = (pack or {}).get("action_index", {})
    action = action_index.get(action_id or "")
    target_id = (action or {}).get("target_id")
    related = [row for row in action_index.values() if row.get("category") == category and row.get("target_id") == target_id]
    allowed: list[str] = []
    reply_map: dict[str, dict[str, Any]] = {}

    def add(letter: str, operation: str, *, action_row: dict[str, Any] | None = None, requires_force: bool = False) -> None:
        code = f"{letter}{rank}"
        if code in allowed:
            return
        allowed.append(code)
        reply_map[code] = {
            "operation_kind": operation,
            "action_id": (action_row or action or {}).get("action_id"),
            "task_id": (action_row or action or {}).get("task_id"),
            "requires_force": requires_force,
            "requires_pinned_pack": False,
            "requires_pack_refresh_first": default_pack_status != "valid",
            "executable": operation == "execute_action",
            "reason": brief_reason,
            "suggested_command": ((action_row or action or {}).get("command") or {}).get("command", ""),
        }

    if category == "pending_review":
        primary = next((row for row in related if row.get("verb") == "approve"), action)
        reject = next((row for row in related if row.get("verb") == "reject"), None)
        add("A", "execute_action", action_row=primary)
        if reject:
            add("R", "execute_action", action_row=reject)
        add("X", "explain")
        default = f"A{rank}"
    elif category == "pending_approval":
        primary = next((row for row in related if row.get("verb") == "approve"), action)
        reject = next((row for row in related if row.get("verb") == "reject"), None)
        add("A", "execute_action", action_row=primary)
        if reject:
            add("R", "execute_action", action_row=reject)
        add("X", "explain")
        default = f"A{rank}"
    elif category == "memory_candidate":
        primary = next((row for row in related if row.get("verb") == "promote"), action)
        reject = next((row for row in related if row.get("verb") == "reject"), None)
        add("P", "execute_action", action_row=primary)
        if reject:
            add("R", "execute_action", action_row=reject)
        add("X", "explain")
        default = f"P{rank}"
    elif category == "idempotency":
        add("F", "execute_action", action_row=action, requires_force=True)
        add("X", "explain")
        default = f"X{rank}"
    elif category in {"stale_action", "missing_from_newest_pack", "action_pack"}:
        add("X", "explain")
        add("B", "rebuild_only")
        default = f"B{rank}" if category == "action_pack" else f"X{rank}"
    else:
        add("X", "explain")
        default = f"X{rank}"

    return {
        "primary_action": default[0],
        "allowed_reply_codes": allowed,
        "default_reply_code": default,
        "reply_map": reply_map,
        "brief_reason": brief_reason,
        "risk_level": risk_level,
        "stale_risk": stale_risk,
    }


def build_decision_inbox_data(root: Path, *, limit: int = 10, allow_pack_rebuild: bool = True) -> dict[str, Any]:
    triage = build_triage_data(root, limit=limit, allow_pack_rebuild=allow_pack_rebuild)
    command_center = build_command_center_data(root, limit=limit, allow_pack_rebuild=allow_pack_rebuild)
    if allow_pack_rebuild:
        pack, _, _, _ = resolve_newest_valid_pack(root, limit=limit)
    else:
        pack, _, _, _ = inspect_current_pack_only(root)
    current_pack = triage.get("current_action_pack", {})
    repeated = triage.get("repeated_problem_detectors", {})
    items: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    candidates.extend(triage.get("recommended_operator_interventions", [])[: limit * 2])
    for row in repeated.get("repeated_idempotency_skips", [])[:limit]:
        candidates.append(
            {
                "category": "idempotency",
                "priority": "medium",
                "task_id": row.get("task_id"),
                "action_id": row.get("action_id"),
                "reason": row.get("reason") or "Repeated idempotency skips suggest this can only rerun with explicit force.",
            }
        )
    for row in (repeated.get("repeated_stale_actions", []) + repeated.get("actions_missing_from_newest_pack", []))[:limit]:
        candidates.append(
            {
                "category": "stale_action" if row in repeated.get("repeated_stale_actions", []) else "missing_from_newest_pack",
                "priority": "high",
                "task_id": row.get("task_id"),
                "action_id": row.get("action_id"),
                "reason": row.get("reason") or "Item is stale or missing from the newest pack and should not be executed directly.",
            }
        )
    seen: set[str] = set()
    rank = 0
    for row in candidates:
        key = f"{row.get('category')}::{row.get('action_id') or row.get('task_id')}"
        if key in seen:
            continue
        seen.add(key)
        rank += 1
        category = str(row.get("category") or "")
        action_id = row.get("action_id")
        risk_level = _category_risk_level(category, action_id)
        stale_risk = "high" if category in {"stale_action", "missing_from_newest_pack"} else "low"
        reply_meta = _action_related_codes(
            rank=rank,
            category=category,
            action_id=action_id,
            pack=pack,
            default_pack_status=current_pack.get("status", "unknown"),
            brief_reason=str(row.get("reason") or ""),
            risk_level=risk_level,
            stale_risk=stale_risk,
        )
        items.append(
            {
                "inbox_item_id": f"inbox_{rank:02d}_{(action_id or row.get('task_id') or category).replace(':', '_')}",
                "rank": rank,
                "task_id": row.get("task_id"),
                "category": category,
                "action_id": action_id,
                "primary_action": reply_meta["primary_action"],
                "allowed_reply_codes": reply_meta["allowed_reply_codes"],
                "default_reply_code": reply_meta["default_reply_code"],
                "brief_reason": reply_meta["brief_reason"],
                "risk_level": risk_level,
                "stale_risk": stale_risk,
                "requires_force": any(code.startswith("F") for code in reply_meta["allowed_reply_codes"]),
                "requires_pinned_pack": False,
                "command_preview": next((value["suggested_command"] for value in reply_meta["reply_map"].values() if value.get("suggested_command")), ""),
                "pack_id": current_pack.get("action_pack_id"),
                "pack_status": current_pack.get("status"),
                "reply_map": reply_meta["reply_map"],
            }
        )
        if rank >= limit:
            break
    return {
        "generated_at": now_iso(),
        "pack_id": current_pack.get("action_pack_id"),
        "pack_status": current_pack.get("status"),
        "reply_ready": current_pack.get("status") == "valid" and bool(items),
        "top_reply_ready_commands": command_center.get("next_actions", [])[:5],
        "items": items,
    }


def build_decision_inbox_markdown(pack: dict[str, Any]) -> str:
    lines = [
        "# Operator Decision Inbox",
        "",
        f"Generated at: {pack['generated_at']}",
        f"Pack: {pack.get('pack_id')} status={pack.get('pack_status')} reply_ready={pack.get('reply_ready')}",
        "",
        "## Items",
    ]
    for row in pack.get("items", []):
        lines.append(
            f"- {row['default_reply_code']} task={row.get('task_id')} category={row['category']} action={row.get('action_id')} reason={row['brief_reason']}"
        )
        lines.append(f"  allowed={row['allowed_reply_codes']} preview=`{row['command_preview']}`")
    return "\n".join(lines).strip() + "\n"


def _tokenize_reply(reply: str) -> list[str]:
    return [token.strip().upper() for token in reply.replace(",", " ").split() if token.strip()]


def resolve_decision_inbox(root: Path, *, allow_rebuild: bool = True, limit: int = 10) -> tuple[dict[str, Any], Path]:
    path = root / "state" / "logs" / "operator_decision_inbox.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8")), path
        except Exception:
            pass
    if allow_rebuild:
        pack = build_decision_inbox_data(root, limit=limit, allow_pack_rebuild=True)
        path.write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
        (root / "state" / "logs" / "operator_decision_inbox.md").write_text(build_decision_inbox_markdown(pack), encoding="utf-8")
        return pack, path
    return {"generated_at": now_iso(), "items": [], "pack_id": None, "pack_status": "missing", "reply_ready": False}, path


def build_reply_plan(
    root: Path,
    *,
    reply_string: str,
    allow_inbox_rebuild: bool = True,
    limit: int = 10,
) -> dict[str, Any]:
    from runtime.core.models import new_id

    inbox, inbox_path = resolve_decision_inbox(root, allow_rebuild=allow_inbox_rebuild, limit=limit)
    item_by_code: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for item in inbox.get("items", []):
        for code, mapping in item.get("reply_map", {}).items():
            item_by_code[code.upper()] = (item, mapping)
    tokens = _tokenize_reply(reply_string)
    steps: list[dict[str, Any]] = []
    unknown_tokens: list[str] = []
    for token in tokens:
        resolved = item_by_code.get(token)
        if resolved is None:
            unknown_tokens.append(token)
            continue
        item, mapping = resolved
        steps.append(
            {
                "reply_code": token,
                "inbox_item_id": item.get("inbox_item_id"),
                "task_id": item.get("task_id"),
                "action_id": mapping.get("action_id"),
                "planned_operation_kind": mapping.get("operation_kind"),
                "requires_force": mapping.get("requires_force", False),
                "requires_pinned_pack": mapping.get("requires_pinned_pack", False),
                "requires_pack_refresh_first": mapping.get("requires_pack_refresh_first", False),
                "executable": mapping.get("executable", False),
                "reason": mapping.get("reason", ""),
                "suggested_command": mapping.get("suggested_command", ""),
            }
        )
    plan = {
        "plan_id": new_id("opreplyplan"),
        "created_at": now_iso(),
        "source_inbox_path": str(inbox_path),
        "source_inbox_generated_at": inbox.get("generated_at"),
        "source_action_pack_id": inbox.get("pack_id"),
        "source_action_pack_status": inbox.get("pack_status"),
        "reply_string": reply_string,
        "normalized_tokens": tokens,
        "unknown_tokens": unknown_tokens,
        "ok": not unknown_tokens,
        "steps": steps,
    }
    save_reply_plan_record(root, plan)
    return plan


def build_decision_shortlist_data(root: Path, *, limit: int = 5, allow_inbox_rebuild: bool = True) -> dict[str, Any]:
    inbox, _ = resolve_decision_inbox(root, allow_rebuild=allow_inbox_rebuild, limit=max(limit, 10))
    rows = [
        {
            "rank": row.get("rank"),
            "inbox_item_id": row.get("inbox_item_id"),
            "default_reply_code": row.get("default_reply_code"),
            "task_id": row.get("task_id"),
            "brief_reason": row.get("brief_reason"),
            "command_preview": row.get("command_preview"),
        }
        for row in inbox.get("items", [])[:limit]
    ]
    return {
        "generated_at": now_iso(),
        "pack_id": inbox.get("pack_id"),
        "pack_status": inbox.get("pack_status"),
        "rows": rows,
    }


def build_decision_shortlist_markdown(pack: dict[str, Any]) -> str:
    lines = ["# Operator Decision Shortlist", "", f"Pack: {pack.get('pack_id')} status={pack.get('pack_status')}", ""]
    for row in pack.get("rows", []):
        lines.append(f"- {row['default_reply_code']} task={row.get('task_id')} reason={row.get('brief_reason')}")
    return "\n".join(lines).strip() + "\n"


def compare_inbox_snapshots(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    curr_items = {row.get("inbox_item_id"): row for row in current.get("items", [])}
    if previous is None:
        return {
            "items_added": sorted(curr_items),
            "items_removed": [],
            "reply_codes_added": sorted(code for row in curr_items.values() for code in row.get("allowed_reply_codes", [])),
            "reply_codes_removed": [],
            "default_reply_changed": [],
            "safe_status_changed": [],
            "became_stale_or_disappeared": [],
            "pack_diff": {"before": None, "after": {"pack_id": current.get("pack_id"), "pack_status": current.get("pack_status")}},
        }
    prev_items = {row.get("inbox_item_id"): row for row in previous.get("items", [])}
    return {
        "items_added": sorted(set(curr_items) - set(prev_items)),
        "items_removed": sorted(set(prev_items) - set(curr_items)),
        "reply_codes_added": sorted({code for row in curr_items.values() for code in row.get("allowed_reply_codes", [])} - {code for row in prev_items.values() for code in row.get("allowed_reply_codes", [])}),
        "reply_codes_removed": sorted({code for row in prev_items.values() for code in row.get("allowed_reply_codes", [])} - {code for row in curr_items.values() for code in row.get("allowed_reply_codes", [])}),
        "default_reply_changed": [
            inbox_item_id
            for inbox_item_id in sorted(set(curr_items) & set(prev_items))
            if curr_items[inbox_item_id].get("default_reply_code") != prev_items[inbox_item_id].get("default_reply_code")
        ],
        "safe_status_changed": [
            inbox_item_id
            for inbox_item_id in sorted(set(curr_items) & set(prev_items))
            if curr_items[inbox_item_id].get("pack_status") != prev_items[inbox_item_id].get("pack_status")
            or curr_items[inbox_item_id].get("task_id") != prev_items[inbox_item_id].get("task_id")
            or curr_items[inbox_item_id].get("action_id") != prev_items[inbox_item_id].get("action_id")
            or curr_items[inbox_item_id].get("brief_reason") != prev_items[inbox_item_id].get("brief_reason")
        ],
        "became_stale_or_disappeared": [
            inbox_item_id
            for inbox_item_id in sorted(set(prev_items))
            if inbox_item_id not in curr_items or curr_items.get(inbox_item_id, {}).get("stale_risk") == "high"
        ],
        "pack_diff": {
            "before": {"pack_id": previous.get("pack_id"), "pack_status": previous.get("pack_status")},
            "after": {"pack_id": current.get("pack_id"), "pack_status": current.get("pack_status")},
        },
    }
