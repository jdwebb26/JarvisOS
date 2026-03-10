#!/usr/bin/env python3
from __future__ import annotations

import json
import re
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


def operator_reply_ingress_dir(root: Path) -> Path:
    path = root / "state" / "operator_reply_ingress"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_reply_ingress_results_dir(root: Path) -> Path:
    path = root / "state" / "operator_reply_ingress_results"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_reply_ingress_runs_dir(root: Path) -> Path:
    path = root / "state" / "operator_reply_ingress_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_reply_messages_dir(root: Path) -> Path:
    path = root / "state" / "operator_reply_messages"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_reply_transport_cycles_dir(root: Path) -> Path:
    path = root / "state" / "operator_reply_transport_cycles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_reply_transport_replay_plans_dir(root: Path) -> Path:
    path = root / "state" / "operator_reply_transport_replay_plans"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_reply_transport_replays_dir(root: Path) -> Path:
    path = root / "state" / "operator_reply_transport_replays"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_outbound_packets_dir(root: Path) -> Path:
    path = root / "state" / "operator_outbound_packets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_imported_reply_messages_dir(root: Path) -> Path:
    path = root / "state" / "operator_imported_reply_messages"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_gateway_inbound_messages_dir(root: Path) -> Path:
    path = root / "state" / "operator_gateway_inbound_messages"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_bridge_cycles_dir(root: Path) -> Path:
    path = root / "state" / "operator_bridge_cycles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_bridge_replay_plans_dir(root: Path) -> Path:
    path = root / "state" / "operator_bridge_replay_plans"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_bridge_replays_dir(root: Path) -> Path:
    path = root / "state" / "operator_bridge_replays"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_doctor_reports_dir(root: Path) -> Path:
    path = root / "state" / "operator_doctor_reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_remediation_plans_dir(root: Path) -> Path:
    path = root / "state" / "operator_remediation_plans"
    path.mkdir(parents=True, exist_ok=True)
    return path


REPLY_TOKEN_PATTERN = re.compile(r"^[A-Z]\d+$")
EXECUTABLE_REPLY_PREFIXES = {"A", "R", "P", "F"}
REPORT_ONLY_REPLY_PREFIXES = {"X", "B"}


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


def save_reply_ingress_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_reply_ingress_dir(root) / f"{record['ingress_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    latest_path = triage_logs_dir(root) / "operator_reply_ingress_latest.json"
    latest_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def save_reply_ingress_result(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_reply_ingress_results_dir(root) / f"{record['ingress_result_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def save_reply_ingress_run(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_reply_ingress_runs_dir(root) / f"{record['run_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def save_reply_transport_cycle_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_reply_transport_cycles_dir(root) / f"{record['transport_cycle_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def save_reply_transport_replay_plan_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_reply_transport_replay_plans_dir(root) / f"{record['replay_plan_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def save_reply_transport_replay_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_reply_transport_replays_dir(root) / f"{record['replay_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def save_outbound_packet_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_outbound_packets_dir(root) / f"{record['outbound_packet_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    latest_path = triage_logs_dir(root) / "operator_outbound_packet_latest.json"
    latest_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def save_imported_reply_message_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_imported_reply_messages_dir(root) / f"{record['import_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    latest_path = triage_logs_dir(root) / "operator_import_reply_message_latest.json"
    latest_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def save_bridge_cycle_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_bridge_cycles_dir(root) / f"{record['bridge_cycle_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def save_bridge_replay_plan_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_bridge_replay_plans_dir(root) / f"{record['bridge_replay_plan_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def save_bridge_replay_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_bridge_replays_dir(root) / f"{record['bridge_replay_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def save_doctor_report_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_doctor_reports_dir(root) / f"{record['doctor_report_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    latest_path = triage_logs_dir(root) / "operator_doctor_latest.json"
    latest_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def save_remediation_plan_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = operator_remediation_plans_dir(root) / f"{record['remediation_plan_id']}.json"
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


def list_reply_ingress_records(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_reply_ingress_dir(root)), "completed_at", "created_at")


def list_reply_ingress_results(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_reply_ingress_results_dir(root)), "created_at", "completed_at")


def list_reply_ingress_runs(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_reply_ingress_runs_dir(root)), "completed_at", "started_at")


def list_reply_transport_cycles(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_reply_transport_cycles_dir(root)), "completed_at", "started_at")


def list_reply_transport_replay_plans(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_reply_transport_replay_plans_dir(root)), "created_at", "started_at")


def list_reply_transport_replays(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_reply_transport_replays_dir(root)), "completed_at", "started_at")


def list_outbound_packets(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_outbound_packets_dir(root)), "generated_at", "created_at")


def list_imported_reply_messages(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_imported_reply_messages_dir(root)), "completed_at", "created_at")


def list_bridge_cycles(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_bridge_cycles_dir(root)), "completed_at", "started_at")


def list_bridge_replay_plans(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_bridge_replay_plans_dir(root)), "created_at", "started_at")


def list_bridge_replays(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_bridge_replays_dir(root)), "completed_at", "started_at")


def list_doctor_reports(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_doctor_reports_dir(root)), "completed_at", "started_at")


def list_remediation_plans(root: Path) -> list[dict[str, Any]]:
    return sort_recent(load_jsons(operator_remediation_plans_dir(root)), "completed_at", "started_at")


def count_pending_reply_messages(root: Path) -> int:
    count = 0
    for row in load_jsons(operator_reply_messages_dir(root)):
        if not row.get("processed_at"):
            count += 1
    return count


def normalize_reply_tokens(raw_text: str) -> list[str]:
    return [token.strip().upper() for token in raw_text.replace(",", " ").split() if token.strip()]


def classify_compact_reply_text(raw_text: str) -> dict[str, Any]:
    normalized_text = " ".join(normalize_reply_tokens(raw_text))
    tokens = normalize_reply_tokens(raw_text)
    if not tokens:
        return {
            "normalized_text": normalized_text,
            "reply_tokens": [],
            "is_reply_candidate": False,
            "classification": "ignored_non_reply",
            "ignore_reason": "No compact reply tokens were present.",
            "invalid_tokens": [],
        }
    invalid_shape = [token for token in tokens if not REPLY_TOKEN_PATTERN.match(token)]
    if invalid_shape:
        return {
            "normalized_text": normalized_text,
            "reply_tokens": tokens,
            "is_reply_candidate": False,
            "classification": "ignored_non_reply",
            "ignore_reason": "Message does not match the bounded compact reply grammar.",
            "invalid_tokens": invalid_shape,
        }
    unknown_prefix = [token for token in tokens if token[0] not in EXECUTABLE_REPLY_PREFIXES | REPORT_ONLY_REPLY_PREFIXES]
    if unknown_prefix:
        return {
            "normalized_text": normalized_text,
            "reply_tokens": tokens,
            "is_reply_candidate": True,
            "classification": "invalid_reply",
            "ignore_reason": "",
            "invalid_tokens": unknown_prefix,
        }
    return {
        "normalized_text": normalized_text,
        "reply_tokens": tokens,
        "is_reply_candidate": True,
        "classification": "reply_candidate",
        "ignore_reason": "",
        "invalid_tokens": [],
    }


def latest_reply_ingress_for_message_id(root: Path, source_message_id: str) -> dict[str, Any] | None:
    if not source_message_id:
        return None
    for row in list_reply_ingress_records(root):
        if row.get("source_message_id") == source_message_id:
            return row
    return None


def current_decision_inbox_path(root: Path) -> Path:
    return triage_logs_dir(root) / "operator_decision_inbox.json"


def load_current_decision_inbox(root: Path) -> tuple[dict[str, Any] | None, Path, str | None]:
    path = current_decision_inbox_path(root)
    if not path.exists():
        return None, path, "missing_inbox"
    try:
        return json.loads(path.read_text(encoding="utf-8")), path, None
    except Exception:
        return None, path, "malformed_inbox"


def classify_decision_inbox_freshness(root: Path, inbox: dict[str, Any] | None) -> tuple[str, dict[str, Any], str]:
    current_pack = load_current_action_pack_summary(root)
    if inbox is None:
        return "missing_inbox", current_pack, "Decision inbox is missing."
    inbox_pack_id = inbox.get("pack_id")
    inbox_pack_status = inbox.get("pack_status")
    current_pack_id = current_pack.get("action_pack_id")
    current_pack_status = current_pack.get("status")
    if current_pack_status != "valid":
        return "pack_refresh_required", current_pack, f"Current action pack status is `{current_pack_status}`."
    if inbox_pack_status != "valid":
        return "stale_inbox", current_pack, f"Decision inbox pack status is `{inbox_pack_status}`."
    if inbox_pack_id and current_pack_id and inbox_pack_id != current_pack_id:
        return "stale_inbox", current_pack, "Decision inbox references an older action pack snapshot."
    return "valid", current_pack, "Decision inbox matches the current valid action pack."


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
    source_inbox: dict[str, Any] | None = None,
    source_inbox_path: Path | None = None,
) -> dict[str, Any]:
    from runtime.core.models import new_id

    if source_inbox is None:
        inbox, inbox_path = resolve_decision_inbox(root, allow_rebuild=allow_inbox_rebuild, limit=limit)
    else:
        inbox = source_inbox
        inbox_path = source_inbox_path or current_decision_inbox_path(root)
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


def build_reply_preview_data(
    root: Path,
    *,
    reply_string: str,
    allow_inbox_rebuild: bool = True,
    limit: int = 10,
    source_inbox: dict[str, Any] | None = None,
    source_inbox_path: Path | None = None,
) -> dict[str, Any]:
    inbox = source_inbox
    if inbox is None:
        inbox, _ = resolve_decision_inbox(root, allow_rebuild=allow_inbox_rebuild, limit=limit)
    plan = build_reply_plan(
        root,
        reply_string=reply_string,
        allow_inbox_rebuild=allow_inbox_rebuild,
        limit=limit,
        source_inbox=inbox,
        source_inbox_path=source_inbox_path,
    )
    return {
        "ok": plan.get("ok", False),
        "normalized_reply_tokens": plan.get("normalized_tokens", []),
        "matched_inbox_items": [step.get("inbox_item_id") for step in plan.get("steps", [])],
        "blocked_or_unknown_tokens": plan.get("unknown_tokens", []),
        "steps": [
            {
                "reply_code": step.get("reply_code"),
                "operation_kind": step.get("planned_operation_kind"),
                "task_id": step.get("task_id"),
                "action_id": step.get("action_id"),
                "requires_pack_refresh_first": step.get("requires_pack_refresh_first"),
                "suggested_command": step.get("suggested_command"),
            }
            for step in plan.get("steps", [])
        ],
        "any_stale_items": any(item.get("stale_risk") == "high" for item in (inbox or {}).get("items", [])),
        "pack_refresh_recommended_first": (inbox or {}).get("pack_status") != "valid",
        "plan": plan,
    }


