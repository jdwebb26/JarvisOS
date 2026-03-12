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

from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.dashboard.task_board import build_task_board
from runtime.gateway.review_inbox import build_review_inbox
from runtime.evals.replay_runner import build_eval_run_summary
from scripts.operator_action_ledger import (
    latest_failed_action_for_task,
    latest_successful_action_for_task,
)


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
    def sort_key(row: dict[str, Any]) -> tuple[str, ...]:
        return tuple(str(row.get(key, "")) for key in keys)

    return sorted(rows, key=sort_key, reverse=True)


def _artifact_summary(rows: list[dict[str, Any]], *, lifecycle_state: str, limit: int) -> list[dict[str, Any]]:
    filtered = [row for row in rows if row.get("lifecycle_state") == lifecycle_state]
    filtered = _sort_recent(filtered, "updated_at", "created_at")
    return [
        {
            "artifact_id": row.get("artifact_id"),
            "task_id": row.get("task_id"),
            "title": row.get("title"),
            "artifact_type": row.get("artifact_type"),
            "execution_backend": row.get("execution_backend"),
            "updated_at": row.get("updated_at"),
        }
        for row in filtered[:limit]
    ]


def _trace_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "trace_id": row.get("trace_id"),
            "task_id": row.get("task_id"),
            "trace_kind": row.get("trace_kind"),
            "status": row.get("status"),
            "execution_backend": row.get("execution_backend"),
            "candidate_artifact_id": row.get("candidate_artifact_id"),
            "response_summary": row.get("response_summary"),
            "updated_at": row.get("updated_at"),
        }
        for row in _sort_recent(rows, "updated_at", "created_at")[:limit]
    ]


def _eval_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "eval_result_id": row.get("eval_result_id"),
            "task_id": row.get("task_id"),
            "trace_id": row.get("trace_id"),
            "score": row.get("score"),
            "passed": row.get("passed"),
            "summary": row.get("summary"),
            "report_artifact_id": row.get("report_artifact_id"),
            "updated_at": row.get("updated_at"),
        }
        for row in _sort_recent(rows, "updated_at", "created_at")[:limit]
    ]


def _operator_action_execution_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "execution_id": row.get("execution_id"),
            "action_id": row.get("action_id"),
            "category": (row.get("selected_action") or {}).get("category"),
            "verb": (row.get("selected_action") or {}).get("verb"),
            "target_id": (row.get("selected_action") or {}).get("target_id"),
            "task_id": (row.get("selected_action") or {}).get("task_id"),
            "dry_run": row.get("dry_run", False),
            "success": row.get("success", False),
            "return_code": row.get("return_code"),
            "ack_summary": row.get("ack_summary", ""),
            "failure_kind": row.get("failure_kind", ""),
            "source_action_pack_id": row.get("source_action_pack_id"),
            "source_action_pack_validation_status": row.get("source_action_pack_validation_status"),
            "source_action_pack_resolution": row.get("source_action_pack_resolution"),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _operator_queue_run_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "queue_run_id": row.get("queue_run_id"),
            "source_action_pack_id": row.get("source_action_pack_id"),
            "source_action_pack_fingerprint": row.get("source_action_pack_fingerprint"),
            "source_action_pack_validation_status": row.get("source_action_pack_validation_status"),
            "source_action_pack_resolution": row.get("source_action_pack_resolution"),
            "source_action_pack_rebuild_reason": row.get("source_action_pack_rebuild_reason", ""),
            "ok": row.get("ok", False),
            "attempted_count": row.get("attempted_count", 0),
            "succeeded_count": row.get("succeeded_count", 0),
            "failed_count": row.get("failed_count", 0),
            "skipped_count": row.get("skipped_count", 0),
            "policy_skipped_count": sum(1 for item in row.get("skipped_actions", []) if item.get("skip_kind") == "policy"),
            "idempotency_skipped_count": sum(
                1 for item in row.get("skipped_actions", []) if item.get("skip_kind") == "idempotency"
            ),
            "stale_skipped_count": sum(1 for item in row.get("skipped_actions", []) if item.get("skip_kind") == "stale_action"),
            "stopped_on_action_id": row.get("stopped_on_action_id"),
            "filters": row.get("filters", {}),
            "policy_summary": row.get("policy_summary", {}),
            "recent_skip_reasons": [item.get("skip_reason", "") for item in row.get("skipped_actions", [])[:3]],
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _operator_bulk_run_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "bulk_run_id": row.get("bulk_run_id"),
            "source_action_pack_id": row.get("source_action_pack_id"),
            "source_action_pack_validation_status": row.get("pack_validation_status"),
            "source_action_pack_resolution": row.get("pack_resolution"),
            "source_action_pack_rebuild_reason": row.get("pack_rebuild_reason", ""),
            "ok": row.get("ok", False),
            "attempted_count": row.get("attempted_count", 0),
            "succeeded_count": row.get("succeeded_count", 0),
            "failed_count": row.get("failed_count", 0),
            "skipped_count": row.get("skipped_count", 0),
            "policy_skipped_count": sum(1 for item in row.get("skipped_actions", []) if item.get("skip_kind") == "policy"),
            "idempotency_skipped_count": sum(1 for item in row.get("skipped_actions", []) if item.get("skip_kind") == "idempotency"),
            "stale_skipped_count": sum(1 for item in row.get("skipped_actions", []) if item.get("skip_kind") == "stale_action"),
            "stop_reason": row.get("stop_reason", ""),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _task_intervention_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "intervention_id": row.get("intervention_id"),
            "task_id": row.get("task_id"),
            "dry_run": row.get("dry_run", False),
            "selected_action_id": row.get("selected_action_id"),
            "source_action_pack_id": row.get("source_action_pack_id"),
            "source_action_pack_validation_status": row.get("source_action_pack_validation_status"),
            "ok": row.get("ok", False),
            "execution_record_id": row.get("execution_record_id"),
            "blocker_summary": row.get("blocker_summary", []),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _safe_autofix_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "autofix_run_id": row.get("autofix_run_id"),
            "ok": row.get("ok", False),
            "rebuild_happened": row.get("rebuild_happened", False),
            "safe_action_selected": row.get("safe_action_selected"),
            "safe_action_executed": row.get("safe_action_executed", False),
            "safe_action_dry_run": row.get("safe_action_dry_run", False),
            "execution_record_id": row.get("execution_record_id"),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _reply_plan_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "plan_id": row.get("plan_id"),
            "reply_string": row.get("reply_string"),
            "ok": row.get("ok", False),
            "unknown_tokens": row.get("unknown_tokens", []),
            "step_count": len(row.get("steps", [])),
            "created_at": row.get("created_at"),
        }
        for row in _sort_recent(rows, "created_at", "started_at")[:limit]
    ]


