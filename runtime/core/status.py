#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.candidate_store import build_candidate_summary
from runtime.core.degradation_policy import build_degradation_summary
from runtime.core.execution_contracts import build_execution_contract_summary
from runtime.core.models import OutputStatus, RecordLifecycleState, TaskRecord, TaskStatus
from runtime.core.token_budget import build_token_budget_summary
from runtime.core.approval_sessions import build_approval_session_summary
from runtime.core.browser_control_allowlist import build_browser_control_allowlist_summary
from runtime.core.backend_assignments import build_backend_assignment_summary
from runtime.core.eval_profiles import build_eval_profile_summary
from runtime.core.heartbeat_reports import build_heartbeat_report_summary
from runtime.core.mcp_policy import build_mcp_policy_summary
from runtime.core.plugin_policy import build_plugin_policy_summary
from runtime.core.policy_surface_summary import build_policy_surface_summary
from runtime.core.prompt_caching_policy import build_prompt_caching_policy_summary
from runtime.core.provenance_store import build_provenance_summary
from runtime.core.promotion_governance import build_promotion_governance_summary
from runtime.core.rollback_store import build_rollback_summary
from runtime.core.routing import build_model_registry_summary, build_routing_failure_summary
from runtime.core.security_validation import build_security_validation_summary
from runtime.core.modality_contracts import build_modality_summary
from runtime.core.agent_roster import build_agent_roster_summary
from runtime.core.subsystem_contracts import build_subsystem_contract_summary
from runtime.core.trajectory_profiles import build_operator_profile_summary, build_trajectory_summary
from runtime.core.voice_sessions import build_voice_session_summary
from runtime.core.a2a_policy import build_a2a_policy_summary
from runtime.core.workspace_registry import summarize_workspace_registry
from runtime.adaptation_lab.summary import summarize_adaptation_lab
from runtime.integrations.research_backends import build_research_backend_summary
from runtime.integrations.lane_activation import summarize_lane_activation
from runtime.integrations.lane_activation import latest_lane_activation_result
from runtime.optimizer.eval_gate import summarize_optimizer_lane
from runtime.integrations.shadowbroker_adapter import summarize_shadowbroker_backend
from runtime.integrations.openclaw_sessions import build_openclaw_discord_session_integrity_summary
from runtime.world_ops.summary import build_world_ops_summary
from runtime.browser.reporting import build_browser_action_summary
from runtime.controls.control_store import build_control_summary, get_effective_control_state, list_blocked_actions, list_control_events, list_control_records
from runtime.integrations.notification_adapter import build_notification_summary
from runtime.voice.router import build_voice_route_capability_summary, build_voice_route_safety_summary


def build_routing_control_plane_summary(
    *,
    routing_summary: dict[str, Any],
    degradation_summary: dict[str, Any],
    heartbeat_summary: dict[str, Any],
) -> dict[str, Any]:
    latest_resolution = dict(routing_summary.get("latest_runtime_route_resolution") or {})
    latest_failure = dict(routing_summary.get("latest_failed_routing_request") or {})
    latest_degradation = dict(degradation_summary.get("latest_degradation_event") or {})
    node_health = dict((heartbeat_summary or {}).get("node_health_summary") or {})
    topology_posture = str(node_health.get("topology_posture") or "unknown")

    route_state = str(latest_resolution.get("route_resolution_state") or "")
    route_legality = str(latest_resolution.get("route_legality_status") or "")
    if latest_failure and (
        not latest_resolution
        or str(latest_failure.get("updated_at") or "") >= str(latest_resolution.get("updated_at") or "")
    ):
        route_state = str(latest_failure.get("route_resolution_state") or "blocked")
        route_legality = str(latest_failure.get("route_legality_status") or "blocked")

    fallback_blocked_for_safety = bool(
        latest_failure.get("fallback_blocked_for_safety")
        or dict(latest_degradation.get("source_refs") or {}).get("fallback_allowed") is False
    )
    latest_selected_route = (
        {
            "provider_id": latest_resolution.get("selected_provider_id"),
            "model_name": latest_resolution.get("selected_model_name"),
            "execution_backend": latest_resolution.get("selected_execution_backend"),
            "node_role": latest_resolution.get("selected_node_role"),
            "host_name": latest_resolution.get("selected_host_name"),
            "selection_reason": latest_resolution.get("selection_reason"),
        }
        if latest_resolution
        else None
    )
    return {
        "latest_route_state": route_state or "unknown",
        "latest_route_legality": route_legality or "unknown",
        "latest_selected_route": latest_selected_route,
        "latest_failed_route": latest_failure or None,
        "latest_degradation_event": latest_degradation or None,
        "fallback_blocked_for_safety": fallback_blocked_for_safety,
        "latest_route_downgraded": bool(latest_resolution.get("rerouted_from_preferred_model", False)),
        "burst_capacity_posture": (
            "optional_capacity_loss"
            if topology_posture in {"healthy_optional_burst_offline", "healthy_optional_capacity_reduced"}
            else "normal"
        ),
        "primary_runtime_posture": "primary_outage" if topology_posture == "primary_outage" else "healthy",
        "topology_posture": topology_posture,
        "topology_notes": list(node_health.get("topology_notes") or []),
    }


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


def _load_tasks(root: Path) -> list[TaskRecord]:
    return [TaskRecord.from_dict(row) for row in _load_jsons(root / "state" / "tasks")]


def _load_events_by_task(root: Path) -> dict[str, list[dict[str, Any]]]:
    rows = _load_jsons(root / "state" / "events")
    events_by_task: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        task_id = row.get("task_id")
        if not task_id:
            continue
        events_by_task.setdefault(task_id, []).append(row)
    for task_id in events_by_task:
        events_by_task[task_id].sort(key=lambda row: row.get("created_at", ""))
    return events_by_task


def _sort_key(task: TaskRecord) -> tuple[str, str]:
    created_at = getattr(task, "created_at", "") or ""
    updated_at = getattr(task, "updated_at", "") or ""
    return (updated_at, created_at)


def _latest_reason(task: TaskRecord, events_by_task: dict[str, list[dict[str, Any]]]) -> str:
    if task.last_error:
        return task.last_error

    for event in reversed(events_by_task.get(task.task_id, [])):
        reason = event.get("reason") or ""
        if reason:
            return reason
    return ""


def _row_timestamp(row: dict[str, Any]) -> str:
    return str(row.get("updated_at") or row.get("created_at") or "")