def ingest_operator_reply(
    root: Path,
    *,
    raw_text: str,
    source_kind: str,
    source_lane: str,
    source_channel: str,
    source_message_id: str,
    source_user: str,
    mode: str,
    dry_run: bool,
    continue_on_failure: bool,
    force_duplicate: bool = False,
) -> tuple[dict[str, Any], int]:
    from runtime.core.models import new_id
    from scripts.operator_apply_reply import apply_reply

    created_at = now_iso()
    normalized = classify_compact_reply_text(raw_text)
    inbox, inbox_path, inbox_error = load_current_decision_inbox(root)
    inbox_generated_at = inbox.get("generated_at") if inbox else None
    inbox_status, current_pack, inbox_reason = classify_decision_inbox_freshness(root, inbox)

    ingress = {
        "ingress_id": new_id("opreplying"),
        "created_at": created_at,
        "source_kind": source_kind,
        "source_lane": source_lane,
        "source_channel": source_channel,
        "source_message_id": source_message_id,
        "source_user": source_user,
        "raw_text": raw_text,
        "normalized_text": normalized["normalized_text"],
        "reply_tokens": normalized["reply_tokens"],
        "matched_plan_id": None,
        "decision_inbox_path": str(inbox_path),
        "decision_inbox_generated_at": inbox_generated_at,
        "source_action_pack_id": current_pack.get("action_pack_id"),
        "source_action_pack_status": current_pack.get("status"),
        "parse_ok": False,
        "applied": False,
        "dry_run": dry_run,
        "ignored": False,
        "ignore_reason": "",
        "result_kind": "",
        "result_ref_id": None,
        "completed_at": None,
    }
    result = {
        "ingress_result_id": new_id("opreplyres"),
        "ingress_id": ingress["ingress_id"],
        "created_at": created_at,
        "classification": normalized["classification"],
        "result_kind": "",
        "ok": False,
        "source_message_id": source_message_id,
        "reply_tokens": normalized["reply_tokens"],
        "payload": {},
    }

    duplicate = latest_reply_ingress_for_message_id(root, source_message_id) if source_message_id else None
    if duplicate and not force_duplicate:
        ingress["ignored"] = True
        ingress["ignore_reason"] = f"Duplicate source_message_id `{source_message_id}` already processed."
        ingress["result_kind"] = "duplicate_message"
        ingress["result_ref_id"] = duplicate.get("ingress_id")
        ingress["completed_at"] = now_iso()
        result["result_kind"] = "duplicate_message"
        result["payload"] = {"duplicate_of": duplicate.get("ingress_id")}
        save_reply_ingress_record(root, ingress)
        save_reply_ingress_result(root, result)
        return {
            "ok": False,
            "classification": normalized["classification"],
            "result_kind": "duplicate_message",
            "ingress_record": ingress,
            "result_record": result,
        }, 1

    if normalized["classification"] == "ignored_non_reply":
        ingress["ignored"] = True
        ingress["ignore_reason"] = normalized["ignore_reason"]
        ingress["result_kind"] = "ignored_non_reply"
        ingress["completed_at"] = now_iso()
        result["result_kind"] = "ignored_non_reply"
        result["ok"] = True
        result["payload"] = {"ignore_reason": normalized["ignore_reason"]}
        save_reply_ingress_record(root, ingress)
        save_reply_ingress_result(root, result)
        return {
            "ok": True,
            "classification": "ignored_non_reply",
            "result_kind": "ignored_non_reply",
            "ingress_record": ingress,
            "result_record": result,
        }, 0

    if normalized["classification"] == "invalid_reply":
        ingress["parse_ok"] = False
        ingress["result_kind"] = "invalid_reply"
        ingress["result_ref_id"] = result["ingress_result_id"]
        ingress["completed_at"] = now_iso()
        result["result_kind"] = "invalid_reply"
        result["payload"] = {"unknown_tokens": normalized["invalid_tokens"]}
        save_reply_ingress_record(root, ingress)
        save_reply_ingress_result(root, result)
        return {
            "ok": False,
            "classification": "invalid_reply",
            "result_kind": "invalid_reply",
            "ingress_record": ingress,
            "result_record": result,
        }, 1

    if inbox_error == "missing_inbox":
        ingress["ignored"] = False
        ingress["ignore_reason"] = "Decision inbox is missing."
        ingress["result_kind"] = "missing_inbox"
        ingress["completed_at"] = now_iso()
        result["result_kind"] = "missing_inbox"
        result["payload"] = {"reason": "Decision inbox is missing. Build the inbox before ingesting replies."}
        save_reply_ingress_record(root, ingress)
        save_reply_ingress_result(root, result)
        return {
            "ok": False,
            "classification": normalized["classification"],
            "result_kind": "missing_inbox",
            "ingress_record": ingress,
            "result_record": result,
        }, 1

    if inbox_status != "valid":
        ingress["ignored"] = False
        ingress["ignore_reason"] = inbox_reason
        ingress["result_kind"] = "pack_refresh_required" if inbox_status == "pack_refresh_required" else "stale_inbox"
        ingress["completed_at"] = now_iso()
        result["result_kind"] = ingress["result_kind"]
        result["payload"] = {"reason": inbox_reason, "pack_status": current_pack.get("status"), "inbox_status": inbox_status}
        save_reply_ingress_record(root, ingress)
        save_reply_ingress_result(root, result)
        return {
            "ok": False,
            "classification": normalized["classification"],
            "result_kind": ingress["result_kind"],
            "ingress_record": ingress,
            "result_record": result,
        }, 1

    plan = build_reply_plan(
        root,
        reply_string=normalized["normalized_text"],
        allow_inbox_rebuild=False,
        source_inbox=inbox,
        source_inbox_path=inbox_path,
    )
    ingress["matched_plan_id"] = plan.get("plan_id")
    ingress["parse_ok"] = plan.get("ok", False)
    result["payload"]["reply_plan"] = plan
    if not plan.get("ok", False):
        ingress["result_kind"] = "invalid_reply"
        ingress["result_ref_id"] = plan.get("plan_id")
        ingress["completed_at"] = now_iso()
        result["result_kind"] = "invalid_reply"
        result["payload"]["unknown_tokens"] = plan.get("unknown_tokens", [])
        save_reply_ingress_record(root, ingress)
        save_reply_ingress_result(root, result)
        return {
            "ok": False,
            "classification": "invalid_reply",
            "result_kind": "invalid_reply",
            "ingress_record": ingress,
            "result_record": result,
            "reply_plan": plan,
        }, 1

    if mode == "plan":
        ingress["result_kind"] = "planned_only"
        ingress["result_ref_id"] = plan.get("plan_id")
        ingress["completed_at"] = now_iso()
        result["result_kind"] = "planned_only"
        result["ok"] = True
        save_reply_ingress_record(root, ingress)
        save_reply_ingress_result(root, result)
        return {
            "ok": True,
            "classification": "reply_candidate",
            "result_kind": "planned_only",
            "ingress_record": ingress,
            "result_record": result,
            "reply_plan": plan,
        }, 0

    if mode == "preview":
        preview = build_reply_preview_data(
            root,
            reply_string=normalized["normalized_text"],
            allow_inbox_rebuild=False,
            source_inbox=inbox,
            source_inbox_path=inbox_path,
        )
        ingress["result_kind"] = "preview_only"
        ingress["result_ref_id"] = plan.get("plan_id")
        ingress["completed_at"] = now_iso()
        result["result_kind"] = "preview_only"
        result["ok"] = bool(preview.get("ok"))
        result["payload"]["preview"] = preview
        save_reply_ingress_record(root, ingress)
        save_reply_ingress_result(root, result)
        return {
            "ok": bool(preview.get("ok")),
            "classification": "reply_candidate",
            "result_kind": "preview_only",
            "ingress_record": ingress,
            "result_record": result,
            "reply_plan": plan,
            "preview": preview,
        }, 0 if preview.get("ok") else 1

    apply_payload, exit_code = apply_reply(
        root,
        reply_string=normalized["normalized_text"],
        plan_id=plan.get("plan_id"),
        dry_run=dry_run,
        continue_on_failure=continue_on_failure,
    )
    ingress["applied"] = True
    ingress["result_kind"] = "applied" if apply_payload.get("ok") else "blocked"
    ingress["result_ref_id"] = apply_payload.get("reply_apply_id")
    ingress["completed_at"] = now_iso()
    result["result_kind"] = ingress["result_kind"]
    result["ok"] = bool(apply_payload.get("ok"))
    result["payload"]["apply"] = apply_payload
    save_reply_ingress_record(root, ingress)
    save_reply_ingress_result(root, result)
    return {
        "ok": bool(apply_payload.get("ok")),
        "classification": "reply_candidate",
        "result_kind": ingress["result_kind"],
        "ingress_record": ingress,
        "result_record": result,
        "reply_plan": plan,
        "apply_payload": apply_payload,
    }, exit_code


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