def _reply_apply_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "reply_apply_id": row.get("reply_apply_id"),
            "reply_string": row.get("reply_string"),
            "ok": row.get("ok", False),
            "attempted_count": row.get("attempted_count", 0),
            "succeeded_count": row.get("succeeded_count", 0),
            "failed_count": row.get("failed_count", 0),
            "skipped_count": row.get("skipped_count", 0),
            "stop_reason": row.get("stop_reason", ""),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _reply_ingress_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "ingress_id": row.get("ingress_id"),
            "source_kind": row.get("source_kind"),
            "source_channel": row.get("source_channel"),
            "source_message_id": row.get("source_message_id"),
            "source_user": row.get("source_user"),
            "normalized_text": row.get("normalized_text"),
            "result_kind": row.get("result_kind"),
            "applied": row.get("applied", False),
            "ignored": row.get("ignored", False),
            "dry_run": row.get("dry_run", False),
            "source_action_pack_status": row.get("source_action_pack_status"),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "created_at")[:limit]
    ]


def _reply_ingress_run_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "run_id": row.get("run_id"),
            "ok": row.get("ok", False),
            "attempted_count": row.get("attempted_count", 0),
            "succeeded_count": row.get("succeeded_count", 0),
            "ignored_count": row.get("ignored_count", 0),
            "invalid_count": row.get("invalid_count", 0),
            "blocked_count": row.get("blocked_count", 0),
            "applied_count": row.get("applied_count", 0),
            "stop_reason": row.get("stop_reason", ""),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _reply_transport_cycle_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "transport_cycle_id": row.get("transport_cycle_id"),
            "ok": row.get("ok", False),
            "mode": row.get("mode"),
            "dry_run": row.get("dry_run", False),
            "attempted_count": row.get("attempted_count", 0),
            "applied_count": row.get("applied_count", 0),
            "blocked_count": row.get("blocked_count", 0),
            "ignored_count": row.get("ignored_count", 0),
            "invalid_count": row.get("invalid_count", 0),
            "stop_reason": row.get("stop_reason", ""),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _reply_transport_replay_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "replay_id": row.get("replay_id"),
            "source_transport_cycle_id": row.get("source_transport_cycle_id"),
            "replay_plan_id": row.get("replay_plan_id"),
            "replay_mode": row.get("replay_mode"),
            "plan_only": row.get("plan_only", False),
            "live_apply_requested": row.get("live_apply_requested", False),
            "ok": row.get("ok", False),
            "reason": row.get("reason", ""),
            "transport_cycle_id": row.get("transport_cycle_id"),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _outbound_packet_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "outbound_packet_id": row.get("outbound_packet_id"),
            "pack_id": row.get("pack_id"),
            "pack_status": row.get("pack_status"),
            "reply_ready": row.get("reply_ready"),
            "top_item_count": len(row.get("top_items", [])),
            "warning": row.get("minimal_warning", ""),
            "generated_at": row.get("generated_at"),
        }
        for row in _sort_recent(rows, "generated_at", "created_at")[:limit]
    ]


def _imported_reply_message_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "import_id": row.get("import_id"),
            "source_message_id": row.get("source_message_id"),
            "classification": row.get("classification"),
            "imported": row.get("imported", False),
            "reply_message_path": row.get("reply_message_path"),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "created_at")[:limit]
    ]


def _bridge_cycle_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "bridge_cycle_id": row.get("bridge_cycle_id"),
            "ok": row.get("ok", False),
            "mode": row.get("mode"),
            "dry_run": row.get("dry_run", False),
            "bridge_ready": row.get("bridge_ready", False),
            "outbound_packet_id": row.get("outbound_packet_id"),
            "imported_count": row.get("imported_count", 0),
            "reply_transport_cycle_id": row.get("reply_transport_cycle_id"),
            "reply_ack_result_kind": row.get("reply_ack_result_kind"),
            "stop_reason": row.get("stop_reason", ""),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _bridge_replay_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "bridge_replay_id": row.get("bridge_replay_id"),
            "source_bridge_cycle_id": row.get("source_bridge_cycle_id"),
            "bridge_replay_plan_id": row.get("bridge_replay_plan_id"),
            "replay_mode": row.get("replay_mode"),
            "plan_only": row.get("plan_only", False),
            "live_apply_requested": row.get("live_apply_requested", False),
            "ok": row.get("ok", False),
            "reason": row.get("reason", ""),
            "bridge_cycle_id": row.get("bridge_cycle_id"),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _doctor_report_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "doctor_report_id": row.get("doctor_report_id"),
            "health_status": row.get("health_status"),
            "highest_severity": row.get("highest_severity"),
            "active_issue_count": row.get("active_issue_count", 0),
            "top_issue_code": ((row.get("issues") or [{}])[0]).get("issue_code"),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _remediation_plan_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "remediation_plan_id": row.get("remediation_plan_id"),
            "health_status": row.get("health_status"),
            "highest_severity": row.get("highest_severity"),
            "active_issue_count": row.get("active_issue_count", 0),
            "step_count": len(row.get("steps", [])),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "created_at")[:limit]
    ]


def _remediation_run_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "remediation_run_id": row.get("remediation_run_id"),
            "remediation_plan_id": row.get("remediation_plan_id"),
            "dry_run": row.get("dry_run", False),
            "ok": row.get("ok", False),
            "attempted_step_count": row.get("attempted_step_count", 0),
            "failed_step_count": row.get("failed_step_count", 0),
            "stop_reason": row.get("stop_reason", ""),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _recovery_cycle_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "recovery_cycle_id": row.get("recovery_cycle_id"),
            "doctor_report_id": row.get("doctor_report_id"),
            "remediation_plan_id": row.get("remediation_plan_id"),
            "remediation_run_id": row.get("remediation_run_id"),
            "dry_run": row.get("dry_run", False),
            "ok": row.get("ok", False),
            "health_status_before": row.get("health_status_before"),
            "health_status_after": row.get("health_status_after"),
            "active_issue_count_before": row.get("active_issue_count_before", 0),
            "active_issue_count_after": row.get("active_issue_count_after", 0),
            "stop_reason": row.get("stop_reason", ""),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _control_plane_checkpoint_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "control_plane_checkpoint_id": row.get("control_plane_checkpoint_id"),
            "pack_id": ((row.get("current_action_pack") or {}).get("pack_id")),
            "pack_status": ((row.get("current_action_pack") or {}).get("status")),
            "decision_inbox_reply_ready": ((row.get("decision_inbox_summary") or {}).get("reply_ready")),
            "doctor_health_status": ((row.get("doctor_summary") or {}).get("health_status")),
            "active_issue_count": ((row.get("doctor_summary") or {}).get("active_issue_count", 0)),
            "latest_recovery_cycle_id": ((row.get("latest_recovery_cycle_summary") or {}).get("recovery_cycle_id")),
            "created_at": row.get("created_at"),
        }
        for row in _sort_recent(rows, "created_at")[:limit]
    ]


