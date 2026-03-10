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

from runtime.core.models import OutputStatus, RecordLifecycleState, TaskRecord, TaskStatus
from runtime.controls.control_store import get_effective_control_state, list_control_records


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
        "review_required": task.review_required,
        "approval_required": task.approval_required,
        "promoted_artifact_id": task.promoted_artifact_id,
        "candidate_artifact_ids": list(task.candidate_artifact_ids),
        "demoted_artifact_ids": list(task.demoted_artifact_ids),
        "revoked_artifact_ids": list(task.revoked_artifact_ids),
        "impacted_output_ids": list(task.impacted_output_ids),
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
            "review_required": task.review_required,
            "approval_required": task.approval_required,
            "promoted_artifact_id": task.promoted_artifact_id,
            "candidate_artifact_ids": list(task.candidate_artifact_ids),
            "demoted_artifact_ids": list(task.demoted_artifact_ids),
            "revoked_artifact_ids": list(task.revoked_artifact_ids),
            "impacted_output_ids": list(task.impacted_output_ids),
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
    from scripts.operator_checkpoint_action_pack import classify_action_pack
    from scripts.operator_triage_support import build_decision_inbox_data, build_decision_shortlist_data, build_triage_data
    control_records = [record.to_dict() for record in list_control_records(root=root)]
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
        "has_active_controls": bool(control_records),
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
        "controls": len(control_records),
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
    }
    triage_summary = build_triage_data(root, limit=10, allow_pack_rebuild=False)
    decision_inbox = build_decision_inbox_data(root, limit=10, allow_pack_rebuild=False)
    decision_shortlist = build_decision_shortlist_data(root, limit=5, allow_inbox_rebuild=False)
    command_center_path = root / "state" / "logs" / "operator_command_center.json"
    decision_manifest_path = root / "state" / "logs" / "operator_decision_manifest.json"
    compare_packs_path = root / "state" / "logs" / "operator_compare_packs_latest.json"
    compare_triage_path = root / "state" / "logs" / "operator_compare_triage_latest.json"
    compare_inbox_path = root / "state" / "logs" / "operator_compare_inbox_latest.json"
    outbound_prompt_path = root / "state" / "logs" / "operator_outbound_prompt_latest.json"
    reply_ack_path = root / "state" / "logs" / "operator_reply_ack_latest.json"
    current_command_center = None
    current_decision_manifest = None
    latest_compare_packs = None
    latest_compare_triage = None
    latest_compare_inbox = None
    current_outbound_prompt = None
    current_reply_ack = None
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
    if outbound_prompt_path.exists():
        try:
            current_outbound_prompt = json.loads(outbound_prompt_path.read_text(encoding="utf-8"))
        except Exception:
            current_outbound_prompt = None
    if reply_ack_path.exists():
        try:
            current_reply_ack = json.loads(reply_ack_path.read_text(encoding="utf-8"))
        except Exception:
            current_reply_ack = None

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
        "impacted_artifacts": impacted_artifacts,
        "revoked_artifacts": revoked_artifacts,
        "impacted_outputs": impacted_outputs,
        "revoked_outputs": revoked_outputs,
        "control_state": {
            "effective": effective_control,
            "records": control_records,
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
            "latest_queue_run": operator_queue_runs[-1] if operator_queue_runs else None,
            "latest_bulk_run": operator_bulk_runs[-1] if operator_bulk_runs else None,
            "latest_task_intervention": operator_task_interventions[-1] if operator_task_interventions else None,
            "latest_safe_autofix_run": operator_safe_autofix_runs[-1] if operator_safe_autofix_runs else None,
            "latest_reply_plan": operator_reply_plans[-1] if operator_reply_plans else None,
            "latest_reply_apply": operator_reply_applies[-1] if operator_reply_applies else None,
            "latest_reply_ingress": operator_reply_ingress[-1] if operator_reply_ingress else None,
            "latest_reply_ingress_run": operator_reply_ingress_runs[-1] if operator_reply_ingress_runs else None,
            "latest_reply_transport_cycle": operator_reply_transport_cycles[-1] if operator_reply_transport_cycles else None,
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
            "current_reply_ack": {
                "generated_at": (current_reply_ack or {}).get("generated_at"),
                "latest_result_kind": ((current_reply_ack or {}).get("latest_reply_received") or {}).get("result_kind"),
                "next_guidance": (current_reply_ack or {}).get("next_guidance", ""),
                "next_suggested_codes": (current_reply_ack or {}).get("next_suggested_codes", [])[:5],
            },
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