def reply_transport_readiness(root: Path, *, allow_inbox_rebuild: bool = False, limit: int = 5) -> dict[str, Any]:
    current_pack = load_current_action_pack_summary(root)
    inbox, inbox_path = resolve_decision_inbox(root, allow_rebuild=allow_inbox_rebuild, limit=limit)
    pending_count = count_pending_reply_messages(root)
    ready = current_pack.get("status") == "valid" and bool(inbox.get("reply_ready"))
    reason = "Reply transport is ready."
    if current_pack.get("status") != "valid":
        reason = f"Current action pack status is `{current_pack.get('status')}`."
    elif not inbox.get("reply_ready"):
        reason = "Decision inbox is not reply-ready."
    return {
        "ready": ready,
        "reason": reason,
        "pack_id": current_pack.get("action_pack_id"),
        "pack_status": current_pack.get("status"),
        "decision_inbox_path": str(inbox_path),
        "decision_inbox_generated_at": inbox.get("generated_at"),
        "pending_inbound_message_count": pending_count,
    }


def build_operator_outbound_prompt_data(root: Path, *, limit: int = 5, allow_inbox_rebuild: bool = True) -> dict[str, Any]:
    inbox, inbox_path = resolve_decision_inbox(root, allow_rebuild=allow_inbox_rebuild, limit=max(limit, 5))
    shortlist = build_decision_shortlist_data(root, limit=min(limit, 5), allow_inbox_rebuild=allow_inbox_rebuild)
    readiness = reply_transport_readiness(root, allow_inbox_rebuild=allow_inbox_rebuild, limit=max(limit, 5))
    top_items = [
        {
            "rank": row.get("rank"),
            "default_reply_code": row.get("default_reply_code"),
            "task_id": row.get("task_id"),
            "category": row.get("category"),
            "brief_reason": row.get("brief_reason"),
            "command_preview": row.get("command_preview"),
        }
        for row in inbox.get("items", [])[: min(limit, 5)]
    ]
    warning = ""
    if not readiness["ready"]:
        warning = readiness["reason"]
    elif any(code.startswith("B") for row in inbox.get("items", [])[: min(limit, 5)] for code in row.get("allowed_reply_codes", [])):
        warning = "Some top items require rebuild-first or explain-only handling before execution."
    return {
        "generated_at": now_iso(),
        "pack_id": inbox.get("pack_id"),
        "pack_status": inbox.get("pack_status"),
        "reply_ready": inbox.get("reply_ready"),
        "top_items": top_items,
        "compact_reply_instructions": [
            "Reply with compact deterministic codes only: A#, R#, P#, X#, B#, F#.",
            "Use A/R/P only when the inbox exposes them for that item.",
            "Use X# to explain an item and B# to rebuild or refresh first.",
            "Use F# only for items that explicitly support force reruns.",
        ],
        "warning": warning,
        "decision_inbox_path": str(inbox_path),
        "decision_inbox_generated_at": inbox.get("generated_at"),
        "pending_inbound_message_count": readiness["pending_inbound_message_count"],
        "shortlist_rows": shortlist.get("rows", []),
    }


def build_operator_outbound_prompt_markdown(prompt: dict[str, Any]) -> str:
    lines = [
        "# Operator Outbound Prompt",
        "",
        f"Generated at: {prompt.get('generated_at')}",
        f"Pack: {prompt.get('pack_id')} status={prompt.get('pack_status')} reply_ready={prompt.get('reply_ready')}",
    ]
    if prompt.get("warning"):
        lines.extend(["", f"Warning: {prompt['warning']}"])
    lines.extend(["", "## Top Reply Items"])
    for row in prompt.get("top_items", []):
        lines.append(
            f"- {row.get('default_reply_code')} task={row.get('task_id')} category={row.get('category')} reason={row.get('brief_reason')}"
        )
    lines.extend(["", "## Compact Reply Instructions"])
    for row in prompt.get("compact_reply_instructions", []):
        lines.append(f"- {row}")
    return "\n".join(lines).strip() + "\n"


def gateway_operator_bridge_readiness(root: Path, *, allow_inbox_rebuild: bool = False, limit: int = 5) -> dict[str, Any]:
    reply_ready = reply_transport_readiness(root, allow_inbox_rebuild=allow_inbox_rebuild, limit=limit)
    outbound_publish_ready = reply_ready["ready"]
    inbound_import_ready = True
    bridge_ready = outbound_publish_ready and inbound_import_ready
    return {
        "outbound_publish_ready": outbound_publish_ready,
        "inbound_import_ready": inbound_import_ready,
        "bridge_ready": bridge_ready,
        "reason": reply_ready["reason"],
        "pack_id": reply_ready["pack_id"],
        "pack_status": reply_ready["pack_status"],
        "pending_inbound_message_count": reply_ready["pending_inbound_message_count"],
    }


def build_operator_outbound_packet_data(root: Path, *, limit: int = 5, allow_inbox_rebuild: bool = True) -> dict[str, Any]:
    prompt = build_operator_outbound_prompt_data(root, limit=limit, allow_inbox_rebuild=allow_inbox_rebuild)
    ack = build_operator_reply_ack_data(root, limit=min(limit, 5), allow_inbox_rebuild=False)
    readiness = gateway_operator_bridge_readiness(root, allow_inbox_rebuild=False, limit=limit)
    return {
        "generated_at": now_iso(),
        "pack_id": prompt.get("pack_id"),
        "pack_status": prompt.get("pack_status"),
        "reply_ready": prompt.get("reply_ready"),
        "top_items": prompt.get("top_items", [])[: min(limit, 5)],
        "compact_reply_instructions": prompt.get("compact_reply_instructions", []),
        "minimal_warning": prompt.get("warning", "") or readiness["reason"],
        "reply_ack_context": {
            "latest_result_kind": ((ack.get("latest_reply_received") or {}).get("result_kind")),
            "next_guidance": ack.get("next_guidance", ""),
            "next_suggested_codes": ack.get("next_suggested_codes", [])[:3],
        },
        "bridge_readiness": readiness,
    }


def build_operator_outbound_packet_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# Operator Outbound Packet",
        "",
        f"Generated at: {packet.get('generated_at')}",
        f"Pack: {packet.get('pack_id')} status={packet.get('pack_status')} reply_ready={packet.get('reply_ready')}",
    ]
    if packet.get("minimal_warning"):
        lines.extend(["", f"Warning: {packet['minimal_warning']}"])
    lines.extend(["", "## Top Items"])
    for row in packet.get("top_items", []):
        lines.append(f"- {row.get('default_reply_code')} task={row.get('task_id')} reason={row.get('brief_reason')}")
    lines.extend(["", "## Reply Instructions"])
    for row in packet.get("compact_reply_instructions", []):
        lines.append(f"- {row}")
    return "\n".join(lines).strip() + "\n"


def compact_outbound_packet_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "outbound_packet_id": row.get("outbound_packet_id"),
        "generated_at": row.get("generated_at"),
        "pack_id": row.get("pack_id"),
        "pack_status": row.get("pack_status"),
        "reply_ready": row.get("reply_ready"),
        "top_item_count": len(row.get("top_items", [])),
        "warning": row.get("minimal_warning", ""),
    }


def classify_gateway_inbound_operator_message(payload: dict[str, Any]) -> dict[str, Any]:
    raw_text = str(payload.get("raw_text", ""))
    classification = classify_compact_reply_text(raw_text)
    if classification["classification"] == "reply_candidate":
        return {
            **classification,
            "classification": "importable_compact_reply",
            "reason": "Inbound payload matches the deterministic compact reply grammar.",
        }
    if classification["classification"] == "invalid_reply":
        return {
            **classification,
            "reason": "Inbound payload looks like compact reply grammar but uses unsupported tokens.",
        }
    return {
        **classification,
        "reason": classification["ignore_reason"],
    }


def import_gateway_reply_message(
    root: Path,
    *,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from runtime.core.models import new_id
    from scripts.operator_enqueue_reply_message import enqueue_reply_message

    created_at = now_iso()
    source_message_id = str(payload.get("source_message_id", "")).strip() or new_id("opgwmsg")
    classification = classify_gateway_inbound_operator_message(payload)
    record = {
        "import_id": new_id("opimport"),
        "created_at": created_at,
        "completed_at": None,
        "source_kind": str(payload.get("source_kind", "gateway")),
        "source_lane": str(payload.get("source_lane", "operator")),
        "source_channel": str(payload.get("source_channel", "gateway")),
        "source_message_id": source_message_id,
        "source_user": str(payload.get("source_user", "operator")),
        "raw_text": str(payload.get("raw_text", "")),
        "normalized_text": classification.get("normalized_text"),
        "reply_tokens": classification.get("reply_tokens", []),
        "classification": classification.get("classification"),
        "apply": bool(payload.get("apply", False)),
        "preview": bool(payload.get("preview", False)),
        "dry_run": bool(payload.get("dry_run", False)),
        "continue_on_failure": bool(payload.get("continue_on_failure", False)),
        "gateway_message_path": str(payload.get("gateway_message_path", "")) or None,
        "imported": False,
        "import_reason": classification.get("reason", ""),
        "reply_message_path": None,
    }
    if classification["classification"] == "importable_compact_reply":
        enqueued = enqueue_reply_message(
            root,
            raw_text=record["raw_text"],
            source_kind=record["source_kind"],
            source_lane=record["source_lane"],
            source_channel=record["source_channel"],
            source_message_id=record["source_message_id"],
            source_user=record["source_user"],
            apply=bool(payload.get("apply", False)),
            preview=bool(payload.get("preview", False)),
            dry_run=bool(payload.get("dry_run", False)),
            continue_on_failure=bool(payload.get("continue_on_failure", False)),
        )
        record["imported"] = True
        record["reply_message_path"] = enqueued["path"]
    record["completed_at"] = now_iso()
    save_imported_reply_message_record(root, record)
    return record


def compact_imported_reply_message_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "import_id": row.get("import_id"),
        "source_message_id": row.get("source_message_id"),
        "source_kind": row.get("source_kind"),
        "source_channel": row.get("source_channel"),
        "source_user": row.get("source_user"),
        "classification": row.get("classification"),
        "apply": row.get("apply", False),
        "preview": row.get("preview", False),
        "dry_run": row.get("dry_run", False),
        "imported": row.get("imported", False),
        "reply_message_path": row.get("reply_message_path"),
        "gateway_message_path": row.get("gateway_message_path"),
        "completed_at": row.get("completed_at"),
    }