def _incident_report_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "incident_report_id": row.get("incident_report_id"),
            "incident_snapshot_id": row.get("incident_snapshot_id"),
            "incident_code": row.get("incident_code"),
            "severity": row.get("severity"),
            "health_status": row.get("health_status"),
            "worsened": row.get("worsened", False),
            "created_at": row.get("created_at"),
        }
        for row in _sort_recent(rows, "created_at", "completed_at")[:limit]
    ]


def _ralph_memory_summary(
    consolidation_runs: list[dict[str, Any]],
    memory_candidates: list[dict[str, Any]],
    *,
    limit: int,
) -> dict[str, Any]:
    latest_runs = _sort_recent(consolidation_runs, "updated_at", "created_at")[:limit]
    latest_candidates = _sort_recent(memory_candidates, "updated_at", "created_at")[:limit]
    return {
        "latest_consolidation_runs": [
            {
                "consolidation_run_id": row.get("consolidation_run_id"),
                "task_id": row.get("task_id"),
                "status": row.get("status"),
                "digest_artifact_id": row.get("digest_artifact_id"),
                "memory_candidate_ids": row.get("memory_candidate_ids", []),
                "summary": row.get("summary"),
                "updated_at": row.get("updated_at"),
            }
            for row in latest_runs
        ],
        "latest_memory_candidates": [
            {
                "memory_candidate_id": row.get("memory_candidate_id"),
                "task_id": row.get("task_id"),
                "memory_type": row.get("memory_type"),
                "lifecycle_state": row.get("lifecycle_state"),
                "decision_status": row.get("decision_status"),
                "confidence_score": row.get("confidence_score"),
                "execution_backend": row.get("execution_backend"),
                "summary": row.get("summary"),
                "updated_at": row.get("updated_at"),
            }
            for row in latest_candidates
        ],
    }