def _latest_rows_by_task(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_id = str(row.get("task_id") or "")
        if not task_id:
            continue
        current = latest.get(task_id)
        if current is None or _row_timestamp(row) >= _row_timestamp(current):
            latest[task_id] = row
    return latest


def _is_discord_origin(*, lane: str, channel: str) -> bool:
    return "discord" in str(lane or "").lower() or "discord" in str(channel or "").lower()


def _infer_backend_failure_category(result: dict[str, Any] | None) -> str:
    if not result:
        return ""
    metadata = dict(result.get("metadata") or {})
    failure_category = str(metadata.get("failure_category") or metadata.get("error_category") or "").strip()
    if failure_category:
        return failure_category
    text = " ".join(
        [
            str(result.get("status") or ""),
            str(result.get("error") or ""),
            str(result.get("outcome_summary") or ""),
        ]
    ).lower()
    if "unreachable backend" in text or "external runtime unreachable" in text or "connection refused" in text:
        return "external_runtime_unreachable"
    if "model timeout" in text:
        return "model_timeout"
    if "backend timeout" in text:
        return "backend_timeout"
    if "invalid provider" in text or "invalid model" in text or "provider/model" in text:
        return "invalid_provider_model_config"
    if "timeout" in text:
        return "timeout"
    status = str(result.get("status") or "").strip()
    if status and status not in {"completed", "ready"}:
        return status
    return ""


def _normalize_live_lane_failure_category(
    *,
    backend_failure_category: str,
    degradation_event: dict[str, Any] | None,
    blocked_action: dict[str, Any] | None,
) -> str:
    if blocked_action:
        return "governance_blocked"
    degradation_refs = dict((degradation_event or {}).get("source_refs") or {})
    if degradation_event and degradation_refs.get("fallback_allowed") is False:
        return "degraded_fallback_blocked"
    normalized = str(backend_failure_category or "").strip()
    if normalized in {
        "routing_refused",
        "backend_timeout",
        "model_timeout",
        "invalid_provider_model_config",
        "degraded_fallback_blocked",
        "governance_blocked",
        "external_runtime_unreachable",
    }:
        return normalized
    if normalized in {"timeout", "unreachable_backend"}:
        return "backend_timeout"
    if normalized:
        return normalized
    if degradation_event:
        return str(degradation_event.get("failure_category") or "degraded")
    return ""


def _live_lane_next_inspect(
    *,
    failure_category: str,
    row: dict[str, Any],
    latest_discord_routing_refusal: dict[str, Any] | None,
) -> str:
    if failure_category == "routing_refused":
        return "Inspect routing_summary.latest_failed_routing_request and runtime_routing_policy.json."
    if failure_category == "backend_timeout":
        return "Inspect backend_execution_results and the selected backend health on the routed host."
    if failure_category == "model_timeout":
        return "Inspect backend_execution_results for model timeout and the selected model/runtime service."
    if failure_category == "invalid_provider_model_config":
        return "Inspect selected provider/model configuration and backend adapter inputs."
    if failure_category == "degraded_fallback_blocked":
        return "Inspect degradation_summary.latest_degradation_event and fallback legality reasons."
    if failure_category == "governance_blocked":
        return "Inspect promotion_governance_summary.latest_blocked_action and clear the review/approval gate."
    if failure_category == "external_runtime_unreachable":
        return "Inspect backend health and external runtime reachability for the selected backend/model host."
    if latest_discord_routing_refusal and not row.get("route_selected"):
        return "Inspect routing_summary.latest_failed_routing_request."
    if row.get("backend_execution_attempted") and row.get("status") not in {TaskStatus.COMPLETED.value, TaskStatus.SHIPPED.value}:
        return "Inspect backend_execution_results and recent task events for this task."
    return "Inspect the task row, routing metadata, and latest execution result."


def build_discord_live_ops_summary(
    *,
    root: Path,
    tasks: list[TaskRecord] | None = None,
    routing_summary: dict[str, Any] | None = None,
    backend_execution_results: list[dict[str, Any]] | None = None,
    degradation_events: list[dict[str, Any]] | None = None,
    blocked_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    task_rows = sorted(tasks or _load_tasks(root), key=_sort_key, reverse=True)
    latest_backend_by_task = _latest_rows_by_task(
        backend_execution_results if backend_execution_results is not None else _load_jsons(root / "state" / "backend_execution_results")
    )
    latest_degradation_by_task = _latest_rows_by_task(
        degradation_events if degradation_events is not None else _load_jsons(root / "state" / "degradation_events")
    )
    latest_blocked_by_task = _latest_rows_by_task(
        blocked_actions if blocked_actions is not None else _load_jsons(root / "state" / "control_blocked_actions")
    )
    routing = dict(routing_summary or build_model_registry_summary(root))
    latest_failed_request = dict(routing.get("latest_failed_routing_request") or {})
    if latest_failed_request and "failure_code" not in latest_failed_request:
        latest_failed_request = build_routing_failure_summary(latest_failed_request) or {}
    latest_discord_routing_refusal = (
        latest_failed_request or None
        if latest_failed_request
        and _is_discord_origin(
            lane=str(latest_failed_request.get("lane") or ""),
            channel=str(latest_failed_request.get("channel") or ""),
        )
        else None
    )

    rows: list[dict[str, Any]] = []
    failure_category_counts: dict[str, int] = {}
    active_statuses = {
        TaskStatus.QUEUED.value,
        TaskStatus.RUNNING.value,
        TaskStatus.BLOCKED.value,
        TaskStatus.WAITING_REVIEW.value,
        TaskStatus.WAITING_APPROVAL.value,
        TaskStatus.READY_TO_SHIP.value,
    }

    for task in task_rows:
        if not _is_discord_origin(lane=task.source_lane, channel=task.source_channel):
            continue
        routing_meta = dict((task.backend_metadata or {}).get("routing") or {})
        latest_backend = latest_backend_by_task.get(task.task_id)
        latest_degradation = latest_degradation_by_task.get(task.task_id)
        latest_blocked = latest_blocked_by_task.get(task.task_id)
        degradation_refs = dict((latest_degradation or {}).get("source_refs") or {})
        fallback_allowed = degradation_refs.get("fallback_allowed")
        fallback_action = str((latest_degradation or {}).get("fallback_action") or "")
        backend_failure_category = _infer_backend_failure_category(latest_backend)
        failure_candidates: list[tuple[str, str, str]] = []
        if latest_backend and backend_failure_category:
            failure_candidates.append(
                (
                    _row_timestamp(latest_backend),
                    backend_failure_category,
                    str(latest_backend.get("error") or latest_backend.get("outcome_summary") or ""),
                )
            )
        if latest_degradation:
            failure_candidates.append(
                (
                    _row_timestamp(latest_degradation),
                    str(latest_degradation.get("failure_category") or "degraded"),
                    str(latest_degradation.get("reason") or ""),
                )
            )
        if latest_blocked:
            failure_candidates.append(
                (
                    _row_timestamp(latest_blocked),
                    "governance_blocked",
                    str(latest_blocked.get("reason") or ""),
                )
            )
        if task.last_error:
            failure_candidates.append((task.updated_at or task.created_at or "", "task_error", task.last_error))
        failure_candidates.sort(key=lambda row: row[0], reverse=True)
        last_failure_category = _normalize_live_lane_failure_category(
            backend_failure_category=backend_failure_category,
            degradation_event=latest_degradation,
            blocked_action=latest_blocked,
        )
        if not last_failure_category and failure_candidates:
            last_failure_category = failure_candidates[0][1]
        last_failure_reason = failure_candidates[0][2] if failure_candidates else ""
        if last_failure_category:
            failure_category_counts[last_failure_category] = failure_category_counts.get(last_failure_category, 0) + 1

        route_selected = bool(routing_meta.get("routing_decision_id"))
        backend_execution_attempted = latest_backend is not None
        timeout_stage = ""
        timeout_failure_category = backend_failure_category or last_failure_category
        if timeout_failure_category == "model_timeout":
            timeout_stage = "model"
        elif timeout_failure_category in {"backend_timeout", "external_runtime_unreachable"}:
            timeout_stage = "backend"
        row = {
            "task_id": task.task_id,
            "source_front_door": "discord",
            "source_lane": task.source_lane,
            "source_channel": task.source_channel,
            "source_message_id": task.source_message_id,
            "status": task.status,
            "lifecycle_state": task.lifecycle_state,
            "task_type": task.task_type,
            "execution_backend": task.execution_backend,
            "provider_id": routing_meta.get("provider_id"),
            "selected_model_name": task.assigned_model or routing_meta.get("model_name"),
            "selected_node_role": routing_meta.get("selected_node_role"),
            "selected_host_name": routing_meta.get("selected_host_name"),
            "workload_type": routing_meta.get("workload_type"),
            "routing_decision_id": routing_meta.get("routing_decision_id"),
            "route_selected": route_selected,
            "backend_execution_attempted": backend_execution_attempted,
            "last_failure_category": last_failure_category,
            "last_failure_reason": last_failure_reason,
            "backend_failure_category": backend_failure_category,
            "backend_execution_status": (latest_backend or {}).get("status"),
            "backend_execution_result_id": (latest_backend or {}).get("backend_execution_result_id"),
            "timeout_stage": timeout_stage,
            "degradation_event_id": (latest_degradation or {}).get("degradation_event_id"),
            "degradation_mode": (latest_degradation or {}).get("degradation_mode"),
            "degraded_failure_category": (latest_degradation or {}).get("failure_category"),
            "degraded_fallback_action": fallback_action,
            "degraded_fallback_attempted": bool(fallback_action and fallback_action != "no_local_fallback" and fallback_allowed is not False),
            "degraded_fallback_blocked": fallback_allowed is False,
            "degraded_fallback_legal": False if fallback_allowed is False else (True if fallback_action else None),
            "degraded_fallback_legality_reasons": list(degradation_refs.get("fallback_legality_reasons") or []),
            "governance_blocked_action_id": (latest_blocked or {}).get("blocked_action_id"),
            "governance_block_reason": (latest_blocked or {}).get("reason"),
            "updated_at": task.updated_at,
        }
        row["next_inspect"] = _live_lane_next_inspect(
            failure_category=last_failure_category,
            row=row,
            latest_discord_routing_refusal=latest_discord_routing_refusal,
        )
        rows.append(row)

    latest_discord_task = rows[0] if rows else None
    live_lane_diagnostic = {
        "front_door": "discord",
        "route_selected": bool(latest_discord_task and latest_discord_task.get("route_selected")),
        "backend_execution_attempted": bool(latest_discord_task and latest_discord_task.get("backend_execution_attempted")),
        "selected_backend": (latest_discord_task or {}).get("execution_backend"),
        "selected_provider_id": (latest_discord_task or {}).get("provider_id"),
        "selected_model_name": (latest_discord_task or {}).get("selected_model_name"),
        "selected_node_role": (latest_discord_task or {}).get("selected_node_role"),
        "selected_host_name": (latest_discord_task or {}).get("selected_host_name"),
        "failure_category": (latest_discord_task or {}).get("last_failure_category")
        or ("routing_refused" if latest_discord_routing_refusal else ""),
        "failure_reason": (latest_discord_task or {}).get("last_failure_reason")
        or str((latest_discord_routing_refusal or {}).get("failure_reason") or ""),
        "timeout_stage": (latest_discord_task or {}).get("timeout_stage"),
        "degraded_fallback_attempted": bool(latest_discord_task and latest_discord_task.get("degraded_fallback_attempted")),
        "degraded_fallback_blocked": bool(latest_discord_task and latest_discord_task.get("degraded_fallback_blocked")),
        "next_inspect": (
            (latest_discord_task or {}).get("next_inspect")
            or _live_lane_next_inspect(
                failure_category="routing_refused" if latest_discord_routing_refusal else "",
                row={},
                latest_discord_routing_refusal=latest_discord_routing_refusal,
            )
        ),
    }

    return {
        "discord_origin_task_count": len(rows),
        "active_discord_task_count": sum(1 for row in rows if row.get("status") in active_statuses),
        "failure_category_counts": failure_category_counts,
        "recent_discord_tasks": rows[:10],
        "latest_discord_task": latest_discord_task,
        "latest_discord_routing_refusal": latest_discord_routing_refusal,
        "live_lane_diagnostic": live_lane_diagnostic,
    }


def _bridge_row_timestamp(row: dict[str, Any]) -> str:
    return str(
        row.get("completed_at")
        or row.get("imported_at")
        or row.get("processed_at")
        or row.get("started_at")
        or row.get("generated_at")
        or row.get("created_at")
        or ""
    )


def _find_nested_field(payload: Any, keys: tuple[str, ...]) -> Any:
    _empty = (None, "", [], {})
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if value not in _empty:
                return value
        for value in payload.values():
            found = _find_nested_field(value, keys)
            if found not in _empty:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = _find_nested_field(value, keys)
            if found not in _empty:
                return found
    return None


def _bridge_failure_from_apply(apply_row: dict[str, Any] | None) -> tuple[str, str]:
    if not apply_row:
        return "", ""
    payload = dict(apply_row)
    failure = _find_nested_field(payload, ("failure",))
    if isinstance(failure, dict):
        failure_kind = str(failure.get("kind") or "").strip()
        failure_reason = str(failure.get("error") or failure.get("reason") or "").strip()
        if failure_kind:
            return failure_kind, failure_reason
    failure_kind = str(_find_nested_field(payload, ("error_type", "failure_kind", "failure_category")) or "").strip()
    failure_reason = str(
        _find_nested_field(
            payload,
            ("message", "failure_reason", "reason", "error"),
        )
        or ""
    ).strip()
    return failure_kind, failure_reason


def build_openclaw_discord_bridge_summary(
    *,
    root: Path,
    gateway_inbound_messages: list[dict[str, Any]] | None = None,
    imported_reply_messages: list[dict[str, Any]] | None = None,
    reply_ingress: list[dict[str, Any]] | None = None,
    reply_applies: list[dict[str, Any]] | None = None,
    bridge_cycles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    gateway_rows = gateway_inbound_messages if gateway_inbound_messages is not None else _load_jsons(root / "state" / "operator_gateway_inbound_messages")
    imported_rows = imported_reply_messages if imported_reply_messages is not None else _load_jsons(root / "state" / "operator_imported_reply_messages")
    ingress_rows = reply_ingress if reply_ingress is not None else _load_jsons(root / "state" / "operator_reply_ingress")
    apply_rows = reply_applies if reply_applies is not None else _load_jsons(root / "state" / "operator_reply_applies")
    cycle_rows = bridge_cycles if bridge_cycles is not None else _load_jsons(root / "state" / "operator_bridge_cycles")

    apply_by_id = {str(row.get("reply_apply_id") or ""): row for row in apply_rows if row.get("reply_apply_id")}
    bridge_by_message: dict[str, dict[str, Any]] = {}
    for row in cycle_rows:
        for message_id in row.get("imported_source_message_ids", []):
            if message_id and message_id not in bridge_by_message:
                bridge_by_message[str(message_id)] = row

    attempts: dict[str, dict[str, Any]] = {}

    def ensure_attempt(message_id: str) -> dict[str, Any]:
        return attempts.setdefault(
            message_id,
            {
                "source_message_id": message_id,
                "source_kind": "",
                "source_lane": "",
                "source_channel": "",
                "source_user": "",
                "attempted_at": "",
                "mirror_stage": "gateway_inbound",
                "selected_provider_id": None,
                "selected_model_name": None,
                "failure_class": "",
                "failure_reason": "",
                "latest_result_kind": "",
                "reply_applied": False,
                "bridge_cycle_id": None,
                "bridge_cycle_ok": None,
            },
        )

    for row in gateway_rows:
        if not _is_discord_origin(lane=str(row.get("source_lane") or ""), channel=str(row.get("source_channel") or "")):
            continue
        message_id = str(row.get("source_message_id") or "").strip()
        if not message_id:
            continue
        attempt = ensure_attempt(message_id)
        attempt["source_kind"] = str(row.get("source_kind") or attempt["source_kind"] or "openclaw")
        attempt["source_lane"] = str(row.get("source_lane") or attempt["source_lane"])
        attempt["source_channel"] = str(row.get("source_channel") or attempt["source_channel"])
        attempt["source_user"] = str(row.get("source_user") or attempt["source_user"])
        attempt["attempted_at"] = max(attempt["attempted_at"], _bridge_row_timestamp(row))
        attempt["selected_provider_id"] = attempt["selected_provider_id"] or _find_nested_field(row, ("provider_id", "selected_provider_id"))
        attempt["selected_model_name"] = attempt["selected_model_name"] or _find_nested_field(row, ("model_name", "selected_model_name"))
        failure_class = str(_find_nested_field(row, ("failure_class", "error_type", "failure_category")) or "").strip()
        failure_reason = str(_find_nested_field(row, ("failure_reason", "message", "error", "reason")) or "").strip()
        if failure_class and not attempt["failure_class"]:
            attempt["failure_class"] = failure_class
            attempt["failure_reason"] = failure_reason

    for row in imported_rows:
        if not _is_discord_origin(lane=str(row.get("source_lane") or ""), channel=str(row.get("source_channel") or "")):
            continue
        message_id = str(row.get("source_message_id") or "").strip()
        if not message_id:
            continue
        attempt = ensure_attempt(message_id)
        attempt["source_kind"] = str(row.get("source_kind") or attempt["source_kind"] or "openclaw")
        attempt["source_lane"] = str(row.get("source_lane") or attempt["source_lane"])
        attempt["source_channel"] = str(row.get("source_channel") or attempt["source_channel"])
        attempt["source_user"] = str(row.get("source_user") or attempt["source_user"])
        attempt["attempted_at"] = max(attempt["attempted_at"], _bridge_row_timestamp(row))
        attempt["mirror_stage"] = "imported"
        attempt["latest_result_kind"] = str(row.get("classification") or attempt["latest_result_kind"])

    for row in ingress_rows:
        if not _is_discord_origin(lane=str(row.get("source_lane") or ""), channel=str(row.get("source_channel") or "")):
            continue
        message_id = str(row.get("source_message_id") or "").strip()
        if not message_id:
            continue
        attempt = ensure_attempt(message_id)
        attempt["source_kind"] = str(row.get("source_kind") or attempt["source_kind"] or "openclaw")
        attempt["source_lane"] = str(row.get("source_lane") or attempt["source_lane"])
        attempt["source_channel"] = str(row.get("source_channel") or attempt["source_channel"])
        attempt["source_user"] = str(row.get("source_user") or attempt["source_user"])
        attempt["attempted_at"] = max(attempt["attempted_at"], _bridge_row_timestamp(row))
        attempt["mirror_stage"] = "reply_ingress"
        attempt["latest_result_kind"] = str(row.get("result_kind") or attempt["latest_result_kind"])
        apply_row = apply_by_id.get(str(row.get("result_ref_id") or ""))
        if apply_row:
            attempt["mirror_stage"] = "reply_applied"
            attempt["reply_applied"] = bool(apply_row.get("ok"))
            failure_class, failure_reason = _bridge_failure_from_apply(apply_row)
            attempt["selected_provider_id"] = attempt["selected_provider_id"] or _find_nested_field(
                apply_row,
                ("provider_id", "selected_provider_id"),
            )
            attempt["selected_model_name"] = attempt["selected_model_name"] or _find_nested_field(
                apply_row,
                ("model_name", "selected_model_name"),
            )
            if failure_class:
                attempt["failure_class"] = failure_class
                attempt["failure_reason"] = failure_reason

    for message_id, attempt in attempts.items():
        cycle = bridge_by_message.get(message_id)
        if not cycle:
            continue
        attempt["bridge_cycle_id"] = cycle.get("bridge_cycle_id")
        attempt["bridge_cycle_ok"] = cycle.get("ok")
        attempt["attempted_at"] = max(attempt["attempted_at"], _bridge_row_timestamp(cycle))
        if attempt["mirror_stage"] == "gateway_inbound":
            attempt["mirror_stage"] = "bridge_cycle"

    rows = sorted(attempts.values(), key=lambda row: row.get("attempted_at") or "", reverse=True)
    latest_attempt = rows[0] if rows else None
    latest_failure = next((row for row in rows if row.get("failure_class")), None)
    latest_successful_reply = next((row for row in rows if row.get("reply_applied") and not row.get("failure_class")), None)

    return {
        "summary_kind": "mirrored_openclaw_discord_activity",
        "authoritative_runtime": "openclaw",
        "mirrored_only": True,
        "note": "Read-only mirror of external OpenClaw Discord activity. Repo-native task/runtime records remain authoritative for Jarvis execution state.",
        "recent_discord_attempt_count": len(rows),
        "pending_gateway_import_count": sum(1 for row in gateway_rows if _is_discord_origin(lane=str(row.get("source_lane") or ""), channel=str(row.get("source_channel") or "")) and not row.get("imported_at")),
        "latest_attempt": latest_attempt,
        "latest_failure": latest_failure,
        "latest_successful_reply": latest_successful_reply,
        "recent_discord_attempts": rows[:10],
    }


def build_openclaw_discord_session_summary(*, root: Path) -> dict[str, Any]:
    return build_openclaw_discord_session_integrity_summary(repo_root=root)


def build_extension_lane_status_summary(
    *,
    shadowbroker_summary: dict[str, Any],
    world_ops_summary: dict[str, Any],
    autoresearch_summary: dict[str, Any],
    adaptation_lab_summary: dict[str, Any],
    optimizer_summary: dict[str, Any],
    hermes_summary: dict[str, Any],
    research_backend_summary: dict[str, Any],
    browser_action_summary: dict[str, Any],
    a2a_policy_summary: dict[str, Any],
    local_model_lane_proof_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def _row(lane: str, classification: str, reason: str) -> dict[str, Any]:
        return {"lane": lane, "classification": classification, "reason": reason}

    shadowbroker_row = _row(
        "shadowbroker",
        "live_and_usable" if shadowbroker_summary.get("configured") and shadowbroker_summary.get("healthy") else "implemented_but_blocked_by_external_runtime",
        (
            "ShadowBroker is configured and healthy."
            if shadowbroker_summary.get("configured") and shadowbroker_summary.get("healthy")
            else str(shadowbroker_summary.get("degraded_reason") or shadowbroker_summary.get("backend_status") or "ShadowBroker depends on external config/runtime.")
        ),
    )
    world_ops_row = _row(
        "world_ops",
        "deprecated_alias",
        "world_ops remains the compatibility aggregation layer; prefer ShadowBroker for the external OSINT sidecar path.",
    )
    latest_upstream_runtime = dict(autoresearch_summary.get("latest_upstream_runtime") or {})
    autoresearch_row = _row(
        "autoresearch_upstream_bridge",
        "live_and_usable" if str(latest_upstream_runtime.get("runtime_status") or "") == "completed" else "implemented_but_blocked_by_external_runtime",
        (
            "Autoresearch upstream runtime completed."
            if str(latest_upstream_runtime.get("runtime_status") or "") == "completed"
            else str(latest_upstream_runtime.get("details") or latest_upstream_runtime.get("runtime_status") or "Autoresearch depends on an external upstream runtime.")
        ),
    )
    proof_rows = {
        str(row.get("lane") or ""): row for row in list((local_model_lane_proof_summary or {}).get("rows") or [])
    }
    latest_adaptation = dict(adaptation_lab_summary.get("latest_result") or {})
    adaptation_proof = dict(proof_rows.get("adaptation_lab_unsloth") or {})
    adaptation_row = _row(
        "adaptation_lab_unsloth",
        "live_and_usable" if adaptation_proof.get("currently_live_on_this_machine") else "implemented_but_blocked_by_external_runtime",
        (
            "Unsloth-backed proof completed on this machine."
            if adaptation_proof.get("currently_live_on_this_machine")
            else str(
                adaptation_proof.get("latest_runtime_status")
                or latest_adaptation.get("runtime_status")
                or adaptation_lab_summary.get("runtime_status_counts")
                or "Adaptation lab depends on local Unsloth runtime availability."
            )
        ),
    )
    latest_optimizer_run = dict(optimizer_summary.get("latest_optimizer_run") or {})
    optimizer_proof = dict(proof_rows.get("optimizer_dspy") or {})
    optimizer_row = _row(
        "optimizer_dspy",
        "live_and_usable" if optimizer_proof.get("currently_live_on_this_machine") else "implemented_but_blocked_by_external_runtime",
        (
            "DSPy-backed proof completed on this machine."
            if optimizer_proof.get("currently_live_on_this_machine")
            else str(
                optimizer_proof.get("latest_runtime_status")
                or latest_optimizer_run.get("runtime_status")
                or optimizer_summary.get("optimizer_runtime_status_counts")
                or "Optimizer depends on DSPy runtime availability."
            )
        ),
    )
    latest_hermes = dict(hermes_summary.get("latest_hermes_result") or {})
    hermes_row = _row(
        "hermes_bridge",
        "live_and_usable" if str(latest_hermes.get("status") or "") == "completed" else "implemented_but_blocked_by_external_runtime",
        (
            "Hermes completed through the external bridge."
            if str(latest_hermes.get("status") or "") == "completed"
            else str(latest_hermes.get("error") or latest_hermes.get("failure_category") or "Hermes depends on an external runtime bridge.")
        ),
    )
    latest_backend_healthchecks = list(research_backend_summary.get("latest_backend_healthchecks") or [])
    latest_research_backend = latest_backend_healthchecks[0] if latest_backend_healthchecks else {}
    searxng_row = _row(
        "searxng",
        "live_and_usable" if int(research_backend_summary.get("healthy_research_backend_count") or 0) > 0 else "implemented_but_blocked_by_external_runtime",
        (
            "SearXNG backend healthcheck is green."
            if int(research_backend_summary.get("healthy_research_backend_count") or 0) > 0
            else str(latest_research_backend.get("details") or latest_research_backend.get("status") or "SearXNG runtime is not currently healthy.")
        ),
    )
    browser_row = _row(
        "browser_bridge",
        "scaffold_only",
        str((browser_action_summary.get("latest_result") or {}).get("outcome_summary") or "Browser bridge remains bounded/stubbed and is not a live external runtime lane."),
    )
    mission_control_row = _row(
        "mission_control_adapter",
        "scaffold_only",
        "No standalone mission control adapter/runtime is present in the repo.",
    )
    a2a_row = _row(
        "a2a",
        "scaffold_only",
        "A2A is currently a policy/validation surface only." if a2a_policy_summary.get("a2a_policy_present") else "A2A runtime surface is not present.",
    )
    rows = [
        shadowbroker_row,
        world_ops_row,
        autoresearch_row,
        adaptation_row,
        optimizer_row,
        hermes_row,
        searxng_row,
        browser_row,
        mission_control_row,
        a2a_row,
    ]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    return {
        "summary_kind": "extension_lane_status",
        "rows": rows,
        "classification_counts": counts,
    }


def build_local_model_lane_proof_summary(*, root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    live_count = 0
    for lane in ("adaptation_lab_unsloth", "optimizer_dspy"):
        latest = dict(latest_lane_activation_result(lane, root=root) or {})
        current_status = str(latest.get("status") or "not_run")
        current_runtime_status = str(latest.get("runtime_status") or "not_run")
        currently_live = bool(latest.get("configured")) and bool(latest.get("healthy")) and current_status == "completed"
        status_counts[current_status] = status_counts.get(current_status, 0) + 1
        if currently_live:
            live_count += 1
        rows.append(
            {
                "lane": lane,
                "latest_activation_status": current_status,
                "latest_runtime_status": current_runtime_status,
                "latest_activation_timestamp": str(latest.get("completed_at") or latest.get("started_at") or ""),
                "currently_live_on_this_machine": currently_live,
                "operator_action_required": str(latest.get("operator_action_required") or ""),
                "command_or_endpoint": str(latest.get("command_or_endpoint") or ""),
                "evidence_refs": dict(latest.get("evidence_refs") or {}),
                "error": str(latest.get("error") or ""),
                "details": str(latest.get("details") or ""),
            }
        )
    return {
        "summary_kind": "local_model_lane_proof",
        "rows": rows,
        "status_counts": status_counts,
        "live_proof_count": live_count,
    }


def _task_summary(task: TaskRecord, events_by_task: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    control_state = get_effective_control_state(
        root=ROOT,
        task_id=task.task_id,
        subsystem=task.execution_backend if task.execution_backend != "unassigned" else task.source_lane,
    )
    return {
        "task_id": task.task_id,
        "summary": task.normalized_request,
        "status": task.status,
        "lifecycle_state": task.lifecycle_state,
        "priority": task.priority,
        "task_type": task.task_type,
        "execution_backend": task.execution_backend,
        "backend_assignment_id": task.backend_assignment_id,
        "review_required": task.review_required,
        "approval_required": task.approval_required,
        "autonomy_mode": task.autonomy_mode,
        "speculative_downstream": task.speculative_downstream,
        "task_envelope": dict(task.task_envelope),
        "promoted_artifact_id": task.promoted_artifact_id,
        "candidate_artifact_ids": list(task.candidate_artifact_ids),
        "demoted_artifact_ids": list(task.demoted_artifact_ids),
        "revoked_artifact_ids": list(task.revoked_artifact_ids),
        "impacted_output_ids": list(task.impacted_output_ids),
        "blocked_dependency_refs": list(task.blocked_dependency_refs),
        "dependency_block_reason": task.dependency_block_reason,
        "publish_readiness_status": task.publish_readiness_status,
        "publish_readiness_reason": task.publish_readiness_reason,
        "reason": _latest_reason(task, events_by_task),
        "control_status": control_state["effective_status"],
        "control_run_state": control_state["effective_run_state"],
        "control_safety_mode": control_state["effective_safety_mode"],
        "control_reasons": control_state["active_reasons"],
        "updated_at": task.updated_at,
    }


def _artifact_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": artifact.get("artifact_id"),
        "task_id": artifact.get("task_id"),
        "title": artifact.get("title"),
        "artifact_type": artifact.get("artifact_type"),
        "lifecycle_state": artifact.get("lifecycle_state"),
        "producer_kind": artifact.get("producer_kind"),
        "execution_backend": artifact.get("execution_backend"),
        "superseded_by_artifact_id": artifact.get("superseded_by_artifact_id"),
        "home_runtime_workspace": artifact.get("home_runtime_workspace"),
        "target_workspace_id": artifact.get("target_workspace_id"),
        "allowed_workspace_ids": artifact.get("allowed_workspace_ids", []),
        "touched_workspace_ids": artifact.get("touched_workspace_ids", []),
        "downstream_impacted_output_ids": artifact.get("downstream_impacted_output_ids", []),
        "revoked_at": artifact.get("revoked_at"),
        "revocation_reason": artifact.get("revocation_reason", ""),
        "updated_at": artifact.get("updated_at"),
    }


def _output_summary(output: dict[str, Any]) -> dict[str, Any]:
    return {
        "output_id": output.get("output_id"),
        "task_id": output.get("task_id"),
        "artifact_id": output.get("artifact_id"),
        "title": output.get("title"),
        "status": output.get("status", OutputStatus.PUBLISHED.value),
        "superseded_by_artifact_id": output.get("superseded_by_artifact_id"),
        "home_runtime_workspace": output.get("home_runtime_workspace"),
        "target_workspace_id": output.get("target_workspace_id"),
        "allowed_workspace_ids": output.get("allowed_workspace_ids", []),
        "touched_workspace_ids": output.get("touched_workspace_ids", []),
        "impacted_by_artifact_ids": output.get("impacted_by_artifact_ids", []),
        "revocation_reason": output.get("revocation_reason", ""),
        "published_at": output.get("published_at"),
    }


def build_status(root: Path) -> dict[str, Any]:
    tasks = sorted(_load_tasks(root), key=_sort_key, reverse=True)
    events_by_task = _load_events_by_task(root)
    task_rows = []
    for task in tasks:
        control_state = get_effective_control_state(
            root=root,
            task_id=task.task_id,
            subsystem=task.execution_backend if task.execution_backend != "unassigned" else task.source_lane,
        )
        row = {
            "task_id": task.task_id,
            "summary": task.normalized_request,
            "status": task.status,
            "lifecycle_state": task.lifecycle_state,
            "priority": task.priority,
            "task_type": task.task_type,
            "execution_backend": task.execution_backend,
            "backend_assignment_id": task.backend_assignment_id,
            "review_required": task.review_required,
            "approval_required": task.approval_required,
            "autonomy_mode": task.autonomy_mode,
            "speculative_downstream": task.speculative_downstream,
            "task_envelope": dict(task.task_envelope),
            "promoted_artifact_id": task.promoted_artifact_id,
            "candidate_artifact_ids": list(task.candidate_artifact_ids),
            "demoted_artifact_ids": list(task.demoted_artifact_ids),
            "revoked_artifact_ids": list(task.revoked_artifact_ids),
            "impacted_output_ids": list(task.impacted_output_ids),
            "blocked_dependency_refs": list(task.blocked_dependency_refs),
            "dependency_block_reason": task.dependency_block_reason,
            "publish_readiness_status": task.publish_readiness_status,
            "publish_readiness_reason": task.publish_readiness_reason,
            "home_runtime_workspace": task.home_runtime_workspace,
            "target_workspace_id": task.target_workspace_id,
            "allowed_workspace_ids": list(task.allowed_workspace_ids),
            "touched_workspace_ids": list(task.touched_workspace_ids),
            "reason": _latest_reason(task, events_by_task),
            "control_status": control_state["effective_status"],
            "control_run_state": control_state["effective_run_state"],
            "control_safety_mode": control_state["effective_safety_mode"],
            "control_reasons": control_state["active_reasons"],
            "updated_at": task.updated_at,
        }
        task_rows.append(row)

    artifacts = _load_jsons(root / "state" / "artifacts")
    outputs = _load_jsons(root / "workspace" / "out")
    reviews = _load_jsons(root / "state" / "reviews")
    approvals = _load_jsons(root / "state" / "approvals")
    memory_candidates = _load_jsons(root / "state" / "memory_candidates")
    memory_retrievals = _load_jsons(root / "state" / "memory_retrievals")
    memory_validations = _load_jsons(root / "state" / "memory_validations")
    memory_promotion_decisions = _load_jsons(root / "state" / "memory_promotion_decisions")
    memory_rejection_decisions = _load_jsons(root / "state" / "memory_rejection_decisions")
    memory_revocation_decisions = _load_jsons(root / "state" / "memory_revocation_decisions")
    operator_action_executions = _load_jsons(root / "state" / "operator_action_executions")
    operator_queue_runs = _load_jsons(root / "state" / "operator_queue_runs")
    operator_bulk_runs = _load_jsons(root / "state" / "operator_bulk_runs")
    operator_task_interventions = _load_jsons(root / "state" / "operator_task_interventions")
    operator_safe_autofix_runs = _load_jsons(root / "state" / "operator_safe_autofix_runs")
    operator_reply_plans = _load_jsons(root / "state" / "operator_reply_plans")
    operator_reply_applies = _load_jsons(root / "state" / "operator_reply_applies")
    operator_reply_ingress = _load_jsons(root / "state" / "operator_reply_ingress")
    operator_reply_ingress_results = _load_jsons(root / "state" / "operator_reply_ingress_results")
    operator_reply_ingress_runs = _load_jsons(root / "state" / "operator_reply_ingress_runs")
    operator_reply_transport_cycles = _load_jsons(root / "state" / "operator_reply_transport_cycles")
    operator_reply_transport_replay_plans = _load_jsons(root / "state" / "operator_reply_transport_replay_plans")
    operator_reply_transport_replays = _load_jsons(root / "state" / "operator_reply_transport_replays")
    operator_outbound_packets = _load_jsons(root / "state" / "operator_outbound_packets")
    operator_imported_reply_messages = _load_jsons(root / "state" / "operator_imported_reply_messages")
    operator_gateway_inbound_messages = _load_jsons(root / "state" / "operator_gateway_inbound_messages")
    operator_bridge_cycles = _load_jsons(root / "state" / "operator_bridge_cycles")
    operator_bridge_replay_plans = _load_jsons(root / "state" / "operator_bridge_replay_plans")
    operator_bridge_replays = _load_jsons(root / "state" / "operator_bridge_replays")
    operator_doctor_reports = _load_jsons(root / "state" / "operator_doctor_reports")
    operator_remediation_plans = _load_jsons(root / "state" / "operator_remediation_plans")
    operator_remediation_runs = _load_jsons(root / "state" / "operator_remediation_runs")
    operator_remediation_step_runs = _load_jsons(root / "state" / "operator_remediation_step_runs")
    operator_recovery_cycles = _load_jsons(root / "state" / "operator_recovery_cycles")
    operator_control_plane_checkpoints = _load_jsons(root / "state" / "operator_control_plane_checkpoints")
    operator_incident_reports = _load_jsons(root / "state" / "operator_incident_reports")
    operator_incident_snapshots = _load_jsons(root / "state" / "operator_incident_snapshots")
    model_registry_entries = _load_jsons(root / "state" / "model_registry_entries")
    capability_profiles = _load_jsons(root / "state" / "capability_profiles")
    routing_policies = _load_jsons(root / "state" / "routing_policies")
    routing_overrides = _load_jsons(root / "state" / "routing_overrides")
    routing_requests = _load_jsons(root / "state" / "routing_requests")
    routing_decisions = _load_jsons(root / "state" / "routing_decisions")
    provider_adapter_results = _load_jsons(root / "state" / "provider_adapter_results")
    backend_assignments = _load_jsons(root / "state" / "backend_assignments")
    backend_execution_requests = _load_jsons(root / "state" / "backend_execution_requests")
    backend_execution_results = _load_jsons(root / "state" / "backend_execution_results")
    degradation_events = _load_jsons(root / "state" / "degradation_events")
    candidate_records = _load_jsons(root / "state" / "candidate_records")
    candidate_validations = _load_jsons(root / "state" / "candidate_validations")
    promotion_decisions = _load_jsons(root / "state" / "promotion_decisions")
    rejection_decisions = _load_jsons(root / "state" / "rejection_decisions")
    candidate_revocations = _load_jsons(root / "state" / "candidate_revocations")
    task_provenance = _load_jsons(root / "state" / "task_provenance")
    artifact_provenance = _load_jsons(root / "state" / "artifact_provenance")
    routing_provenance = _load_jsons(root / "state" / "routing_provenance")
    decision_provenance = _load_jsons(root / "state" / "decision_provenance")
    publish_provenance = _load_jsons(root / "state" / "publish_provenance")
    rollback_provenance = _load_jsons(root / "state" / "rollback_provenance")
    memory_provenance = _load_jsons(root / "state" / "memory_provenance")
    replay_plans = _load_jsons(root / "state" / "replay_plans")
    replay_executions = _load_jsons(root / "state" / "replay_executions")
    replay_results = _load_jsons(root / "state" / "replay_results")
    modality_contracts = _load_jsons(root / "state" / "modality_contracts")
    output_dependencies = _load_jsons(root / "state" / "output_dependencies")
    rollback_plans = _load_jsons(root / "state" / "rollback_plans")
    rollback_executions = _load_jsons(root / "state" / "rollback_executions")
    revocation_impacts = _load_jsons(root / "state" / "revocation_impacts")
    approval_sessions = _load_jsons(root / "state" / "approval_sessions")
    approval_decision_contexts = _load_jsons(root / "state" / "approval_decision_contexts")
    approval_resume_tokens = _load_jsons(root / "state" / "approval_resume_tokens")
    subsystem_contracts = _load_jsons(root / "state" / "subsystem_contracts")
    eval_profiles = _load_jsons(root / "state" / "eval_profiles")
    strategy_diversity_maps = _load_jsons(root / "state" / "strategy_diversity_maps")
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
    control_records = [record.to_dict() for record in list_control_records(root=root)]
    control_events = [record.to_dict() for record in list_control_events(root=root)]
    blocked_control_actions = [record.to_dict() for record in list_blocked_actions(root=root)]
    routing_summary = build_model_registry_summary(root)
    agent_roster_summary = build_agent_roster_summary(root=root)
    backend_assignment_summary = build_backend_assignment_summary(root=root)
    candidate_promotion_summary = build_candidate_summary(root)
    from runtime.memory.governance import build_memory_governance_summary

    memory_discipline_summary = build_memory_governance_summary(root=root)
    promotion_governance_summary = build_promotion_governance_summary(root=root)
    rollback_summary = build_rollback_summary(root)
    provenance_summary = build_provenance_summary(root)
    from runtime.core.replay_store import build_replay_summary

    replay_summary = build_replay_summary(root)
    from runtime.evals.trace_store import build_eval_outcome_summary

    eval_outcome_summary = build_eval_outcome_summary(root=root)
    multimodal_summary = build_modality_summary(root)
    execution_contract_summary = build_execution_contract_summary(root)
    token_budget_summary = build_token_budget_summary(root)
    degradation_summary = build_degradation_summary(root)
    eval_profile_summary = build_eval_profile_summary(root=root)
    browser_control_allowlist_summary = build_browser_control_allowlist_summary(root=root)
    browser_action_summary = build_browser_action_summary(root=root)
    voice_session_summary = build_voice_session_summary(root=root)
    heartbeat_summary = build_heartbeat_report_summary(root=root)
    from runtime.integrations.hermes_adapter import build_hermes_summary

    hermes_summary = build_hermes_summary(root=root)
    from runtime.integrations.autoresearch_adapter import build_autoresearch_summary

    autoresearch_summary = build_autoresearch_summary(root=root)
    approval_session_summary = build_approval_session_summary(root)
    subsystem_contract_summary = build_subsystem_contract_summary(root)
    trajectory_summary = build_trajectory_summary(root=root)
    operator_profile_summary = build_operator_profile_summary(root=root)
    security_validation_summary = build_security_validation_summary(root=root)
    prompt_caching_policy_summary = build_prompt_caching_policy_summary(root=root)
    mcp_policy_summary = build_mcp_policy_summary(root=root)
    plugin_policy_summary = build_plugin_policy_summary(root=root)
    a2a_policy_summary = build_a2a_policy_summary(root=root)
    voice_route_capability_summary = build_voice_route_capability_summary()
    voice_route_safety_summary = build_voice_route_safety_summary()
    notification_summary = build_notification_summary(root=root)
    policy_surface_summary = build_policy_surface_summary(
        security_validation_summary=security_validation_summary,
        prompt_caching_policy_summary=prompt_caching_policy_summary,
        mcp_policy_summary=mcp_policy_summary,
        plugin_policy_summary=plugin_policy_summary,
        a2a_policy_summary=a2a_policy_summary,
        notification_summary=notification_summary,
        voice_route_capability_summary=voice_route_capability_summary,
        voice_route_safety_summary=voice_route_safety_summary,
    )
    control_summary = build_control_summary(root=root)
    workspace_registry_summary = summarize_workspace_registry(root=root, tasks=task_rows, artifacts=artifacts, outputs=outputs)
    world_ops_summary = build_world_ops_summary(root=root)
    shadowbroker_summary = summarize_shadowbroker_backend(root=root)
    adaptation_lab_summary = summarize_adaptation_lab(root=root)
    optimizer_summary = summarize_optimizer_lane(root=root)
    local_model_lane_proof_summary = build_local_model_lane_proof_summary(root=root)
    discord_live_ops_summary = build_discord_live_ops_summary(
        root=root,
        tasks=tasks,
        routing_summary=routing_summary,
        backend_execution_results=backend_execution_results,
        degradation_events=degradation_events,
        blocked_actions=blocked_control_actions,
    )
    openclaw_discord_bridge_summary = build_openclaw_discord_bridge_summary(
        root=root,
        gateway_inbound_messages=operator_gateway_inbound_messages,
        imported_reply_messages=operator_imported_reply_messages,
        reply_ingress=operator_reply_ingress,
        reply_applies=operator_reply_applies,
        bridge_cycles=operator_bridge_cycles,
    )
    openclaw_discord_session_summary = build_openclaw_discord_session_summary(root=root)
    routing_control_plane_summary = build_routing_control_plane_summary(
        routing_summary=routing_summary,
        degradation_summary=degradation_summary,
        heartbeat_summary=heartbeat_summary,
    )
    extension_lane_status_summary = build_extension_lane_status_summary(
        shadowbroker_summary=shadowbroker_summary,
        world_ops_summary=world_ops_summary,
        autoresearch_summary=autoresearch_summary,
        adaptation_lab_summary=adaptation_lab_summary,
        optimizer_summary=optimizer_summary,
        hermes_summary=hermes_summary,
        research_backend_summary=build_research_backend_summary(root=root),
        browser_action_summary=browser_action_summary,
        a2a_policy_summary=a2a_policy_summary,
        local_model_lane_proof_summary=local_model_lane_proof_summary,
    )
    lane_activation_summary = summarize_lane_activation(
        root=root,
        extension_lane_status_summary=extension_lane_status_summary,
    )
    current_action_pack_path = root / "state" / "logs" / "operator_checkpoint_action_pack.json"
    current_action_pack = {"path": str(current_action_pack_path), "status": "malformed", "fresh": False}
    if current_action_pack_path.exists():
        try:
            current_action_pack = {"path": str(current_action_pack_path), **classify_action_pack(json.loads(current_action_pack_path.read_text(encoding="utf-8")))}
        except Exception as exc:
            current_action_pack = {"path": str(current_action_pack_path), "status": "malformed", "reason": str(exc), "fresh": False}
    paused_controls = [row for row in control_records if row.get("run_state") == "paused"]
    stopped_controls = [row for row in control_records if row.get("run_state") == "stopped"]
    degraded_controls = [row for row in control_records if row.get("safety_mode") == "degraded"]
    revoked_controls = [row for row in control_records if row.get("safety_mode") == "revoked"]
    global_control = get_effective_control_state(root=root)
    effective_run_state = "active"
    effective_safety_mode = "normal"
    if stopped_controls:
        effective_run_state = "stopped"
    elif paused_controls:
        effective_run_state = "paused"
    if revoked_controls:
        effective_safety_mode = "revoked"
    elif degraded_controls:
        effective_safety_mode = "degraded"
    effective_status = "active"
    if effective_run_state == "stopped":
        effective_status = "stopped"
    elif effective_run_state == "paused":
        effective_status = "paused"
    elif effective_safety_mode == "revoked":
        effective_status = "revoked"
    elif effective_safety_mode == "degraded":
        effective_status = "degraded"
    effective_control = {
        "effective_status": effective_status,
        "effective_run_state": effective_run_state,
        "effective_safety_mode": effective_safety_mode,
        "records": global_control.get("records", []),
        "active_reasons": global_control.get("active_reasons", []),
        "has_active_controls": bool(global_control.get("has_active_controls")),
        "emergency_flags": dict(global_control.get("emergency_flags", {})),
        "disabled_provider_ids": list(global_control.get("disabled_provider_ids", [])),
        "disabled_execution_backends": list(global_control.get("disabled_execution_backends", [])),
    }

    queued_now = [row for row in task_rows if row["status"] == TaskStatus.QUEUED.value]
    running_now = [row for row in task_rows if row["status"] == TaskStatus.RUNNING.value]
    blocked = [row for row in task_rows if row["status"] == TaskStatus.BLOCKED.value]
    waiting_review = [row for row in task_rows if row["status"] == TaskStatus.WAITING_REVIEW.value]
    waiting_approval = [row for row in task_rows if row["status"] == TaskStatus.WAITING_APPROVAL.value]
    ready_to_ship = [row for row in task_rows if row["status"] == TaskStatus.READY_TO_SHIP.value]
    shipped = [row for row in task_rows if row["status"] == TaskStatus.SHIPPED.value]
    finished_recently = [
        row
        for row in task_rows
        if row["status"] in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
            TaskStatus.ARCHIVED.value,
        }
    ][:10]

    candidate_artifacts = [
        _artifact_summary(row)
        for row in artifacts
        if row.get("lifecycle_state") == RecordLifecycleState.CANDIDATE.value
    ]
    impacted_artifacts = [
        _artifact_summary(row)
        for row in artifacts
        if row.get("lifecycle_state") in {RecordLifecycleState.DEMOTED.value, RecordLifecycleState.SUPERSEDED.value}
    ]
    revoked_artifacts = [
        _artifact_summary(row)
        for row in artifacts
        if row.get("revoked_at")
    ]
    impacted_outputs = [
        _output_summary(row)
        for row in outputs
        if row.get("status") == OutputStatus.IMPACTED.value
    ]
    revoked_outputs = [
        _output_summary(row)
        for row in outputs
        if row.get("status") == OutputStatus.REVOKED.value
    ]

    pending_reviews = [row for row in reviews if row.get("status") == "pending"]
    pending_approvals = [row for row in approvals if row.get("status") == "pending"]
    promoted_memories = [row for row in memory_candidates if row.get("lifecycle_state") == RecordLifecycleState.PROMOTED.value]
    candidate_memories = [row for row in memory_candidates if row.get("lifecycle_state") == RecordLifecycleState.CANDIDATE.value]
    contradicted_memories = [
        row
        for row in memory_candidates
        if row.get("contradiction_status") == "contradicted" or row.get("superseded_by_memory_candidate_id")
    ]

    counts = {
        "total_tasks": len(task_rows),
        "queued": len(queued_now),
        "running": len(running_now),
        "blocked": len(blocked),
        "waiting_review": len(waiting_review),
        "waiting_approval": len(waiting_approval),
        "ready_to_ship": len(ready_to_ship),
        "shipped": len(shipped),
        "finished_recently": len(finished_recently),
        "candidate_artifacts": len(candidate_artifacts),
        "impacted_artifacts": len(impacted_artifacts),
        "revoked_artifacts": len(revoked_artifacts),
        "impacted_outputs": len(impacted_outputs),
        "revoked_outputs": len(revoked_outputs),
        "pending_reviews": len(pending_reviews),
        "pending_approvals": len(pending_approvals),
        "promoted_memories": len(promoted_memories),
        "candidate_memories": len(candidate_memories),
        "contradicted_memories": len(contradicted_memories),
        "memory_retrievals": len(memory_retrievals),
        "memory_validations": len(memory_validations),
        "memory_promotion_decisions": len(memory_promotion_decisions),
        "memory_rejection_decisions": len(memory_rejection_decisions),
        "memory_revocation_decisions": len(memory_revocation_decisions),
        "controls": len(control_records),
        "control_events": len(control_events),
        "control_blocked_actions": len(blocked_control_actions),
        "paused_controls": len(paused_controls),
        "stopped_controls": len(stopped_controls),
        "degraded_controls": len(degraded_controls),
        "revoked_controls": len(revoked_controls),
        "operator_action_executions": len(operator_action_executions),
        "operator_queue_runs": len(operator_queue_runs),
        "operator_bulk_runs": len(operator_bulk_runs),
        "operator_task_interventions": len(operator_task_interventions),
        "operator_safe_autofix_runs": len(operator_safe_autofix_runs),
        "operator_reply_plans": len(operator_reply_plans),
        "operator_reply_applies": len(operator_reply_applies),
        "operator_reply_ingress": len(operator_reply_ingress),
        "operator_reply_ingress_results": len(operator_reply_ingress_results),
        "operator_reply_ingress_runs": len(operator_reply_ingress_runs),
        "operator_reply_transport_cycles": len(operator_reply_transport_cycles),
        "operator_reply_transport_replay_plans": len(operator_reply_transport_replay_plans),
        "operator_reply_transport_replays": len(operator_reply_transport_replays),
        "operator_outbound_packets": len(operator_outbound_packets),
        "operator_imported_reply_messages": len(operator_imported_reply_messages),
        "operator_bridge_cycles": len(operator_bridge_cycles),
        "operator_bridge_replay_plans": len(operator_bridge_replay_plans),
        "operator_bridge_replays": len(operator_bridge_replays),
        "operator_doctor_reports": len(operator_doctor_reports),
        "operator_remediation_plans": len(operator_remediation_plans),
        "operator_remediation_runs": len(operator_remediation_runs),
        "operator_remediation_step_runs": len(operator_remediation_step_runs),
        "operator_recovery_cycles": len(operator_recovery_cycles),
        "operator_control_plane_checkpoints": len(operator_control_plane_checkpoints),
        "operator_incident_reports": len(operator_incident_reports),
        "operator_incident_snapshots": len(operator_incident_snapshots),
        "model_registry_entries": len(model_registry_entries),
        "capability_profiles": len(capability_profiles),
        "routing_policies": len(routing_policies),
        "routing_overrides": len(routing_overrides),
        "routing_requests": len(routing_requests),
        "routing_decisions": len(routing_decisions),
        "provider_adapter_results": len(provider_adapter_results),
        "backend_assignments": len(backend_assignments),
        "backend_execution_requests": len(backend_execution_requests),
        "backend_execution_results": len(backend_execution_results),
        "degradation_policies": degradation_summary.get("degradation_policy_count", 0),
        "degradation_events": degradation_summary.get("degradation_event_count", 0),
        "candidate_records": len(candidate_records),
        "candidate_validations": len(candidate_validations),
        "promotion_decisions": len(promotion_decisions),
        "rejection_decisions": len(rejection_decisions),
            "candidate_revocations": len(candidate_revocations),
            "task_provenance": len(task_provenance),
            "artifact_provenance": len(artifact_provenance),
            "routing_provenance": len(routing_provenance),
            "decision_provenance": len(decision_provenance),
            "publish_provenance": len(publish_provenance),
            "rollback_provenance": len(rollback_provenance),
            "memory_provenance": len(memory_provenance),
            "replay_plans": len(replay_plans),
            "replay_executions": len(replay_executions),
            "replay_results": len(replay_results),
            "modality_contracts": len(modality_contracts),
            "output_dependencies": len(output_dependencies),
        "rollback_plans": len(rollback_plans),
        "rollback_executions": len(rollback_executions),
        "revocation_impacts": len(revocation_impacts),
        "approval_sessions": len(approval_sessions),
        "approval_decision_contexts": len(approval_decision_contexts),
        "approval_resume_tokens": len(approval_resume_tokens),
        "subsystem_contracts": len(subsystem_contracts),
        "eval_profiles": len(eval_profiles),
        "strategy_diversity_maps": len(strategy_diversity_maps),
    }
    triage_summary = build_triage_data(root, limit=10, allow_pack_rebuild=False)
    decision_inbox = build_decision_inbox_data(root, limit=10, allow_pack_rebuild=False)
    decision_shortlist = build_decision_shortlist_data(root, limit=5, allow_inbox_rebuild=False)
    command_center_path = root / "state" / "logs" / "operator_command_center.json"
    decision_manifest_path = root / "state" / "logs" / "operator_decision_manifest.json"
    compare_packs_path = root / "state" / "logs" / "operator_compare_packs_latest.json"
    compare_triage_path = root / "state" / "logs" / "operator_compare_triage_latest.json"
    compare_inbox_path = root / "state" / "logs" / "operator_compare_inbox_latest.json"
    compare_reply_transport_path = root / "state" / "logs" / "operator_compare_reply_transport_cycles_latest.json"
    compare_bridge_cycles_path = root / "state" / "logs" / "operator_compare_bridge_cycles_latest.json"
    compare_control_plane_checkpoints_path = root / "state" / "logs" / "operator_compare_control_plane_checkpoints_latest.json"
    outbound_prompt_path = root / "state" / "logs" / "operator_outbound_prompt_latest.json"
    outbound_packet_path = root / "state" / "logs" / "operator_outbound_packet_latest.json"
    reply_ack_path = root / "state" / "logs" / "operator_reply_ack_latest.json"
    current_command_center = None
    current_decision_manifest = None
    latest_compare_packs = None
    latest_compare_triage = None
    latest_compare_inbox = None
    current_outbound_prompt = None
    current_outbound_packet = None
    current_reply_ack = None
    latest_compare_reply_transport = None
    latest_compare_bridge_cycles = None
    latest_compare_control_plane_checkpoints = None
    if command_center_path.exists():
        try:
            current_command_center = json.loads(command_center_path.read_text(encoding="utf-8"))
        except Exception:
            current_command_center = None
    if decision_manifest_path.exists():
        try:
            current_decision_manifest = json.loads(decision_manifest_path.read_text(encoding="utf-8"))
        except Exception:
            current_decision_manifest = None
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
            current_outbound_prompt = json.loads(outbound_prompt_path.read_text(encoding="utf-8"))
        except Exception:
            current_outbound_prompt = None
    if outbound_packet_path.exists():
        try:
            current_outbound_packet = json.loads(outbound_packet_path.read_text(encoding="utf-8"))
        except Exception:
            current_outbound_packet = None
    if reply_ack_path.exists():
        try:
            current_reply_ack = json.loads(reply_ack_path.read_text(encoding="utf-8"))
        except Exception:
            current_reply_ack = None
    latest_cycle_record = load_reply_transport_cycle(root, operator_reply_transport_cycles[-1]["transport_cycle_id"]) if operator_reply_transport_cycles else None
    latest_cycle_replay_safety = (
        classify_reply_transport_replay_safety(root, cycle=latest_cycle_record, live_apply_requested=False) if latest_cycle_record else None
    )
    latest_bridge_cycle_record = load_bridge_cycle(root, operator_bridge_cycles[-1]["bridge_cycle_id"]) if operator_bridge_cycles else None
    latest_bridge_replay_safety = (
        classify_bridge_replay_safety(root, cycle=latest_bridge_cycle_record, live_apply_requested=False) if latest_bridge_cycle_record else None
    )

    if control_records:
        next_move = "Inspect active control-state before resuming apply, promotion, or publish work."
    elif blocked:
        next_move = "Clear blocked tasks and inspect the linked lifecycle reasons first."
    elif waiting_review:
        next_move = "Review tasks waiting on reviewer verdicts."
    elif waiting_approval:
        next_move = "Review approval-gated tasks first."
    elif impacted_outputs or revoked_artifacts:
        next_move = "Inspect impacted or revoked outputs before shipping any dependent work."
    elif ready_to_ship:
        next_move = "Ship or publish the ready-to-ship tasks with promoted artifacts."
    elif running_now:
        next_move = "Let current in-progress work continue or inspect the top active task."
    elif queued_now:
        next_move = "Start the highest-priority queued task or inspect queued work."
    else:
        next_move = "No active work is currently queued or running."

    autonomy_mode_counts: dict[str, int] = {}
    task_envelope_task_count = 0
    speculative_downstream_count = 0
    for task in tasks:
        autonomy_mode_counts[task.autonomy_mode] = autonomy_mode_counts.get(task.autonomy_mode, 0) + 1
        if task.task_envelope:
            task_envelope_task_count += 1
        if task.speculative_downstream:
            speculative_downstream_count += 1

    return {
        "queued_now": queued_now,
        "running_now": running_now,
        "blocked": blocked,
        "waiting_review": waiting_review,
        "waiting_approval": waiting_approval,
        "ready_to_ship": ready_to_ship,
        "shipped": shipped,
        "finished_recently": finished_recently,
        "candidate_artifacts": candidate_artifacts,
        "routing_summary": routing_summary,
        "agent_roster_summary": agent_roster_summary,
        "routing_control_plane_summary": routing_control_plane_summary,
        "extension_lane_status_summary": extension_lane_status_summary,
        "lane_activation_summary": lane_activation_summary,
        "local_model_lane_proof_summary": local_model_lane_proof_summary,
        "workspace_registry_summary": workspace_registry_summary,
        "world_ops_summary": world_ops_summary,
        "shadowbroker_summary": shadowbroker_summary,
        "adaptation_lab_summary": adaptation_lab_summary,
        "optimizer_summary": optimizer_summary,
        "discord_live_ops_summary": discord_live_ops_summary,
        "openclaw_discord_bridge_summary": openclaw_discord_bridge_summary,
        "openclaw_discord_session_summary": openclaw_discord_session_summary,
        "backend_assignment_summary": backend_assignment_summary,
        "execution_contract_summary": execution_contract_summary,
        "token_budget_summary": token_budget_summary,
        "degradation_summary": degradation_summary,
        "heartbeat_summary": heartbeat_summary,
        "hermes_summary": hermes_summary,
        "autoresearch_summary": autoresearch_summary,
        "eval_profile_summary": eval_profile_summary,
        "browser_control_allowlist_summary": browser_control_allowlist_summary,
        "browser_action_summary": browser_action_summary,
        "voice_session_summary": voice_session_summary,
        "task_envelope_summary": {
            "task_envelope_task_count": task_envelope_task_count,
            "autonomy_mode_counts": autonomy_mode_counts,
            "speculative_downstream_count": speculative_downstream_count,
            "blocked_dependency_task_count": len([task for task in tasks if task.blocked_dependency_refs]),
        },
        "candidate_promotion_summary": candidate_promotion_summary,
        "provenance_summary": provenance_summary,
        "replay_summary": replay_summary,
        "eval_outcome_summary": eval_outcome_summary,
        "multimodal_summary": multimodal_summary,
        "memory_discipline_summary": memory_discipline_summary,
        "promotion_governance_summary": promotion_governance_summary,
        "rollback_summary": rollback_summary,
        "approval_session_summary": approval_session_summary,
        "subsystem_contract_summary": subsystem_contract_summary,
        "trajectory_summary": trajectory_summary,
        "operator_profile_summary": operator_profile_summary,
        "security_validation_summary": security_validation_summary,
        "prompt_caching_policy_summary": prompt_caching_policy_summary,
        "mcp_policy_summary": mcp_policy_summary,
        "plugin_policy_summary": plugin_policy_summary,
        "a2a_policy_summary": a2a_policy_summary,
        "voice_route_capability_summary": voice_route_capability_summary,
        "voice_route_safety_summary": voice_route_safety_summary,
        "notification_summary": notification_summary,
        "policy_surface_summary": policy_surface_summary,
        "impacted_artifacts": impacted_artifacts,
        "revoked_artifacts": revoked_artifacts,
        "impacted_outputs": impacted_outputs,
        "revoked_outputs": revoked_outputs,
        "control_state": {
            "effective": effective_control,
            "records": control_records,
            "events": control_events,
            "latest_blocked_action": control_summary.get("latest_blocked_action"),
            "paused": paused_controls,
            "stopped": stopped_controls,
            "degraded": degraded_controls,
            "revoked": revoked_controls,
        },
        "operator_control_plane": {
            "recent_execution_count": len(operator_action_executions),
            "recent_queue_run_count": len(operator_queue_runs),
            "recent_bulk_run_count": len(operator_bulk_runs),
            "recent_task_intervention_count": len(operator_task_interventions),
            "recent_safe_autofix_run_count": len(operator_safe_autofix_runs),
            "recent_reply_plan_count": len(operator_reply_plans),
            "recent_reply_apply_count": len(operator_reply_applies),
            "recent_reply_ingress_count": len(operator_reply_ingress),
            "recent_reply_ingress_result_count": len(operator_reply_ingress_results),
            "recent_reply_ingress_run_count": len(operator_reply_ingress_runs),
            "recent_reply_transport_cycle_count": len(operator_reply_transport_cycles),
            "recent_reply_transport_replay_plan_count": len(operator_reply_transport_replay_plans),
            "recent_reply_transport_replay_count": len(operator_reply_transport_replays),
            "recent_outbound_packet_count": len(operator_outbound_packets),
            "recent_imported_reply_message_count": len(operator_imported_reply_messages),
            "recent_bridge_cycle_count": len(operator_bridge_cycles),
            "recent_bridge_replay_plan_count": len(operator_bridge_replay_plans),
            "recent_bridge_replay_count": len(operator_bridge_replays),
            "recent_doctor_report_count": len(operator_doctor_reports),
            "recent_remediation_plan_count": len(operator_remediation_plans),
            "recent_remediation_run_count": len(operator_remediation_runs),
            "recent_remediation_step_run_count": len(operator_remediation_step_runs),
            "recent_recovery_cycle_count": len(operator_recovery_cycles),
            "recent_control_plane_checkpoint_count": len(operator_control_plane_checkpoints),
            "recent_incident_report_count": len(operator_incident_reports),
            "recent_incident_snapshot_count": len(operator_incident_snapshots),
            "latest_queue_run": operator_queue_runs[-1] if operator_queue_runs else None,
            "latest_bulk_run": operator_bulk_runs[-1] if operator_bulk_runs else None,
            "latest_task_intervention": operator_task_interventions[-1] if operator_task_interventions else None,
            "latest_safe_autofix_run": operator_safe_autofix_runs[-1] if operator_safe_autofix_runs else None,
            "latest_reply_plan": operator_reply_plans[-1] if operator_reply_plans else None,
            "latest_reply_apply": operator_reply_applies[-1] if operator_reply_applies else None,
            "latest_reply_ingress": operator_reply_ingress[-1] if operator_reply_ingress else None,
            "latest_reply_ingress_run": operator_reply_ingress_runs[-1] if operator_reply_ingress_runs else None,
            "latest_reply_transport_cycle": operator_reply_transport_cycles[-1] if operator_reply_transport_cycles else None,
            "latest_reply_transport_replay": operator_reply_transport_replays[-1] if operator_reply_transport_replays else None,
            "latest_outbound_packet": operator_outbound_packets[-1] if operator_outbound_packets else None,
            "latest_imported_reply_message": operator_imported_reply_messages[-1] if operator_imported_reply_messages else None,
            "latest_bridge_cycle": operator_bridge_cycles[-1] if operator_bridge_cycles else None,
            "latest_bridge_replay": operator_bridge_replays[-1] if operator_bridge_replays else None,
            "latest_doctor_report": operator_doctor_reports[-1] if operator_doctor_reports else None,
            "latest_remediation_plan": operator_remediation_plans[-1] if operator_remediation_plans else None,
            "latest_remediation_run": operator_remediation_runs[-1] if operator_remediation_runs else None,
            "latest_recovery_cycle": operator_recovery_cycles[-1] if operator_recovery_cycles else None,
            "recent_recovery_cycles": operator_recovery_cycles[-5:],
            "latest_control_plane_checkpoint": operator_control_plane_checkpoints[-1] if operator_control_plane_checkpoints else None,
            "recent_control_plane_checkpoints": operator_control_plane_checkpoints[-5:],
            "latest_incident_report": operator_incident_reports[-1] if operator_incident_reports else None,
            "recent_incident_reports": operator_incident_reports[-5:],
            "reply_transport_replay_summary": latest_cycle_replay_safety or {},
            "bridge_replay_summary": latest_bridge_replay_safety or {},
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
            "model_registry_summary": routing_summary,
            "agent_roster_summary": agent_roster_summary,
            "backend_assignment_summary": backend_assignment_summary,
            "candidate_promotion_summary": candidate_promotion_summary,
            "memory_discipline_summary": memory_discipline_summary,
            "promotion_governance_summary": promotion_governance_summary,
            "rollback_summary": rollback_summary,
            "approval_session_summary": approval_session_summary,
            "subsystem_contract_summary": subsystem_contract_summary,
            "trajectory_summary": trajectory_summary,
            "operator_profile_summary": operator_profile_summary,
            "eval_outcome_summary": eval_outcome_summary,
            "degradation_summary": degradation_summary,
            "heartbeat_summary": heartbeat_summary,
            "hermes_summary": hermes_summary,
            "autoresearch_summary": autoresearch_summary,
            "eval_profile_summary": eval_profile_summary,
            "browser_control_allowlist_summary": browser_control_allowlist_summary,
            "browser_action_summary": browser_action_summary,
            "voice_session_summary": voice_session_summary,
            "reply_ingress_summary": {
                "reply_ingest_ready": decision_inbox.get("reply_ready") and current_action_pack.get("status") == "valid",
                "reply_transport_ready": decision_inbox.get("reply_ready") and current_action_pack.get("status") == "valid",
                "ignored_count": sum(1 for row in operator_reply_ingress if row.get("result_kind") == "ignored_non_reply"),
                "invalid_count": sum(1 for row in operator_reply_ingress if row.get("result_kind") == "invalid_reply"),
                "blocked_count": sum(
                    1
                    for row in operator_reply_ingress
                    if row.get("result_kind") in {"missing_inbox", "stale_inbox", "pack_refresh_required", "blocked", "duplicate_message"}
                ),
                "applied_count": sum(1 for row in operator_reply_ingress if row.get("result_kind") == "applied"),
                "duplicate_count": sum(1 for row in operator_reply_ingress if row.get("result_kind") == "duplicate_message"),
                "pending_inbound_message_count": len(
                    [row for row in _load_jsons(root / "state" / "operator_reply_messages") if not row.get("processed_at")]
                ),
                "latest_source_metadata": {
                    "source_kind": (operator_reply_ingress[-1] if operator_reply_ingress else {}).get("source_kind"),
                    "source_channel": (operator_reply_ingress[-1] if operator_reply_ingress else {}).get("source_channel"),
                    "source_message_id": (operator_reply_ingress[-1] if operator_reply_ingress else {}).get("source_message_id"),
                    "source_user": (operator_reply_ingress[-1] if operator_reply_ingress else {}).get("source_user"),
                },
            },
            "current_outbound_prompt": {
                "generated_at": (current_outbound_prompt or {}).get("generated_at"),
                "pack_id": (current_outbound_prompt or {}).get("pack_id"),
                "pack_status": (current_outbound_prompt or {}).get("pack_status"),
                "reply_ready": (current_outbound_prompt or {}).get("reply_ready"),
                "warning": (current_outbound_prompt or {}).get("warning", ""),
                "top_items": (current_outbound_prompt or {}).get("top_items", [])[:5],
            },
            "current_outbound_packet": {
                "generated_at": (current_outbound_packet or {}).get("generated_at"),
                "pack_id": (current_outbound_packet or {}).get("pack_id"),
                "pack_status": (current_outbound_packet or {}).get("pack_status"),
                "reply_ready": (current_outbound_packet or {}).get("reply_ready"),
                "minimal_warning": (current_outbound_packet or {}).get("minimal_warning", ""),
                "top_items": (current_outbound_packet or {}).get("top_items", [])[:5],
            },
            "current_reply_ack": {
                "generated_at": (current_reply_ack or {}).get("generated_at"),
                "latest_result_kind": ((current_reply_ack or {}).get("latest_reply_received") or {}).get("result_kind"),
                "next_guidance": (current_reply_ack or {}).get("next_guidance", ""),
                "next_suggested_codes": (current_reply_ack or {}).get("next_suggested_codes", [])[:5],
            },
            "gateway_bridge_summary": {
                **gateway_operator_bridge_readiness(root, allow_inbox_rebuild=False, limit=5),
                "latest_import_classification": (operator_imported_reply_messages[-1] if operator_imported_reply_messages else {}).get("classification"),
                "latest_bridge_result": (operator_bridge_cycles[-1] if operator_bridge_cycles else {}).get("ok"),
                "latest_bridge_replay_ok": (operator_bridge_replays[-1] if operator_bridge_replays else {}).get("ok"),
            },
            "latest_compare_reply_transport_cycles": latest_compare_reply_transport,
            "latest_compare_bridge_cycles": latest_compare_bridge_cycles,
            "latest_compare_control_plane_checkpoints": latest_compare_control_plane_checkpoints,
            "current_action_pack": current_action_pack,
            "current_command_center": {
                "health_label": ((current_command_center or {}).get("now") or {}).get("control_plane_health_label"),
                "top_next_commands": (current_command_center or {}).get("next_actions", [])[:5],
                "recent_deltas": (current_command_center or {}).get("recent_deltas", {}),
            },
            "current_decision_manifest": {
                "ranked_next_commands": (current_decision_manifest or {}).get("ranked_next_commands", [])[:5],
                "do_not_run_items": (current_decision_manifest or {}).get("do_not_run_items", [])[:5],
            },
            "current_decision_inbox": {
                "reply_ready": decision_inbox.get("reply_ready"),
                "top_items": decision_inbox.get("items", [])[:5],
            },
            "current_decision_shortlist": decision_shortlist,
            "latest_compare_packs": latest_compare_packs,
            "latest_compare_triage": latest_compare_triage,
            "latest_compare_inbox": latest_compare_inbox,
            "triage_summary": {
                "control_plane_health_summary": triage_summary.get("control_plane_health_summary", {}),
                "repeated_problem_detectors": triage_summary.get("repeated_problem_detectors", {}),
                "recommended_operator_interventions": triage_summary.get("recommended_operator_interventions", [])[:5],
            },
        },
        "counts": counts,
        "next_recommended_move": next_move,
    }


def summarize_status(root: Path) -> dict[str, Any]:
    return build_status(root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build task status summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    result = build_status(Path(args.root).resolve())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