def list_imported_reply_messages_view(root: Path, *, limit: int = 20) -> dict[str, Any]:
    rows = list_imported_reply_messages(root)[:limit]
    return {
        "generated_at": now_iso(),
        "count": len(rows),
        "rows": [compact_imported_reply_message_summary(row) for row in rows],
    }


def list_outbound_packets_view(root: Path, *, limit: int = 20) -> dict[str, Any]:
    rows = list_outbound_packets(root)[:limit]
    return {
        "generated_at": now_iso(),
        "count": len(rows),
        "rows": [compact_outbound_packet_summary(row) for row in rows],
    }


def _reply_ack_guidance(result_kind: str, inbox: dict[str, Any]) -> tuple[str, list[str]]:
    if result_kind == "applied":
        return (
            "Reply was applied through existing wrapper guards.",
            [row.get("default_reply_code") for row in inbox.get("items", [])[:3] if row.get("default_reply_code")],
        )
    if result_kind in {"missing_inbox", "stale_inbox", "pack_refresh_required"}:
        return ("Refresh the bounded pack/inbox before sending another execute reply.", ["B1", "X1"])
    if result_kind == "duplicate_message":
        return ("This source_message_id was already processed. Use a new message id if you truly intend to retry.", ["X1"])
    if result_kind == "invalid_reply":
        return ("Reply was not valid compact grammar for the current inbox.", [row.get("default_reply_code") for row in inbox.get("items", [])[:2]])
    if result_kind == "ignored_non_reply":
        return ("Message was ignored because it was not compact reply grammar.", [])
    return ("Inspect the latest inbox or explain the target item before retrying.", [row.get("default_reply_code") for row in inbox.get("items", [])[:2]])


def build_operator_reply_ack_data(root: Path, *, limit: int = 5, allow_inbox_rebuild: bool = False) -> dict[str, Any]:
    inbox, inbox_path = resolve_decision_inbox(root, allow_rebuild=allow_inbox_rebuild, limit=max(limit, 5))
    ingress_rows = list_reply_ingress_records(root)
    result_rows = list_reply_ingress_results(root)
    apply_rows = list_reply_applies(root)
    plan_rows = list_reply_plans(root)
    latest_ingress = ingress_rows[0] if ingress_rows else None
    latest_result = result_rows[0] if result_rows else None
    latest_apply = apply_rows[0] if apply_rows else None
    latest_plan = plan_rows[0] if plan_rows else None
    result_kind = (latest_ingress or {}).get("result_kind") or (latest_result or {}).get("result_kind") or ""
    guidance, next_codes = _reply_ack_guidance(result_kind, inbox)
    blocked_reasons: list[str] = []
    if latest_apply:
        for row in latest_apply.get("per_step_results", [])[:limit]:
            if row.get("status") in {"skipped_stale", "skipped_idempotency", "failed_execution", "plan_blocked", "invalid_reply"}:
                blocked_reasons.append(str(row.get("status")))
    if latest_result and isinstance(latest_result.get("payload"), dict):
        reason = latest_result["payload"].get("reason")
        if reason:
            blocked_reasons.append(str(reason))
    return {
        "generated_at": now_iso(),
        "decision_inbox_path": str(inbox_path),
        "latest_reply_received": latest_ingress,
        "matched_plan": latest_plan if latest_plan and latest_plan.get("plan_id") == (latest_ingress or {}).get("matched_plan_id") else latest_plan,
        "latest_apply_or_preview_outcome": latest_apply or (latest_result or {}).get("payload", {}).get("preview"),
        "blocked_or_skipped_reasons": blocked_reasons,
        "next_guidance": guidance,
        "next_suggested_codes": [code for code in next_codes if code][: min(limit, 5)],
        "reply_transport_ready": reply_transport_readiness(root, allow_inbox_rebuild=False, limit=max(limit, 5)),
    }


def build_operator_reply_ack_markdown(pack: dict[str, Any]) -> str:
    latest = pack.get("latest_reply_received") or {}
    lines = [
        "# Operator Reply Ack",
        "",
        f"Generated at: {pack.get('generated_at')}",
        f"Latest reply: message_id={latest.get('source_message_id')} result={latest.get('result_kind')} user={latest.get('source_user')}",
        f"Guidance: {pack.get('next_guidance')}",
    ]
    if pack.get("blocked_or_skipped_reasons"):
        lines.extend(["", "Blocked/Skipped"])
        for row in pack.get("blocked_or_skipped_reasons", []):
            lines.append(f"- {row}")
    if pack.get("next_suggested_codes"):
        lines.extend(["", "Next Suggested Codes"])
        for row in pack.get("next_suggested_codes", []):
            lines.append(f"- {row}")
    return "\n".join(lines).strip() + "\n"


def compact_reply_transport_cycle(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "transport_cycle_id": row.get("transport_cycle_id"),
        "mode": row.get("mode"),
        "dry_run": row.get("dry_run", False),
        "ok": row.get("ok", False),
        "attempted_count": row.get("attempted_count", 0),
        "applied_count": row.get("applied_count", 0),
        "blocked_count": row.get("blocked_count", 0),
        "ignored_count": row.get("ignored_count", 0),
        "invalid_count": row.get("invalid_count", 0),
        "stop_reason": row.get("stop_reason", ""),
        "outbound_prompt_pack_id": row.get("outbound_prompt_pack_id"),
        "reply_ack_result_kind": row.get("reply_ack_result_kind"),
        "processed_source_message_ids": row.get("processed_source_message_ids", [])[:5],
        "completed_at": row.get("completed_at"),
    }


def list_reply_transport_cycles_view(
    root: Path,
    *,
    limit: int = 20,
    failed_only: bool = False,
    mode: str | None = None,
) -> dict[str, Any]:
    rows = list_reply_transport_cycles(root)
    if failed_only:
        rows = [row for row in rows if not row.get("ok", False)]
    if mode:
        rows = [row for row in rows if row.get("mode") == mode]
    rows = rows[:limit]
    return {
        "generated_at": now_iso(),
        "count": len(rows),
        "rows": [compact_reply_transport_cycle(row) for row in rows],
    }


def load_reply_transport_cycle(root: Path, cycle_id: str) -> dict[str, Any] | None:
    path = operator_reply_transport_cycles_dir(root) / f"{cycle_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    for row in list_reply_transport_cycles(root):
        if row.get("transport_cycle_id") == cycle_id:
            return row
    return None