def _recommended_actions(snapshot: dict[str, Any], review_inbox: dict[str, Any], memory_candidates: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    if snapshot.get("operator_focus"):
        actions.append(snapshot["operator_focus"])

    pending_reviews = review_inbox.get("pending_reviews", [])
    for row in pending_reviews[:3]:
        actions.append(f"Review `{row['review_id']}` for task `{row['task_id']}`.")

    pending_approvals = review_inbox.get("pending_approvals", [])
    for row in pending_approvals[:3]:
        actions.append(f"Decide approval `{row['approval_id']}` for task `{row['task_id']}`.")

    candidate_memories = [
        row
        for row in _sort_recent(memory_candidates, "updated_at", "created_at")
        if row.get("lifecycle_state") == "candidate"
    ]
    for row in candidate_memories[:3]:
        actions.append(
            f"Decide memory candidate `{row['memory_candidate_id']}` ({row.get('memory_type', 'unknown')}) for task `{row['task_id']}`."
        )

    if not actions:
        actions.append("No immediate manual checkpoint items. Inspect recent artifacts and traces for the next bounded run.")
    return actions


def _build_markdown(pack: dict[str, Any]) -> str:
    lines = [
        "# Operator Handoff Pack",
        "",
        f"Generated at: {pack['generated_at']}",
        "",
        "## Recent Task Status",
    ]
    for row in pack["recent_task_status"]:
        lines.append(
            f"- {row['task_id']}: status={row['status']} backend={row.get('execution_backend')} control={row.get('control_status')} summary={row['summary']}"
        )
        if row.get("last_successful_operator_action"):
            lines.append(
                f"  last_success={row['last_successful_operator_action']['action_id']} ack={row['last_successful_operator_action']['ack_summary']}"
            )
        if row.get("last_failed_operator_action"):
            lines.append(
                f"  last_failed={row['last_failed_operator_action']['action_id']} stderr={row['last_failed_operator_action']['stderr_snapshot']}"
            )

    lines.extend(["", "## Artifacts"])
    lines.append(f"- candidate_artifacts={len(pack['artifacts']['candidate'])}")
    lines.append(f"- promoted_artifacts={len(pack['artifacts']['promoted'])}")

    lines.extend(["", "## Latest Traces"])
    for row in pack["latest_trace_summary"]:
        lines.append(f"- {row['trace_id']}: {row['trace_kind']} status={row['status']} task={row['task_id']}")

    lines.extend(["", "## Latest Evals"])
    for row in pack["latest_eval_summary"]:
        lines.append(
            f"- {row['eval_result_id']}: passed={row['passed']} score={row['score']} task={row['task_id']} summary={row['summary']}"
        )
    lines.extend(["", "## 5.2 Prep Runtime Summary"])
    backend_health = pack.get("backend_health_summary", {})
    active_nodes = pack.get("active_nodes_summary", {})
    degraded = pack.get("degraded_state_summary", {})
    eval_scaffolding = pack.get("eval_scaffolding_summary", {})
    lines.append(
        f"- backend_snapshots={backend_health.get('snapshot_count')} unhealthy_lanes={backend_health.get('unhealthy_lane_count')} active_nodes={active_nodes.get('active_node_count')}"
    )
    lines.append(
        f"- degraded_backends={degraded.get('degraded_backend_count')} eval_runs={eval_scaffolding.get('eval_run_count')} reroute_scaffolding_only={((pack.get('reroute_summary') or {}).get('scaffolding_only'))}"
    )

    lines.extend(["", "## Recent Operator Actions"])
    for row in pack["recent_operator_action_executions"]:
        lines.append(
            f"- {row['execution_id']}: action={row['action_id']} success={row['success']} dry_run={row['dry_run']} pack={row['source_action_pack_id']} status={row['source_action_pack_validation_status']} ack={row['ack_summary']}"
        )
    if not pack["recent_operator_action_executions"]:
        lines.append("- none")

    lines.extend(["", "## Recent Queue Runs"])
    for row in pack["recent_operator_queue_runs"]:
        lines.append(
            f"- {row['queue_run_id']}: ok={row['ok']} attempted={row['attempted_count']} failed={row['failed_count']} skipped={row['skipped_count']} policy_skips={row['policy_skipped_count']} idempotency_skips={row['idempotency_skipped_count']} stale_skips={row['stale_skipped_count']} stopped_on={row['stopped_on_action_id']}"
        )
        lines.append(
            f"  policy allow={row['policy_summary'].get('effective_allow_categories', [])} deny={row['policy_summary'].get('deny_categories', [])}"
        )
        if row.get("recent_skip_reasons"):
            lines.append(f"  skips={row['recent_skip_reasons']}")
    if not pack["recent_operator_queue_runs"]:
        lines.append("- none")

    lines.extend(["", "## Recent Bulk Runs"])
    for row in pack["recent_operator_bulk_runs"]:
        lines.append(
            f"- {row['bulk_run_id']}: ok={row['ok']} attempted={row['attempted_count']} failed={row['failed_count']} skipped={row['skipped_count']} pack={row['source_action_pack_id']} status={row['source_action_pack_validation_status']} stop_reason={row['stop_reason']}"
        )
    if not pack["recent_operator_bulk_runs"]:
        lines.append("- none")

    lines.extend(["", "## Recent Task Interventions"])
    for row in pack["recent_operator_task_interventions"]:
        lines.append(
            f"- {row['intervention_id']}: task={row['task_id']} ok={row['ok']} dry_run={row['dry_run']} action={row['selected_action_id']} blockers={row['blocker_summary']}"
        )
    if not pack["recent_operator_task_interventions"]:
        lines.append("- none")

    lines.extend(["", "## Recent Safe Autofix Runs"])
    for row in pack["recent_operator_safe_autofix_runs"]:
        lines.append(
            f"- {row['autofix_run_id']}: ok={row['ok']} rebuild={row['rebuild_happened']} selected={row['safe_action_selected']} executed={row['safe_action_executed']} dry_run={row['safe_action_dry_run']}"
        )
    if not pack["recent_operator_safe_autofix_runs"]:
        lines.append("- none")

    lines.extend(["", "## Triage Summary"])
    triage_summary = pack.get("triage_summary", {})
    health = triage_summary.get("control_plane_health_summary", {})
    lines.append(
        f"- pending_reviews={health.get('pending_review_count')} pending_approvals={health.get('pending_approval_count')} candidate_memory={health.get('candidate_memory_count')} queue_failures={health.get('queue_failure_count')} bulk_failures={health.get('bulk_failure_count')}"
    )
    repeated = triage_summary.get("repeated_problem_detectors", {})
    lines.append(
        f"- repeated_stale={len(repeated.get('repeated_stale_actions', []))} repeated_idempotency={len(repeated.get('repeated_idempotency_skips', []))} repeated_pinned_failures={len(repeated.get('repeated_pinned_pack_validation_failures', []))} repeated_expired={len(repeated.get('repeated_expired_pack_refusals', []))}"
    )

    lines.extend(["", "## Command Center"])
    cc = pack.get("command_center_summary", {})
    lines.append(f"- health={cc.get('health_label')}")
    for row in cc.get("top_next_commands", []):
        lines.append(f"- next {row.get('command_id')}: {row.get('category')} task={row.get('task_id')} action={row.get('action_id')}")

    lines.extend(["", "## Decision Manifest"])
    manifest = pack.get("decision_manifest_summary", {})
    lines.append(
        f"- pack={manifest.get('current_pack_identity', {}).get('action_pack_id')} status={manifest.get('current_pack_identity', {}).get('status')}"
    )
    for row in manifest.get("do_not_run_items", []):
        lines.append(f"- do_not_run task={row.get('task_id')} action={row.get('action_id')} reason={row.get('reason')}")

    lines.extend(["", "## Decision Inbox"])
    inbox = pack.get("decision_inbox_summary", {})
    lines.append(f"- reply_ready={inbox.get('reply_ready')} safe_items={inbox.get('reply_safe_item_count')} pack={inbox.get('pack_id')} status={inbox.get('pack_status')}")
    for row in inbox.get("top_items", []):
        lines.append(f"- {row.get('default_reply_code')} task={row.get('task_id')} category={row.get('category')} reason={row.get('brief_reason')}")

    lines.extend(["", "## Reply Ingress"])
    ingress = pack.get("reply_ingress_summary", {})
    lines.append(
        f"- reply_ingest_ready={ingress.get('reply_ingest_ready')} latest_result={((pack.get('latest_reply_ingress') or {}).get('result_kind'))} "
        f"ignored={ingress.get('ignored_count')} invalid={ingress.get('invalid_count')} blocked={ingress.get('blocked_count')} applied={ingress.get('applied_count')}"
    )
    prompt = pack.get("outbound_prompt_summary", {})
    ack = pack.get("reply_ack_summary", {})
    transport = pack.get("latest_reply_transport_cycle") or {}
    lines.append(
        f"- pending_inbound={ingress.get('pending_inbound_message_count')} transport_ready={ingress.get('reply_transport_ready')} "
        f"prompt_pack={prompt.get('pack_id')} ack_result={ack.get('latest_result_kind')} latest_cycle={transport.get('transport_cycle_id')}"
    )
    lines.append(
        f"- replay_safe={ingress.get('latest_cycle_replay_safe')} latest_compare={((pack.get('latest_compare_reply_transport_cycles') or {}).get('current_cycle_id'))} "
        f"latest_replay={((pack.get('latest_reply_transport_replay') or {}).get('replay_id'))}"
    )
    bridge = pack.get("gateway_bridge_summary", {})
    lines.append(
        f"- outbound_publish_ready={bridge.get('outbound_publish_ready')} inbound_import_ready={bridge.get('inbound_import_ready')} "
        f"bridge_ready={bridge.get('bridge_ready')} latest_import={bridge.get('latest_import_classification')} latest_bridge={bridge.get('latest_bridge_result')}"
    )
    lines.append(
        f"- bridge_replay_safe={((pack.get('bridge_replay_summary') or {}).get('replay_allowed'))} "
        f"latest_bridge_replay={((pack.get('latest_bridge_replay') or {}).get('bridge_replay_id'))} "
        f"latest_bridge_compare={((pack.get('latest_compare_bridge_cycles') or {}).get('current_bridge_cycle_id'))}"
    )
    doctor = pack.get("doctor_summary", {})
    lines.append(
        f"- doctor_health={doctor.get('health_status')} highest_severity={doctor.get('highest_severity')} "
        f"active_issues={doctor.get('active_issue_count')} latest_plan={((pack.get('latest_remediation_plan') or {}).get('remediation_plan_id'))} "
        f"latest_run={((pack.get('latest_remediation_run') or {}).get('remediation_run_id'))}"
    )

    lines.extend(["", "## Action Pack"])
    action_pack = pack.get("current_action_pack", {})
    lines.append(
        f"- current={action_pack.get('action_pack_id')} status={action_pack.get('status')} expires_at={action_pack.get('expires_at')} ttl={action_pack.get('recommended_ttl_seconds')}"
    )

    lines.extend(["", "## Pending Review / Approval"])
    for row in pack["pending_review_items"]:
        lines.append(f"- review {row['review_id']} task={row['task_id']} reviewer={row['reviewer_role']} summary={row['summary']}")
    for row in pack["pending_approval_items"]:
        lines.append(
            f"- approval {row['approval_id']} task={row['task_id']} reviewer={row['requested_reviewer']} summary={row['summary']}"
        )
    if not pack["pending_review_items"] and not pack["pending_approval_items"]:
        lines.append("- none")

    lines.extend(["", "## Ralph / Memory"])
    for row in pack["ralph_memory_summary"]["latest_consolidation_runs"]:
        lines.append(
            f"- consolidation {row['consolidation_run_id']} task={row['task_id']} digest={row['digest_artifact_id']} status={row['status']}"
        )
    for row in pack["ralph_memory_summary"]["latest_memory_candidates"]:
        lines.append(
            f"- memory {row['memory_candidate_id']} task={row['task_id']} type={row['memory_type']} lifecycle={row['lifecycle_state']} decision={row['decision_status']}"
        )

    lines.extend(["", "## Recommended Next Actions"])
    for action in pack["recommended_next_actions"]:
        lines.append(f"- {action}")

    return "\n".join(lines).strip() + "\n"


def build_operator_handoff_pack(root: Path, *, limit: int = 10) -> dict[str, Any]:
    snapshot = build_operator_snapshot(root)
    task_board = build_task_board(root)
    review_inbox = build_review_inbox(root)
    state_export = build_state_export(root)
    eval_scaffolding_summary = build_eval_run_summary(root=root)

    artifacts = _load_jsons(root / "state" / "artifacts")
    run_traces = _load_jsons(root / "state" / "run_traces")
    eval_results = _load_jsons(root / "state" / "eval_results")
    consolidation_runs = _load_jsons(root / "state" / "consolidation_runs")
    memory_candidates = _load_jsons(root / "state" / "memory_candidates")
    operator_action_executions = _load_jsons(root / "state" / "operator_action_executions")
    operator_queue_runs = _load_jsons(root / "state" / "operator_queue_runs")
    operator_bulk_runs = _load_jsons(root / "state" / "operator_bulk_runs")
    operator_task_interventions = _load_jsons(root / "state" / "operator_task_interventions")
    operator_safe_autofix_runs = _load_jsons(root / "state" / "operator_safe_autofix_runs")
    operator_reply_plans = _load_jsons(root / "state" / "operator_reply_plans")
    operator_reply_applies = _load_jsons(root / "state" / "operator_reply_applies")
    operator_reply_ingress = _load_jsons(root / "state" / "operator_reply_ingress")
    operator_reply_ingress_runs = _load_jsons(root / "state" / "operator_reply_ingress_runs")
    operator_reply_transport_cycles = _load_jsons(root / "state" / "operator_reply_transport_cycles")
    operator_reply_transport_replays = _load_jsons(root / "state" / "operator_reply_transport_replays")
    operator_outbound_packets = _load_jsons(root / "state" / "operator_outbound_packets")
    operator_imported_reply_messages = _load_jsons(root / "state" / "operator_imported_reply_messages")
    operator_bridge_cycles = _load_jsons(root / "state" / "operator_bridge_cycles")
    operator_bridge_replays = _load_jsons(root / "state" / "operator_bridge_replays")
    operator_doctor_reports = _load_jsons(root / "state" / "operator_doctor_reports")
    operator_remediation_plans = _load_jsons(root / "state" / "operator_remediation_plans")
    operator_remediation_runs = _load_jsons(root / "state" / "operator_remediation_runs")
    operator_remediation_step_runs = _load_jsons(root / "state" / "operator_remediation_step_runs")
    operator_recovery_cycles = _load_jsons(root / "state" / "operator_recovery_cycles")
    operator_control_plane_checkpoints = _load_jsons(root / "state" / "operator_control_plane_checkpoints")
    operator_incident_reports = _load_jsons(root / "state" / "operator_incident_reports")
    operator_incident_snapshots = _load_jsons(root / "state" / "operator_incident_snapshots")
    recent_task_status = task_board["rows"][:limit]
    for row in recent_task_status:
        latest_success = latest_successful_action_for_task(root, row["task_id"])
        latest_failed = latest_failed_action_for_task(root, row["task_id"])
        row["last_successful_operator_action"] = latest_success
        row["last_failed_operator_action"] = latest_failed

    from scripts.operator_checkpoint_action_pack import classify_action_pack
    from scripts.operator_triage_support import (
        build_decision_inbox_data,
        build_decision_shortlist_data,
        build_triage_data,
        classify_bridge_replay_safety,
        classify_reply_transport_replay_safety,
        gateway_operator_bridge_readiness,
        load_bridge_cycle,
        load_reply_transport_cycle,
    )
    from scripts.operator_triage_support import build_command_center_data, build_decision_manifest_data

    current_action_pack_path = root / "state" / "logs" / "operator_checkpoint_action_pack.json"
    current_action_pack = {
        "path": str(current_action_pack_path),
        "status": "malformed",
        "reason": "Current action pack not found.",
        "action_pack_id": None,
        "action_pack_fingerprint": None,
        "generated_at": None,
        "expires_at": None,
        "recommended_ttl_seconds": None,
        "fresh": False,
    }
    if current_action_pack_path.exists():
        try:
            current_action_pack = {"path": str(current_action_pack_path), **classify_action_pack(json.loads(current_action_pack_path.read_text(encoding="utf-8")))}
        except Exception as exc:
            current_action_pack = {"path": str(current_action_pack_path), "status": "malformed", "reason": str(exc), "fresh": False}

    action_failures = [row for row in operator_action_executions if not row.get("success", False)]
    expired_pack_refusals = sum(
        1
        for row in action_failures
        if row.get("failure_kind") == "expired_pack"
    )
    pinned_pack_validation_failures = sum(
        1
        for row in action_failures
        if row.get("failure_kind") == "pinned_pack_validation_failed"
    )
    triage_summary = build_triage_data(root, limit=limit, allow_pack_rebuild=False)
    command_center = build_command_center_data(root, limit=limit, allow_pack_rebuild=False)
    decision_manifest = build_decision_manifest_data(root, limit=limit, allow_pack_rebuild=False)
    decision_inbox = build_decision_inbox_data(root, limit=limit, allow_pack_rebuild=False)
    decision_shortlist = build_decision_shortlist_data(root, limit=min(limit, 5), allow_inbox_rebuild=False)
    repeated = triage_summary.get("repeated_problem_detectors", {})
    latest_compare_packs = None
    latest_compare_triage = None
    latest_compare_inbox = None
    outbound_prompt = None
    reply_ack = None
    latest_compare_reply_transport = None
    latest_compare_bridge_cycles = None
    latest_compare_control_plane_checkpoints = None
    compare_packs_path = root / "state" / "logs" / "operator_compare_packs_latest.json"
    compare_triage_path = root / "state" / "logs" / "operator_compare_triage_latest.json"
    compare_inbox_path = root / "state" / "logs" / "operator_compare_inbox_latest.json"
    compare_reply_transport_path = root / "state" / "logs" / "operator_compare_reply_transport_cycles_latest.json"
    compare_bridge_cycles_path = root / "state" / "logs" / "operator_compare_bridge_cycles_latest.json"
    compare_control_plane_checkpoints_path = root / "state" / "logs" / "operator_compare_control_plane_checkpoints_latest.json"
    outbound_prompt_path = root / "state" / "logs" / "operator_outbound_prompt_latest.json"
    reply_ack_path = root / "state" / "logs" / "operator_reply_ack_latest.json"
    if compare_packs_path.exists():
        try:
            latest_compare_packs = json.loads(compare_packs_path.read_text(encoding="utf-8"))
        except Exception:
            latest_compare_packs = None
    if compare_triage_path.exists():
        try:
            latest_compare_triage = json.loads(compare_triage_path.read_text(encoding="utf-8"))
        except Exception:
            latest_compare_triage = None
    if compare_inbox_path.exists():
        try:
            latest_compare_inbox = json.loads(compare_inbox_path.read_text(encoding="utf-8"))
        except Exception:
            latest_compare_inbox = None
    if compare_reply_transport_path.exists():
        try:
            latest_compare_reply_transport = json.loads(compare_reply_transport_path.read_text(encoding="utf-8"))
        except Exception:
            latest_compare_reply_transport = None
    if compare_bridge_cycles_path.exists():
        try:
            latest_compare_bridge_cycles = json.loads(compare_bridge_cycles_path.read_text(encoding="utf-8"))
        except Exception:
            latest_compare_bridge_cycles = None
    if compare_control_plane_checkpoints_path.exists():
        try:
            latest_compare_control_plane_checkpoints = json.loads(compare_control_plane_checkpoints_path.read_text(encoding="utf-8"))
        except Exception:
            latest_compare_control_plane_checkpoints = None
    if outbound_prompt_path.exists():
        try:
            outbound_prompt = json.loads(outbound_prompt_path.read_text(encoding="utf-8"))
        except Exception:
            outbound_prompt = None
    if reply_ack_path.exists():
        try:
            reply_ack = json.loads(reply_ack_path.read_text(encoding="utf-8"))
        except Exception:
            reply_ack = None
    latest_cycle_record = load_reply_transport_cycle(root, operator_reply_transport_cycles[-1]["transport_cycle_id"]) if operator_reply_transport_cycles else None
    latest_cycle_replay_safety = (
        classify_reply_transport_replay_safety(root, cycle=latest_cycle_record, live_apply_requested=False) if latest_cycle_record else None
    )
    latest_bridge_cycle_record = load_bridge_cycle(root, operator_bridge_cycles[-1]["bridge_cycle_id"]) if operator_bridge_cycles else None
    latest_bridge_replay_safety = (
        classify_bridge_replay_safety(root, cycle=latest_bridge_cycle_record, live_apply_requested=False) if latest_bridge_cycle_record else None
    )

    pack = {
        "generated_at": snapshot["status"].get("generated_at"),
        "model_registry_summary": snapshot.get("routing_summary", {}),
        "backend_assignment_summary": snapshot.get("backend_assignment_summary", {}),
        "execution_contract_summary": snapshot.get("execution_contract_summary", {}),
        "token_budget_summary": snapshot.get("token_budget_summary", {}),
        "degradation_summary": snapshot.get("degradation_summary", {}),
        "heartbeat_summary": snapshot.get("heartbeat_summary", {}),
        "node_registry_summary": snapshot.get("node_registry_summary", {}),
        "node_health_summary": snapshot.get("node_health_summary", {}),
        "active_nodes_summary": snapshot.get("active_nodes_summary", {}),
        "backend_health_summary": snapshot.get("backend_health_summary", {}),
        "accelerator_summary": snapshot.get("accelerator_summary", {}),
        "degraded_state_summary": snapshot.get("degraded_state_summary", {}),
        "reroute_summary": snapshot.get("reroute_summary", {}),
        "hermes_summary": snapshot.get("hermes_summary", {}),
        "autoresearch_summary": snapshot.get("autoresearch_summary", {}),
        "eval_outcome_summary": snapshot.get("eval_outcome_summary", {}),
        "eval_profile_summary": snapshot.get("eval_profile_summary", {}),
        "eval_scaffolding_summary": eval_scaffolding_summary,
        "browser_control_allowlist_summary": snapshot.get("browser_control_allowlist_summary", {}),
        "voice_session_summary": snapshot.get("voice_session_summary", {}),
        "task_lease_summary": snapshot.get("task_lease_summary", {}),
        "skill_scheduler_summary": snapshot.get("skill_scheduler_summary", {}),
        "research_backend_summary": snapshot.get("research_backend_summary", {}),
        "evidence_bundle_summary": snapshot.get("evidence_bundle_summary", {}),
        "vault_summary": snapshot.get("vault_summary", {}),
        "experiment_summary": snapshot.get("experiment_summary", {}),
        "ui_view_summary": snapshot.get("ui_view_summary", {}),
        "task_envelope_summary": snapshot.get("task_envelope_summary", {}),
        "candidate_promotion_summary": snapshot.get("candidate_promotion_summary", {}),
        "provenance_summary": snapshot.get("provenance_summary", {}),
        "replay_summary": snapshot.get("replay_summary", {}),
        "multimodal_summary": snapshot.get("multimodal_summary", {}),
        "memory_discipline_summary": snapshot.get("memory_discipline_summary", {}),
        "promotion_governance_summary": snapshot.get("promotion_governance_summary", {}),
        "rollback_summary": snapshot.get("rollback_summary", {}),
        "approval_session_summary": snapshot.get("approval_session_summary", {}),
        "subsystem_contract_summary": snapshot.get("subsystem_contract_summary", {}),
        "trajectory_summary": snapshot.get("trajectory_summary", {}),
        "operator_profile_summary": snapshot.get("operator_profile_summary", {}),
        "effective_emergency_control_summary": (snapshot.get("control_state", {}) or {}).get("effective", {}),
        "recent_task_status": recent_task_status,
        "artifacts": {
            "candidate": _artifact_summary(artifacts, lifecycle_state="candidate", limit=limit),
            "promoted": _artifact_summary(artifacts, lifecycle_state="promoted", limit=limit),
        },
        "latest_trace_summary": _trace_summary(run_traces, limit=limit),
        "latest_eval_summary": _eval_summary(eval_results, limit=limit),
        "recent_operator_action_executions": _operator_action_execution_summary(operator_action_executions, limit=limit),
        "recent_operator_queue_runs": _operator_queue_run_summary(operator_queue_runs, limit=limit),
        "recent_operator_bulk_runs": _operator_bulk_run_summary(operator_bulk_runs, limit=limit),
        "recent_operator_task_interventions": _task_intervention_summary(operator_task_interventions, limit=limit),
        "recent_operator_safe_autofix_runs": _safe_autofix_summary(operator_safe_autofix_runs, limit=limit),
        "current_action_pack": current_action_pack,
        "triage_summary": triage_summary,
        "command_center_summary": {
            "health_label": command_center.get("now", {}).get("control_plane_health_label"),
            "top_next_commands": command_center.get("next_actions", [])[:5],
            "recent_deltas": command_center.get("recent_deltas", {}),
        },
        "decision_manifest_summary": {
            "current_pack_identity": decision_manifest.get("current_pack_identity", {}),
            "ranked_next_commands": decision_manifest.get("ranked_next_commands", [])[:5],
            "do_not_run_items": decision_manifest.get("do_not_run_items", [])[:5],
        },
        "decision_inbox_summary": {
            "reply_ready": decision_inbox.get("reply_ready"),
            "pack_id": decision_inbox.get("pack_id"),
            "pack_status": decision_inbox.get("pack_status"),
            "reply_safe_item_count": sum(1 for row in decision_inbox.get("items", []) if any(code[0] in {"A", "R", "P"} for code in row.get("allowed_reply_codes", []))),
            "top_items": decision_inbox.get("items", [])[:5],
        },
        "decision_shortlist_summary": decision_shortlist,
        "reply_ingress_summary": {
            "reply_ingest_ready": bool(decision_inbox.get("reply_ready")) and current_action_pack.get("status") == "valid",
            "reply_transport_ready": bool(decision_inbox.get("reply_ready")) and current_action_pack.get("status") == "valid",
            "ignored_count": sum(1 for row in operator_reply_ingress if row.get("result_kind") == "ignored_non_reply"),
            "invalid_count": sum(1 for row in operator_reply_ingress if row.get("result_kind") == "invalid_reply"),
            "blocked_count": sum(
                1
                for row in operator_reply_ingress
                if row.get("result_kind") in {"missing_inbox", "stale_inbox", "pack_refresh_required", "blocked", "duplicate_message"}
            ),
            "applied_count": sum(1 for row in operator_reply_ingress if row.get("result_kind") == "applied"),
            "duplicate_count": sum(1 for row in operator_reply_ingress if row.get("result_kind") == "duplicate_message"),
            "pending_inbound_message_count": sum(1 for row in _load_jsons(root / "state" / "operator_reply_messages") if not row.get("processed_at")),
            "latest_cycle_replay_safe": bool((latest_cycle_replay_safety or {}).get("replay_allowed")),
            "latest_source_metadata": {
                "source_kind": (operator_reply_ingress[-1] if operator_reply_ingress else {}).get("source_kind"),
                "source_lane": (operator_reply_ingress[-1] if operator_reply_ingress else {}).get("source_lane"),
                "source_channel": (operator_reply_ingress[-1] if operator_reply_ingress else {}).get("source_channel"),
                "source_message_id": (operator_reply_ingress[-1] if operator_reply_ingress else {}).get("source_message_id"),
                "source_user": (operator_reply_ingress[-1] if operator_reply_ingress else {}).get("source_user"),
            },
        },
        "pending_review_items": review_inbox["pending_reviews"],
        "pending_approval_items": review_inbox["pending_approvals"],
        "ralph_memory_summary": _ralph_memory_summary(consolidation_runs, memory_candidates, limit=limit),
        "recommended_next_actions": _recommended_actions(snapshot, review_inbox, memory_candidates),
        "status_counts": snapshot.get("status", {}).get("counts", {}),
        "state_export_counts": state_export.get("counts", {}),
        "operator_control_plane_counts": {
            "expired_pack_refusals": expired_pack_refusals,
            "pinned_pack_validation_failures": pinned_pack_validation_failures,
            "repeated_stale_actions": len(repeated.get("repeated_stale_actions", [])),
            "repeated_idempotency_skips": len(repeated.get("repeated_idempotency_skips", [])),
        },
        "control_state": snapshot.get("control_state", {}),
        "operator_focus": snapshot.get("operator_focus", ""),
        "review_inbox_reply": review_inbox.get("reply", ""),
        "latest_operator_queue_run": _operator_queue_run_summary(operator_queue_runs, limit=1)[0] if operator_queue_runs else None,
        "latest_operator_bulk_run": _operator_bulk_run_summary(operator_bulk_runs, limit=1)[0] if operator_bulk_runs else None,
        "latest_operator_task_intervention": _task_intervention_summary(operator_task_interventions, limit=1)[0]
        if operator_task_interventions
        else None,
        "latest_operator_safe_autofix_run": _safe_autofix_summary(operator_safe_autofix_runs, limit=1)[0]
        if operator_safe_autofix_runs
        else None,
        "latest_reply_plan": _reply_plan_summary(operator_reply_plans, limit=1)[0] if operator_reply_plans else None,
        "latest_reply_apply": _reply_apply_summary(operator_reply_applies, limit=1)[0] if operator_reply_applies else None,
        "latest_reply_ingress": _reply_ingress_summary(operator_reply_ingress, limit=1)[0] if operator_reply_ingress else None,
        "latest_reply_ingress_run": _reply_ingress_run_summary(operator_reply_ingress_runs, limit=1)[0] if operator_reply_ingress_runs else None,
        "recent_reply_ingress": _reply_ingress_summary(operator_reply_ingress, limit=limit),
        "recent_reply_ingress_runs": _reply_ingress_run_summary(operator_reply_ingress_runs, limit=limit),
        "latest_reply_transport_cycle": _reply_transport_cycle_summary(operator_reply_transport_cycles, limit=1)[0]
        if operator_reply_transport_cycles
        else None,
        "recent_reply_transport_cycles": _reply_transport_cycle_summary(operator_reply_transport_cycles, limit=limit),
        "latest_reply_transport_replay": _reply_transport_replay_summary(operator_reply_transport_replays, limit=1)[0]
        if operator_reply_transport_replays
        else None,
        "recent_reply_transport_replays": _reply_transport_replay_summary(operator_reply_transport_replays, limit=limit),
        "reply_transport_replay_summary": latest_cycle_replay_safety or {},
        "latest_outbound_packet": _outbound_packet_summary(operator_outbound_packets, limit=1)[0] if operator_outbound_packets else None,
        "recent_outbound_packets": _outbound_packet_summary(operator_outbound_packets, limit=limit),
        "latest_imported_reply_message": _imported_reply_message_summary(operator_imported_reply_messages, limit=1)[0]
        if operator_imported_reply_messages
        else None,
        "recent_imported_reply_messages": _imported_reply_message_summary(operator_imported_reply_messages, limit=limit),
        "latest_bridge_cycle": _bridge_cycle_summary(operator_bridge_cycles, limit=1)[0] if operator_bridge_cycles else None,
        "recent_bridge_cycles": _bridge_cycle_summary(operator_bridge_cycles, limit=limit),
        "latest_bridge_replay": _bridge_replay_summary(operator_bridge_replays, limit=1)[0] if operator_bridge_replays else None,
        "recent_bridge_replays": _bridge_replay_summary(operator_bridge_replays, limit=limit),
        "bridge_replay_summary": latest_bridge_replay_safety or {},
        "latest_doctor_report": _doctor_report_summary(operator_doctor_reports, limit=1)[0] if operator_doctor_reports else None,
        "recent_doctor_reports": _doctor_report_summary(operator_doctor_reports, limit=limit),
        "latest_remediation_plan": _remediation_plan_summary(operator_remediation_plans, limit=1)[0] if operator_remediation_plans else None,
        "recent_remediation_plans": _remediation_plan_summary(operator_remediation_plans, limit=limit),
        "latest_remediation_run": _remediation_run_summary(operator_remediation_runs, limit=1)[0] if operator_remediation_runs else None,
        "recent_remediation_runs": _remediation_run_summary(operator_remediation_runs, limit=limit),
        "latest_recovery_cycle": _recovery_cycle_summary(operator_recovery_cycles, limit=1)[0] if operator_recovery_cycles else None,
        "recent_recovery_cycles": _recovery_cycle_summary(operator_recovery_cycles, limit=limit),
        "latest_control_plane_checkpoint": _control_plane_checkpoint_summary(operator_control_plane_checkpoints, limit=1)[0]
        if operator_control_plane_checkpoints
        else None,
        "recent_control_plane_checkpoints": _control_plane_checkpoint_summary(operator_control_plane_checkpoints, limit=limit),
        "latest_incident_report": _incident_report_summary(operator_incident_reports, limit=1)[0] if operator_incident_reports else None,
        "recent_incident_reports": _incident_report_summary(operator_incident_reports, limit=limit),
        "doctor_summary": {
            "health_status": (operator_doctor_reports[-1] if operator_doctor_reports else {}).get("health_status", "unknown"),
            "highest_severity": (operator_doctor_reports[-1] if operator_doctor_reports else {}).get("highest_severity", "unknown"),
            "active_issue_count": (operator_doctor_reports[-1] if operator_doctor_reports else {}).get("active_issue_count", 0),
            "next_recommended_commands": ((operator_doctor_reports[-1] if operator_doctor_reports else {}).get("next_recommended_commands", []))[:5],
        },
        "remediation_run_summary": {
            "latest_remediation_run_id": (operator_remediation_runs[-1] if operator_remediation_runs else {}).get("remediation_run_id"),
            "latest_remediation_run_ok": (operator_remediation_runs[-1] if operator_remediation_runs else {}).get("ok"),
            "latest_remediation_run_dry_run": (operator_remediation_runs[-1] if operator_remediation_runs else {}).get("dry_run"),
            "latest_remediation_run_attempted_step_count": (operator_remediation_runs[-1] if operator_remediation_runs else {}).get("attempted_step_count"),
            "latest_remediation_run_failed_step_count": (operator_remediation_runs[-1] if operator_remediation_runs else {}).get("failed_step_count"),
            "latest_remediation_run_stop_reason": (operator_remediation_runs[-1] if operator_remediation_runs else {}).get("stop_reason"),
            "remediation_run_count": len(operator_remediation_runs),
            "remediation_step_run_count": len(operator_remediation_step_runs),
        },
        "recovery_cycle_summary": {
            "latest_recovery_cycle_id": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("recovery_cycle_id"),
            "latest_recovery_cycle_ok": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("ok"),
            "latest_recovery_cycle_dry_run": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("dry_run"),
            "latest_recovery_cycle_active_issue_count_before": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("active_issue_count_before"),
            "latest_recovery_cycle_active_issue_count_after": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("active_issue_count_after"),
            "latest_recovery_cycle_issue_count_before": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("active_issue_count_before"),
            "latest_recovery_cycle_issue_count_after": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("active_issue_count_after"),
            "latest_recovery_cycle_stop_reason": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("stop_reason"),
            "recovery_cycle_count": len(operator_recovery_cycles),
        },
        "control_plane_checkpoint_summary": {
            "latest_control_plane_checkpoint_id": (operator_control_plane_checkpoints[-1] if operator_control_plane_checkpoints else {}).get("control_plane_checkpoint_id"),
            "control_plane_checkpoint_count": len(operator_control_plane_checkpoints),
            "latest_compare_checkpoint_id": (latest_compare_control_plane_checkpoints or {}).get("current_checkpoint_id"),
        },
        "incident_summary": {
            "latest_incident_report_id": (operator_incident_reports[-1] if operator_incident_reports else {}).get("incident_report_id"),
            "latest_incident_code": (operator_incident_reports[-1] if operator_incident_reports else {}).get("incident_code"),
            "latest_incident_severity": (operator_incident_reports[-1] if operator_incident_reports else {}).get("severity"),
            "operator_incident_report_count": len(operator_incident_reports),
            "operator_incident_snapshot_count": len(operator_incident_snapshots),
        },
        "outbound_prompt_summary": {
            "generated_at": (outbound_prompt or {}).get("generated_at"),
            "pack_id": (outbound_prompt or {}).get("pack_id"),
            "pack_status": (outbound_prompt or {}).get("pack_status"),
            "reply_ready": (outbound_prompt or {}).get("reply_ready"),
            "warning": (outbound_prompt or {}).get("warning", ""),
            "top_items": (outbound_prompt or {}).get("top_items", [])[:5],
        },
        "reply_ack_summary": {
            "generated_at": (reply_ack or {}).get("generated_at"),
            "latest_result_kind": ((reply_ack or {}).get("latest_reply_received") or {}).get("result_kind"),
            "next_guidance": (reply_ack or {}).get("next_guidance", ""),
            "next_suggested_codes": (reply_ack or {}).get("next_suggested_codes", [])[:5],
        },
        "gateway_bridge_summary": {
            **gateway_operator_bridge_readiness(root, allow_inbox_rebuild=False, limit=min(limit, 5)),
            "latest_import_classification": (operator_imported_reply_messages[-1] if operator_imported_reply_messages else {}).get("classification"),
            "latest_bridge_result": (operator_bridge_cycles[-1] if operator_bridge_cycles else {}).get("ok"),
            "outbound_packet_count": len(operator_outbound_packets),
            "imported_reply_message_count": len(operator_imported_reply_messages),
            "bridge_cycle_count": len(operator_bridge_cycles),
            "bridge_replay_count": len(operator_bridge_replays),
            "latest_bridge_replay_ok": (operator_bridge_replays[-1] if operator_bridge_replays else {}).get("ok"),
        },
        "latest_compare_reply_transport_cycles": latest_compare_reply_transport,
        "latest_compare_bridge_cycles": latest_compare_bridge_cycles,
        "latest_compare_control_plane_checkpoints": latest_compare_control_plane_checkpoints,
        "latest_compare_packs": latest_compare_packs,
        "latest_compare_triage": latest_compare_triage,
        "latest_compare_inbox": latest_compare_inbox,
    }

    markdown = _build_markdown(pack)
    json_path = root / "state" / "logs" / "operator_handoff_pack.json"
    markdown_path = root / "state" / "logs" / "operator_handoff_pack.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")

    return {
        "pack": pack,
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an operator handoff pack from durable state.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=10, help="Maximum recent items per section")
    args = parser.parse_args()

    result = build_operator_handoff_pack(Path(args.root).resolve(), limit=args.limit)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