def _load_json_file(path: Path | str | None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_reply_messages_for_cycle(root: Path, cycle: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for path_text in cycle.get("processed_message_paths", []):
        payload = _load_json_file(path_text)
        if payload is not None:
            payload["_message_path"] = str(path_text)
            messages.append(payload)
    if messages:
        return messages
    message_rows = load_jsons(operator_reply_messages_dir(root))
    source_ids = set(cycle.get("processed_source_message_ids", []))
    ingress_ids = set(cycle.get("processed_ingress_ids", []))
    for row in message_rows:
        if row.get("source_message_id") in source_ids or row.get("ingress_id") in ingress_ids:
            messages.append(row)
    return messages


def inspect_reply_transport_cycle(root: Path, *, cycle_id: str | None = None) -> dict[str, Any]:
    rows = list_reply_transport_cycles(root)
    cycle = load_reply_transport_cycle(root, cycle_id) if cycle_id else (rows[0] if rows else None)
    if cycle is None:
        return {"ok": False, "error": f"Reply transport cycle not found: {cycle_id}" if cycle_id else "No reply transport cycles found."}
    outbound = _load_json_file(cycle.get("outbound_prompt_path"))
    ack = _load_json_file(cycle.get("reply_ack_path"))
    handoff = _load_json_file(cycle.get("handoff_path"))
    ingress_run = None
    ingress_run_id = cycle.get("reply_ingress_run_id")
    if ingress_run_id:
        ingress_run = _load_json_file(operator_reply_ingress_runs_dir(root) / f"{ingress_run_id}.json")
    messages = _load_reply_messages_for_cycle(root, cycle)
    replay_safety = classify_reply_transport_replay_safety(root, cycle=cycle, live_apply_requested=False)
    return {
        "ok": True,
        "cycle": compact_reply_transport_cycle(cycle),
        "paths": {
            "outbound_prompt_path": cycle.get("outbound_prompt_path"),
            "reply_ack_path": cycle.get("reply_ack_path"),
            "handoff_path": cycle.get("handoff_path"),
            "ingress_run_id": ingress_run_id,
        },
        "counts": {
            "message_count": len(messages),
            "processed_ingress_count": len(cycle.get("processed_ingress_ids", [])),
            "attempted_count": cycle.get("attempted_count", 0),
            "blocked_count": cycle.get("blocked_count", 0),
        },
        "stop_reason": cycle.get("stop_reason", ""),
        "result_summary": {
            "reply_ack_result_kind": cycle.get("reply_ack_result_kind"),
            "outbound_prompt_pack_id": cycle.get("outbound_prompt_pack_id"),
        },
        "provenance": {
            "outbound_prompt": {"path": cycle.get("outbound_prompt_path"), "pack_id": (outbound or {}).get("pack_id")},
            "reply_ack": {"path": cycle.get("reply_ack_path"), "latest_result_kind": ((ack or {}).get("latest_reply_received") or {}).get("result_kind")},
            "handoff": {"path": cycle.get("handoff_path"), "generated_at": (handoff or {}).get("generated_at")},
            "ingress_run": ingress_run,
        },
        "replay_safety": replay_safety,
        "messages": [
            {
                "source_message_id": row.get("source_message_id"),
                "raw_text": row.get("raw_text"),
                "apply": row.get("apply", False),
                "preview": row.get("preview", False),
                "dry_run": row.get("dry_run", False),
                "processed_at": row.get("processed_at"),
                "result_kind": row.get("result_kind"),
            }
            for row in messages[:10]
        ],
    }


def compare_reply_transport_cycle_records(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    current_ids = set(current.get("processed_source_message_ids", []))
    previous_ids = set((previous or {}).get("processed_source_message_ids", []))
    return {
        "current_cycle_id": current.get("transport_cycle_id"),
        "other_cycle_id": (previous or {}).get("transport_cycle_id"),
        "mode_changed": None if previous is None else current.get("mode") != previous.get("mode"),
        "ok_changed": None if previous is None else current.get("ok") != previous.get("ok"),
        "attempted_count_delta": current.get("attempted_count", 0) - ((previous or {}).get("attempted_count", 0)),
        "applied_count_delta": current.get("applied_count", 0) - ((previous or {}).get("applied_count", 0)),
        "blocked_count_delta": current.get("blocked_count", 0) - ((previous or {}).get("blocked_count", 0)),
        "invalid_count_delta": current.get("invalid_count", 0) - ((previous or {}).get("invalid_count", 0)),
        "stop_reason_before": (previous or {}).get("stop_reason"),
        "stop_reason_after": current.get("stop_reason"),
        "message_ids_added": sorted(current_ids - previous_ids),
        "message_ids_removed": sorted(previous_ids - current_ids),
        "pack_id_before": (previous or {}).get("outbound_prompt_pack_id"),
        "pack_id_after": current.get("outbound_prompt_pack_id"),
        "reply_ack_result_before": (previous or {}).get("reply_ack_result_kind"),
        "reply_ack_result_after": current.get("reply_ack_result_kind"),
    }


def compare_reply_transport_cycles(
    root: Path,
    *,
    current_cycle_id: str | None = None,
    other_cycle_id: str | None = None,
) -> dict[str, Any]:
    rows = list_reply_transport_cycles(root)
    if not rows:
        return {"ok": False, "error": "No reply transport cycles found."}
    current = load_reply_transport_cycle(root, current_cycle_id) if current_cycle_id else rows[0]
    if current is None:
        return {"ok": False, "error": f"Reply transport cycle not found: {current_cycle_id}"}
    if other_cycle_id:
        other = load_reply_transport_cycle(root, other_cycle_id)
        if other is None:
            return {"ok": False, "error": f"Reply transport cycle not found: {other_cycle_id}"}
    else:
        other = rows[1] if len(rows) > 1 and rows[0].get("transport_cycle_id") == current.get("transport_cycle_id") else (rows[0] if len(rows) > 1 else None)
        if other is not None and other.get("transport_cycle_id") == current.get("transport_cycle_id"):
            other = rows[1] if len(rows) > 1 else None
    payload = compare_reply_transport_cycle_records(current, other)
    latest_path = triage_logs_dir(root) / "operator_compare_reply_transport_cycles_latest.json"
    latest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def classify_reply_transport_replay_safety(
    root: Path,
    *,
    cycle: dict[str, Any],
    live_apply_requested: bool,
) -> dict[str, Any]:
    readiness = reply_transport_readiness(root, allow_inbox_rebuild=False, limit=5)
    messages = _load_reply_messages_for_cycle(root, cycle)
    if not messages:
        return {
            "replay_allowed": False,
            "replay_mode": "blocked",
            "reason": "No stored inbound reply intent was found for this cycle.",
            "would": "blocked",
            "reply_transport_ready": readiness["ready"],
        }
    for row in messages:
        classification = classify_compact_reply_text(str(row.get("raw_text", "")))
        if classification["classification"] in {"ignored_non_reply", "invalid_reply"}:
            return {
                "replay_allowed": False,
                "replay_mode": "blocked",
                "reason": f"Stored inbound reply `{row.get('source_message_id')}` is not replay-safe.",
                "would": "blocked",
                "reply_transport_ready": readiness["ready"],
            }
        if row.get("result_kind") == "duplicate_message":
            return {
                "replay_allowed": False,
                "replay_mode": "blocked",
                "reason": "Original cycle already resolved as a duplicate message and should not be replayed as execution intent.",
                "would": "blocked",
                "reply_transport_ready": readiness["ready"],
            }
    if not readiness["ready"]:
        return {
            "replay_allowed": False,
            "replay_mode": "blocked",
            "reason": readiness["reason"],
            "would": "blocked",
            "reply_transport_ready": readiness["ready"],
        }
    mode = str(cycle.get("mode") or "plan")
    if mode == "apply":
        return {
            "replay_allowed": True,
            "replay_mode": "apply_live" if live_apply_requested else "apply_dry_run",
            "reason": "Replay is allowed through the existing transport cycle.",
            "would": "apply_live" if live_apply_requested else "apply_dry_run",
            "reply_transport_ready": readiness["ready"],
        }
    if mode == "preview":
        return {
            "replay_allowed": True,
            "replay_mode": "preview_only",
            "reason": "Original cycle was preview-only, so replay stays preview-only.",
            "would": "preview_only",
            "reply_transport_ready": readiness["ready"],
        }
    return {
        "replay_allowed": True,
        "replay_mode": "plan_only",
        "reason": "Original cycle was plan-only, so replay remains plan-only.",
        "would": "plan_only",
        "reply_transport_ready": readiness["ready"],
    }


def build_reply_transport_replay_plan(
    root: Path,
    *,
    cycle_id: str,
    live_apply_requested: bool = False,
) -> dict[str, Any]:
    from runtime.core.models import new_id

    cycle = load_reply_transport_cycle(root, cycle_id)
    if cycle is None:
        payload = {"ok": False, "error": f"Reply transport cycle not found: {cycle_id}"}
        return payload
    messages = _load_reply_messages_for_cycle(root, cycle)
    safety = classify_reply_transport_replay_safety(root, cycle=cycle, live_apply_requested=live_apply_requested)
    replay_plan = {
        "replay_plan_id": new_id("opreplyreplayplan"),
        "created_at": now_iso(),
        "source_transport_cycle_id": cycle.get("transport_cycle_id"),
        "source_outbound_prompt_path": cycle.get("outbound_prompt_path"),
        "source_reply_ingress_run_id": cycle.get("reply_ingress_run_id"),
        "source_reply_ack_path": cycle.get("reply_ack_path"),
        "source_handoff_path": cycle.get("handoff_path"),
        "replay_safety": safety,
        "ok": bool(safety.get("replay_allowed")),
        "steps": [],
    }
    for index, row in enumerate(messages, start=1):
        source_message_id = str(row.get("source_message_id") or f"cycle_msg_{index}")
        replay_message_id = f"{source_message_id}__replay_{replay_plan['replay_plan_id']}_{index:02d}"
        mode = safety.get("replay_mode")
        replay_plan["steps"].append(
            {
                "index": index,
                "source_message_id": source_message_id,
                "replay_source_message_id": replay_message_id,
                "raw_text": row.get("raw_text", ""),
                "planned_operation_kind": mode,
                "apply": mode in {"apply_dry_run", "apply_live"},
                "preview": mode == "preview_only",
                "dry_run": mode != "apply_live",
                "continue_on_failure": bool(row.get("continue_on_failure", False)),
                "executable": bool(safety.get("replay_allowed")),
                "reason": safety.get("reason"),
            }
        )
    save_reply_transport_replay_plan_record(root, replay_plan)
    return replay_plan


def execute_reply_transport_replay(
    root: Path,
    *,
    cycle_id: str,
    plan_only: bool,
    live_apply: bool,
    continue_on_failure: bool,
) -> tuple[dict[str, Any], int]:
    from runtime.core.models import new_id
    from scripts.operator_enqueue_reply_message import enqueue_reply_message
    from scripts.operator_reply_transport_cycle import run_operator_reply_transport_cycle

    replay_plan = build_reply_transport_replay_plan(root, cycle_id=cycle_id, live_apply_requested=live_apply)
    replay = {
        "replay_id": new_id("opreplyreplay"),
        "started_at": now_iso(),
        "completed_at": None,
        "source_transport_cycle_id": cycle_id,
        "replay_plan_id": replay_plan.get("replay_plan_id"),
        "live_apply_requested": live_apply,
        "plan_only": plan_only,
        "ok": False,
        "replay_mode": (replay_plan.get("replay_safety") or {}).get("replay_mode"),
        "reason": "",
        "enqueued_message_paths": [],
        "transport_cycle_id": None,
    }
    if not replay_plan.get("ok", False) or plan_only:
        replay["ok"] = bool(replay_plan.get("ok", False))
        replay["reason"] = "Plan only." if plan_only and replay_plan.get("ok", False) else replay_plan.get("error") or (replay_plan.get("replay_safety") or {}).get("reason", "")
        replay["completed_at"] = now_iso()
        save_reply_transport_replay_record(root, replay)
        return {"ok": replay["ok"], "replay": replay, "replay_plan": replay_plan}, 0 if replay["ok"] else 1

    mode = (replay_plan.get("replay_safety") or {}).get("replay_mode")
    for step in replay_plan.get("steps", []):
        enqueued = enqueue_reply_message(
            root,
            raw_text=str(step.get("raw_text", "")),
            source_kind="replay",
            source_lane="reply_replay",
            source_channel="transport_replay",
            source_message_id=str(step.get("replay_source_message_id")),
            source_user="operator_replay",
            apply=bool(step.get("apply")),
            preview=bool(step.get("preview")),
            dry_run=bool(step.get("dry_run")),
            continue_on_failure=bool(step.get("continue_on_failure")) or continue_on_failure,
        )
        replay["enqueued_message_paths"].append(enqueued["path"])

    transport_payload, exit_code = run_operator_reply_transport_cycle(
        root,
        limit=len(replay_plan.get("steps", [])),
        apply=mode in {"apply_dry_run", "apply_live"},
        preview=mode == "preview_only",
        dry_run=mode != "apply_live",
        continue_on_failure=continue_on_failure,
        refresh_handoff=True,
    )
    replay["ok"] = bool(transport_payload.get("ok"))
    replay["transport_cycle_id"] = ((transport_payload.get("transport_cycle") or {}).get("transport_cycle_id"))
    replay["reason"] = (transport_payload.get("transport_cycle") or {}).get("stop_reason", "")
    replay["completed_at"] = now_iso()
    save_reply_transport_replay_record(root, replay)
    return {"ok": replay["ok"], "replay": replay, "replay_plan": replay_plan, "transport_cycle": transport_payload}, exit_code


def compact_bridge_cycle(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "bridge_cycle_id": row.get("bridge_cycle_id"),
        "ok": row.get("ok", False),
        "mode": row.get("mode"),
        "dry_run": row.get("dry_run", False),
        "bridge_ready": row.get("bridge_ready", False),
        "outbound_packet_id": row.get("outbound_packet_id"),
        "outbound_packet_pack_id": row.get("outbound_packet_pack_id"),
        "imported_count": row.get("imported_count", 0),
        "imported_source_message_ids": row.get("imported_source_message_ids", [])[:5],
        "reply_transport_cycle_id": row.get("reply_transport_cycle_id"),
        "reply_ack_result_kind": row.get("reply_ack_result_kind"),
        "stop_reason": row.get("stop_reason", ""),
        "completed_at": row.get("completed_at"),
    }


def list_bridge_cycles_view(
    root: Path,
    *,
    limit: int = 20,
    failed_only: bool = False,
    mode: str | None = None,
) -> dict[str, Any]:
    rows = list_bridge_cycles(root)
    if failed_only:
        rows = [row for row in rows if not row.get("ok", False)]
    if mode:
        rows = [row for row in rows if row.get("mode") == mode]
    rows = rows[:limit]
    return {
        "generated_at": now_iso(),
        "count": len(rows),
        "rows": [compact_bridge_cycle(row) for row in rows],
    }


def load_bridge_cycle(root: Path, cycle_id: str) -> dict[str, Any] | None:
    path = operator_bridge_cycles_dir(root) / f"{cycle_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    for row in list_bridge_cycles(root):
        if row.get("bridge_cycle_id") == cycle_id:
            return row
    return None


def _load_imported_rows_for_bridge_cycle(root: Path, cycle: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    imported_rows = cycle.get("imported_rows", [])
    if isinstance(imported_rows, list) and imported_rows:
        return [row for row in imported_rows if isinstance(row, dict)]
    import_ids = set(cycle.get("imported_reply_message_ids", []))
    source_ids = set(cycle.get("imported_source_message_ids", []))
    for row in list_imported_reply_messages(root):
        if row.get("import_id") in import_ids or row.get("source_message_id") in source_ids:
            rows.append(row)
    return rows


def _load_gateway_messages_for_bridge_cycle(cycle: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(cycle.get("imported_gateway_rows"), list):
        rows.extend(row for row in cycle.get("imported_gateway_rows", []) if isinstance(row, dict))
    for path_text in cycle.get("imported_gateway_message_paths", []):
        payload = _load_json_file(path_text)
        if payload is not None:
            payload["_gateway_message_path"] = str(path_text)
            rows.append(payload)
    return rows


def inspect_bridge_cycle(root: Path, *, cycle_id: str | None = None) -> dict[str, Any]:
    rows = list_bridge_cycles(root)
    cycle = load_bridge_cycle(root, cycle_id) if cycle_id else (rows[0] if rows else None)
    if cycle is None:
        return {"ok": False, "error": f"Bridge cycle not found: {cycle_id}" if cycle_id else "No bridge cycles found."}
    outbound_packet = _load_json_file(cycle.get("outbound_packet_path"))
    reply_ack = _load_json_file(cycle.get("reply_ack_path"))
    handoff = _load_json_file(cycle.get("handoff_path"))
    imported_rows = _load_imported_rows_for_bridge_cycle(root, cycle)
    gateway_rows = _load_gateway_messages_for_bridge_cycle(cycle)
    replay_safety = classify_bridge_replay_safety(root, cycle=cycle, live_apply_requested=False)
    return {
        "ok": True,
        "cycle": compact_bridge_cycle(cycle),
        "paths": {
            "outbound_packet_path": cycle.get("outbound_packet_path"),
            "reply_ack_path": cycle.get("reply_ack_path"),
            "handoff_path": cycle.get("handoff_path"),
            "reply_transport_cycle_id": cycle.get("reply_transport_cycle_id"),
        },
        "counts": {
            "imported_count": cycle.get("imported_count", 0),
            "gateway_message_count": len(gateway_rows),
            "reply_transport_attempted_count": cycle.get("reply_transport_attempted_count", 0),
            "reply_transport_blocked_count": cycle.get("reply_transport_blocked_count", 0),
        },
        "stop_reason": cycle.get("stop_reason", ""),
        "result_summary": {
            "reply_ack_result_kind": cycle.get("reply_ack_result_kind"),
            "latest_import_classification": (imported_rows[0] if imported_rows else {}).get("classification"),
            "outbound_packet_pack_id": cycle.get("outbound_packet_pack_id"),
        },
        "provenance": {
            "outbound_packet": {"path": cycle.get("outbound_packet_path"), "pack_id": (outbound_packet or {}).get("pack_id")},
            "reply_ack": {"path": cycle.get("reply_ack_path"), "latest_result_kind": ((reply_ack or {}).get("latest_reply_received") or {}).get("result_kind")},
            "handoff": {"path": cycle.get("handoff_path"), "generated_at": (handoff or {}).get("generated_at")},
            "gateway_message_paths": cycle.get("imported_gateway_message_paths", []),
        },
        "replay_safety": replay_safety,
        "imported_messages": [compact_imported_reply_message_summary(row) for row in imported_rows[:10]],
        "gateway_messages": [
            {
                "source_message_id": row.get("source_message_id"),
                "raw_text": row.get("raw_text"),
                "classification": row.get("classification"),
                "path": row.get("gateway_message_path") or row.get("_gateway_message_path"),
            }
            for row in gateway_rows[:10]
        ],
    }


def compare_bridge_cycle_records(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    current_ids = set(current.get("imported_source_message_ids", []))
    previous_ids = set((previous or {}).get("imported_source_message_ids", []))
    current_import_ids = set(current.get("imported_reply_message_ids", []))
    previous_import_ids = set((previous or {}).get("imported_reply_message_ids", []))
    return {
        "current_bridge_cycle_id": current.get("bridge_cycle_id"),
        "other_bridge_cycle_id": (previous or {}).get("bridge_cycle_id"),
        "mode_changed": None if previous is None else current.get("mode") != previous.get("mode"),
        "ok_changed": None if previous is None else current.get("ok") != previous.get("ok"),
        "imported_count_delta": current.get("imported_count", 0) - ((previous or {}).get("imported_count", 0)),
        "reply_transport_attempted_delta": current.get("reply_transport_attempted_count", 0) - ((previous or {}).get("reply_transport_attempted_count", 0)),
        "reply_transport_blocked_delta": current.get("reply_transport_blocked_count", 0) - ((previous or {}).get("reply_transport_blocked_count", 0)),
        "message_ids_added": sorted(current_ids - previous_ids),
        "message_ids_removed": sorted(previous_ids - current_ids),
        "import_ids_added": sorted(current_import_ids - previous_import_ids),
        "import_ids_removed": sorted(previous_import_ids - current_import_ids),
        "pack_id_before": (previous or {}).get("outbound_packet_pack_id"),
        "pack_id_after": current.get("outbound_packet_pack_id"),
        "reply_ack_result_before": (previous or {}).get("reply_ack_result_kind"),
        "reply_ack_result_after": current.get("reply_ack_result_kind"),
        "stop_reason_before": (previous or {}).get("stop_reason"),
        "stop_reason_after": current.get("stop_reason"),
    }


def compare_bridge_cycles(
    root: Path,
    *,
    current_cycle_id: str | None = None,
    other_cycle_id: str | None = None,
) -> dict[str, Any]:
    rows = list_bridge_cycles(root)
    if not rows:
        return {"ok": False, "error": "No bridge cycles found."}
    current = load_bridge_cycle(root, current_cycle_id) if current_cycle_id else rows[0]
    if current is None:
        return {"ok": False, "error": f"Bridge cycle not found: {current_cycle_id}"}
    if other_cycle_id:
        other = load_bridge_cycle(root, other_cycle_id)
        if other is None:
            return {"ok": False, "error": f"Bridge cycle not found: {other_cycle_id}"}
    else:
        other = rows[1] if len(rows) > 1 and rows[0].get("bridge_cycle_id") == current.get("bridge_cycle_id") else (rows[0] if len(rows) > 1 else None)
        if other is not None and other.get("bridge_cycle_id") == current.get("bridge_cycle_id"):
            other = rows[1] if len(rows) > 1 else None
    payload = compare_bridge_cycle_records(current, other)
    latest_path = triage_logs_dir(root) / "operator_compare_bridge_cycles_latest.json"
    latest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def classify_bridge_replay_safety(
    root: Path,
    *,
    cycle: dict[str, Any],
    live_apply_requested: bool,
) -> dict[str, Any]:
    readiness = gateway_operator_bridge_readiness(root, allow_inbox_rebuild=False, limit=5)
    imported_rows = _load_imported_rows_for_bridge_cycle(root, cycle)
    importable_rows = [row for row in imported_rows if row.get("classification") == "importable_compact_reply" and row.get("imported", False)]
    if not imported_rows or not importable_rows:
        return {
            "replay_allowed": False,
            "replay_mode": "blocked",
            "reason": "No importable gateway reply messages were captured for this bridge cycle.",
            "would": "blocked",
            "bridge_ready": readiness["bridge_ready"],
        }
    if not readiness["bridge_ready"]:
        return {
            "replay_allowed": False,
            "replay_mode": "blocked",
            "reason": readiness["reason"],
            "would": "blocked",
            "bridge_ready": readiness["bridge_ready"],
        }
    mode = str(cycle.get("mode") or "plan")
    if mode == "apply":
        replay_mode = "apply_live" if live_apply_requested else "apply_dry_run"
    elif mode == "preview":
        replay_mode = "preview_only"
    else:
        replay_mode = "plan_only"
    return {
        "replay_allowed": True,
        "replay_mode": replay_mode,
        "reason": "Replay is allowed through the existing bridge cycle wrappers.",
        "would": replay_mode,
        "bridge_ready": readiness["bridge_ready"],
        "importable_count": len(importable_rows),
    }


def build_bridge_replay_plan(
    root: Path,
    *,
    cycle_id: str,
    live_apply_requested: bool = False,
) -> dict[str, Any]:
    from runtime.core.models import new_id

    cycle = load_bridge_cycle(root, cycle_id)
    if cycle is None:
        return {"ok": False, "error": f"Bridge cycle not found: {cycle_id}"}
    imported_rows = _load_imported_rows_for_bridge_cycle(root, cycle)
    safety = classify_bridge_replay_safety(root, cycle=cycle, live_apply_requested=live_apply_requested)
    replay_plan = {
        "bridge_replay_plan_id": new_id("opbridgereplayplan"),
        "created_at": now_iso(),
        "source_bridge_cycle_id": cycle.get("bridge_cycle_id"),
        "source_outbound_packet_id": cycle.get("outbound_packet_id"),
        "source_outbound_packet_path": cycle.get("outbound_packet_path"),
        "source_reply_transport_cycle_id": cycle.get("reply_transport_cycle_id"),
        "source_reply_ack_path": cycle.get("reply_ack_path"),
        "source_handoff_path": cycle.get("handoff_path"),
        "replay_safety": safety,
        "ok": bool(safety.get("replay_allowed")),
        "steps": [],
    }
    mode = safety.get("replay_mode")
    for index, row in enumerate(imported_rows, start=1):
        if row.get("classification") != "importable_compact_reply" or not row.get("imported", False):
            continue
        source_message_id = str(row.get("source_message_id") or f"bridge_msg_{index}")
        replay_source_message_id = f"{source_message_id}__bridge_replay_{replay_plan['bridge_replay_plan_id']}_{index:02d}"
        replay_plan["steps"].append(
            {
                "index": index,
                "source_message_id": source_message_id,
                "replay_source_message_id": replay_source_message_id,
                "raw_text": row.get("raw_text", ""),
                "source_kind": row.get("source_kind", "gateway"),
                "source_lane": row.get("source_lane", "operator"),
                "source_channel": row.get("source_channel", "gateway"),
                "source_user": row.get("source_user", "operator"),
                "planned_operation_kind": mode,
                "apply": mode in {"apply_dry_run", "apply_live"},
                "preview": mode == "preview_only",
                "dry_run": mode != "apply_live",
                "continue_on_failure": bool(row.get("continue_on_failure", False)),
                "gateway_message_path": row.get("gateway_message_path"),
                "executable": bool(safety.get("replay_allowed")),
                "reason": safety.get("reason"),
            }
        )
    save_bridge_replay_plan_record(root, replay_plan)
    return replay_plan


def execute_bridge_replay(
    root: Path,
    *,
    cycle_id: str,
    plan_only: bool,
    live_apply: bool,
    continue_on_failure: bool,
) -> tuple[dict[str, Any], int]:
    from runtime.core.models import new_id
    from scripts.operator_bridge_cycle import run_operator_bridge_cycle

    replay_plan = build_bridge_replay_plan(root, cycle_id=cycle_id, live_apply_requested=live_apply)
    replay = {
        "bridge_replay_id": new_id("opbridgereplay"),
        "started_at": now_iso(),
        "completed_at": None,
        "source_bridge_cycle_id": cycle_id,
        "bridge_replay_plan_id": replay_plan.get("bridge_replay_plan_id"),
        "live_apply_requested": live_apply,
        "plan_only": plan_only,
        "ok": False,
        "replay_mode": (replay_plan.get("replay_safety") or {}).get("replay_mode"),
        "reason": "",
        "staged_gateway_message_paths": [],
        "bridge_cycle_id": None,
    }
    if not replay_plan.get("ok", False) or plan_only:
        replay["ok"] = bool(replay_plan.get("ok", False))
        replay["reason"] = "Plan only." if plan_only and replay_plan.get("ok", False) else replay_plan.get("error") or (replay_plan.get("replay_safety") or {}).get("reason", "")
        replay["completed_at"] = now_iso()
        save_bridge_replay_record(root, replay)
        return {"ok": replay["ok"], "bridge_replay": replay, "bridge_replay_plan": replay_plan}, 0 if replay["ok"] else 1

    mode = (replay_plan.get("replay_safety") or {}).get("replay_mode")
    staged_paths: list[Path] = []
    folder = operator_gateway_inbound_messages_dir(root)
    for step in replay_plan.get("steps", []):
        path = folder / f"{step['replay_source_message_id']}.json"
        payload = {
            "source_kind": "bridge_replay",
            "source_lane": "bridge_replay",
            "source_channel": "bridge_replay",
            "source_message_id": step.get("replay_source_message_id"),
            "source_user": step.get("source_user", "operator_replay"),
            "raw_text": step.get("raw_text", ""),
            "apply": bool(step.get("apply")),
            "preview": bool(step.get("preview")),
            "dry_run": bool(step.get("dry_run")),
            "continue_on_failure": bool(step.get("continue_on_failure")) or continue_on_failure,
            "replay_of_bridge_cycle_id": cycle_id,
            "original_source_message_id": step.get("source_message_id"),
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        staged_paths.append(path)
        replay["staged_gateway_message_paths"].append(str(path))

    bridge_payload, exit_code = run_operator_bridge_cycle(
        root,
        limit=len(staged_paths),
        import_from_folder=True,
        import_paths=staged_paths,
        apply=mode in {"apply_dry_run", "apply_live"},
        preview=mode == "preview_only",
        dry_run=mode != "apply_live",
        continue_on_failure=continue_on_failure,
        refresh_handoff=True,
    )
    replay["ok"] = bool(bridge_payload.get("ok"))
    replay["bridge_cycle_id"] = ((bridge_payload.get("bridge_cycle") or {}).get("bridge_cycle_id"))
    replay["reason"] = (bridge_payload.get("bridge_cycle") or {}).get("stop_reason", "")
    replay["completed_at"] = now_iso()
    save_bridge_replay_record(root, replay)
    return {"ok": replay["ok"], "bridge_replay": replay, "bridge_replay_plan": replay_plan, "bridge_cycle": bridge_payload}, exit_code


DOCTOR_SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3}


def _operator_command(root: Path, script_name: str, *args: str) -> str:
    parts = [
        "python3",
        str((root / "scripts" / script_name).resolve()),
        "--root",
        str(root.resolve()),
    ]
    parts.extend(arg for arg in args if arg)
    return " ".join(parts)


def count_pending_gateway_import_messages(root: Path) -> int:
    count = 0
    for row in load_jsons(operator_gateway_inbound_messages_dir(root)):
        if not row.get("imported_at"):
            count += 1
    return count


def _pending_gateway_import_paths(root: Path, *, limit: int = 5) -> list[str]:
    paths: list[str] = []
    for path in sorted(operator_gateway_inbound_messages_dir(root).glob("*.json")):
        payload = _load_json_file(path)
        if payload is None or payload.get("imported_at"):
            continue
        paths.append(str(path))
        if len(paths) >= limit:
            break
    return paths


def _doctor_issue(
    *,
    code: str,
    severity: str,
    reason: str,
    command: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "issue_code": code,
        "severity": severity,
        "reason": reason,
        "suggested_command": command,
        "details": details or {},
    }


def classify_operator_doctor_state(root: Path, *, limit: int = 5) -> dict[str, Any]:
    from scripts.operator_checkpoint_action_pack import classify_action_pack

    current_pack = load_current_action_pack_summary(root)
    inbox, inbox_path, inbox_error = load_current_decision_inbox(root)
    inbox_status, _, inbox_reason = classify_decision_inbox_freshness(root, inbox)
    reply_ingress = {
        "reply_ingest_ready": bool(inbox and inbox.get("reply_ready")) and current_pack.get("status") == "valid",
        "pending_inbound_reply_count": count_pending_reply_messages(root),
        "duplicate_count": sum(1 for row in list_reply_ingress_records(root) if row.get("result_kind") == "duplicate_message"),
        "blocked_count": sum(
            1
            for row in list_reply_ingress_records(root)
            if row.get("result_kind") in {"missing_inbox", "stale_inbox", "pack_refresh_required", "blocked", "duplicate_message"}
        ),
    }
    reply_transport = reply_transport_readiness(root, allow_inbox_rebuild=False, limit=limit)
    gateway_bridge = gateway_operator_bridge_readiness(root, allow_inbox_rebuild=False, limit=limit)
    pending_gateway_count = count_pending_gateway_import_messages(root)
    latest_transport_cycle = list_reply_transport_cycles(root)[0] if list_reply_transport_cycles(root) else None
    latest_bridge_cycle = list_bridge_cycles(root)[0] if list_bridge_cycles(root) else None
    latest_transport_replay_safety = (
        classify_reply_transport_replay_safety(root, cycle=latest_transport_cycle, live_apply_requested=False)
        if latest_transport_cycle
        else {"replay_allowed": None, "reason": "No reply transport cycle recorded yet."}
    )
    latest_bridge_replay_safety = (
        classify_bridge_replay_safety(root, cycle=latest_bridge_cycle, live_apply_requested=False)
        if latest_bridge_cycle
        else {"replay_allowed": None, "reason": "No bridge cycle recorded yet."}
    )

    issues: list[dict[str, Any]] = []
    pack_status = current_pack.get("status")
    if pack_status == "missing":
        issues.append(
            _doctor_issue(
                code="pack_missing",
                severity="high",
                reason=current_pack.get("reason") or "Current action pack is missing.",
                command=_operator_command(root, "operator_checkpoint_action_pack.py"),
            )
        )
    elif pack_status in {"malformed", "fingerprint_invalid"}:
        issues.append(
            _doctor_issue(
                code="pack_invalid",
                severity="high",
                reason=current_pack.get("reason") or f"Current action pack status is `{pack_status}`.",
                command=_operator_command(root, "operator_checkpoint_action_pack.py"),
                details={"pack_status": pack_status},
            )
        )
    elif pack_status == "expired":
        issues.append(
            _doctor_issue(
                code="pack_expired",
                severity="high",
                reason=current_pack.get("reason") or "Current action pack has expired.",
                command=_operator_command(root, "operator_checkpoint_action_pack.py"),
                details={"expires_at": current_pack.get("expires_at")},
            )
        )

    if inbox_error == "missing_inbox":
        issues.append(
            _doctor_issue(
                code="inbox_missing",
                severity="medium",
                reason="Decision inbox is missing.",
                command=_operator_command(root, "operator_decision_inbox.py"),
                details={"decision_inbox_path": str(inbox_path)},
            )
        )
    elif inbox_status == "stale_inbox":
        issues.append(
            _doctor_issue(
                code="inbox_stale",
                severity="medium",
                reason=inbox_reason,
                command=_operator_command(root, "operator_decision_inbox.py"),
                details={"decision_inbox_path": str(inbox_path)},
            )
        )
    elif inbox is not None and not inbox.get("reply_ready"):
        issues.append(
            _doctor_issue(
                code="inbox_not_reply_ready",
                severity="medium",
                reason="Decision inbox exists but is not reply-ready.",
                command=_operator_command(root, "operator_decision_inbox.py"),
                details={"decision_inbox_path": str(inbox_path)},
            )
        )

    if reply_ingress["pending_inbound_reply_count"] > 0:
        issues.append(
            _doctor_issue(
                code="pending_inbound_replies",
                severity="medium",
                reason=f"{reply_ingress['pending_inbound_reply_count']} inbound reply message(s) are waiting in the file-backed queue.",
                command=_operator_command(root, "operator_reply_transport_cycle.py", "--apply", "--dry-run", "--continue-on-failure"),
                details={"pending_inbound_reply_count": reply_ingress["pending_inbound_reply_count"]},
            )
        )

    if pending_gateway_count > 0:
        issues.append(
            _doctor_issue(
                code="pending_gateway_imports",
                severity="medium",
                reason=f"{pending_gateway_count} gateway-style reply message(s) are waiting to be imported.",
                command=_operator_command(root, "operator_bridge_cycle.py", "--import-from-folder", "--apply", "--dry-run", "--continue-on-failure"),
                details={"pending_gateway_import_count": pending_gateway_count, "paths": _pending_gateway_import_paths(root, limit=limit)},
            )
        )

    if latest_transport_cycle and not latest_transport_cycle.get("ok", False):
        issues.append(
            _doctor_issue(
                code="latest_transport_failed",
                severity="high",
                reason=latest_transport_cycle.get("stop_reason") or "Latest reply transport cycle did not complete cleanly.",
                command=_operator_command(
                    root,
                    "operator_explain_reply_transport_cycle.py",
                    "--cycle-id",
                    str(latest_transport_cycle.get("transport_cycle_id") or ""),
                ),
                details={"transport_cycle_id": latest_transport_cycle.get("transport_cycle_id")},
            )
        )

    if latest_bridge_cycle and not latest_bridge_cycle.get("ok", False):
        issues.append(
            _doctor_issue(
                code="latest_bridge_failed",
                severity="high",
                reason=latest_bridge_cycle.get("stop_reason") or "Latest bridge cycle did not complete cleanly.",
                command=_operator_command(
                    root,
                    "operator_explain_bridge_cycle.py",
                    "--cycle-id",
                    str(latest_bridge_cycle.get("bridge_cycle_id") or ""),
                ),
                details={"bridge_cycle_id": latest_bridge_cycle.get("bridge_cycle_id")},
            )
        )

    if latest_transport_replay_safety.get("replay_allowed") is False:
        issues.append(
            _doctor_issue(
                code="replay_blocked",
                severity="medium",
                reason=latest_transport_replay_safety.get("reason") or "Latest reply transport replay is blocked.",
                command=_operator_command(
                    root,
                    "operator_replay_transport_cycle.py",
                    "--cycle-id",
                    str((latest_transport_cycle or {}).get("transport_cycle_id") or ""),
                    "--plan-only",
                )
                if latest_transport_cycle
                else None,
                details={"transport_cycle_id": (latest_transport_cycle or {}).get("transport_cycle_id")},
            )
        )

    if latest_bridge_replay_safety.get("replay_allowed") is False:
        issues.append(
            _doctor_issue(
                code="bridge_replay_blocked",
                severity="medium",
                reason=latest_bridge_replay_safety.get("reason") or "Latest bridge replay is blocked.",
                command=_operator_command(
                    root,
                    "operator_replay_bridge_cycle.py",
                    "--cycle-id",
                    str((latest_bridge_cycle or {}).get("bridge_cycle_id") or ""),
                    "--plan-only",
                )
                if latest_bridge_cycle
                else None,
                details={"bridge_cycle_id": (latest_bridge_cycle or {}).get("bridge_cycle_id")},
            )
        )

    if not issues:
        issues.append(
            _doctor_issue(
                code="healthy",
                severity="low",
                reason="Operator reply/control-plane paths are healthy.",
                command=_operator_command(root, "operator_handoff_pack.py"),
            )
        )

    issues = sorted(issues, key=lambda row: (-DOCTOR_SEVERITY_ORDER.get(str(row.get("severity")), 0), str(row.get("issue_code"))))
    highest = issues[0]["severity"] if issues else "low"
    health_status = "healthy"
    if highest == "high":
        health_status = "blocked"
    elif highest == "medium":
        health_status = "degraded"
    next_commands = [row["suggested_command"] for row in issues if row.get("suggested_command")][:5]
    return {
        "generated_at": now_iso(),
        "health_status": health_status,
        "highest_severity": highest,
        "active_issue_count": len([row for row in issues if row.get("issue_code") != "healthy"]),
        "issues": issues,
        "readiness": {
            "current_action_pack": current_pack,
            "decision_inbox": {
                "path": str(inbox_path),
                "status": inbox_status,
                "reply_ready": False if inbox is None else bool(inbox.get("reply_ready")),
                "generated_at": None if inbox is None else inbox.get("generated_at"),
                "reason": inbox_reason,
            },
            "reply_ingress": reply_ingress,
            "reply_transport": reply_transport,
            "latest_reply_transport_replay_safety": latest_transport_replay_safety,
            "gateway_bridge": {
                **gateway_bridge,
                "pending_gateway_import_count": pending_gateway_count,
            },
            "latest_bridge_replay_safety": latest_bridge_replay_safety,
        },
        "next_recommended_commands": next_commands,
        "latest_refs": {
            "latest_reply_transport_cycle_id": None if latest_transport_cycle is None else latest_transport_cycle.get("transport_cycle_id"),
            "latest_bridge_cycle_id": None if latest_bridge_cycle is None else latest_bridge_cycle.get("bridge_cycle_id"),
        },
    }


def build_operator_doctor_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Operator Doctor",
        "",
        f"Generated at: {report.get('generated_at')}",
        f"Health: {report.get('health_status')} highest_severity={report.get('highest_severity')} active_issues={report.get('active_issue_count')}",
        "",
        "## Issues",
    ]
    for row in report.get("issues", []):
        lines.append(f"- {row.get('issue_code')} severity={row.get('severity')} reason={row.get('reason')}")
        if row.get("suggested_command"):
            lines.append(f"  next: {row.get('suggested_command')}")
    lines.extend(["", "## Next Commands"])
    for row in report.get("next_recommended_commands", []):
        lines.append(f"- {row}")
    return "\n".join(lines).strip() + "\n"


def create_operator_doctor_report(root: Path, *, limit: int = 5) -> dict[str, Any]:
    from runtime.core.models import new_id

    report = {
        "doctor_report_id": new_id("opdoctor"),
        "started_at": now_iso(),
        **classify_operator_doctor_state(root, limit=limit),
        "completed_at": now_iso(),
    }
    save_doctor_report_record(root, report)
    markdown_path = triage_logs_dir(root) / "operator_doctor_latest.md"
    markdown_path.write_text(build_operator_doctor_markdown(report), encoding="utf-8")
    return report


def list_doctor_reports_view(root: Path, *, limit: int = 20) -> dict[str, Any]:
    rows = list_doctor_reports(root)[:limit]
    return {
        "generated_at": now_iso(),
        "count": len(rows),
        "rows": [
            {
                "doctor_report_id": row.get("doctor_report_id"),
                "health_status": row.get("health_status"),
                "highest_severity": row.get("highest_severity"),
                "active_issue_count": row.get("active_issue_count", 0),
                "top_issue_code": ((row.get("issues") or [{}])[0]).get("issue_code"),
                "completed_at": row.get("completed_at"),
            }
            for row in rows
        ],
    }


def build_operator_remediation_plan(root: Path, *, limit: int = 5) -> dict[str, Any]:
    from runtime.core.models import new_id

    doctor = classify_operator_doctor_state(root, limit=limit)
    steps = []
    for index, issue in enumerate(doctor.get("issues", [])[:limit], start=1):
        if not issue.get("suggested_command"):
            continue
        steps.append(
            {
                "index": index,
                "issue_code": issue.get("issue_code"),
                "severity": issue.get("severity"),
                "reason": issue.get("reason"),
                "suggested_command": issue.get("suggested_command"),
            }
        )
    plan = {
        "remediation_plan_id": new_id("opremed"),
        "created_at": now_iso(),
        "health_status": doctor.get("health_status"),
        "highest_severity": doctor.get("highest_severity"),
        "active_issue_count": doctor.get("active_issue_count"),
        "source_doctor_snapshot": {
            "generated_at": doctor.get("generated_at"),
            "latest_reply_transport_cycle_id": (doctor.get("latest_refs") or {}).get("latest_reply_transport_cycle_id"),
            "latest_bridge_cycle_id": (doctor.get("latest_refs") or {}).get("latest_bridge_cycle_id"),
        },
        "steps": steps,
        "next_recommended_commands": doctor.get("next_recommended_commands", [])[:limit],
        "completed_at": now_iso(),
    }
    save_remediation_plan_record(root, plan)
    return plan


def explain_operator_doctor_issue(root: Path, *, issue_code: str, limit: int = 5) -> dict[str, Any]:
    doctor = classify_operator_doctor_state(root, limit=limit)
    for issue in doctor.get("issues", []):
        if issue.get("issue_code") == issue_code:
            return {
                "ok": True,
                "issue": issue,
                "health_status": doctor.get("health_status"),
                "highest_severity": doctor.get("highest_severity"),
                "readiness": doctor.get("readiness", {}),
                "next_recommended_commands": doctor.get("next_recommended_commands", [])[:limit],
            }
    return {
        "ok": False,
        "error": f"Doctor issue not found: {issue_code}",
        "health_status": doctor.get("health_status"),
        "available_issue_codes": [row.get("issue_code") for row in doctor.get("issues", [])],
    }


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
