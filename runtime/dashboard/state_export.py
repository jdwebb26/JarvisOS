#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.dashboard.status_names import normalize_status_name


def _load_jsons(folder: Path) -> list[dict]:
    rows: list[dict] = []
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return rows


def _load_flowstate_source_records(folder: Path) -> list[dict]:
    rows: list[dict] = []
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "source_id" not in row:
            continue
        rows.append(row)
    return rows


def build_state_export(root: Path) -> dict:
    tasks = _load_jsons(root / "state" / "tasks")
    reviews = _load_jsons(root / "state" / "reviews")
    approvals = _load_jsons(root / "state" / "approvals")
    approval_checkpoints = _load_jsons(root / "state" / "approval_checkpoints")
    artifacts = _load_jsons(root / "state" / "artifacts")
    outputs = _load_jsons(root / "workspace" / "out")
    flowstate_sources = _load_flowstate_source_records(root / "state" / "flowstate_sources")
    controls = _load_jsons(root / "state" / "controls")
    control_actions = _load_jsons(root / "state" / "control_actions")
    hermes_requests = _load_jsons(root / "state" / "hermes_requests")
    hermes_results = _load_jsons(root / "state" / "hermes_results")
    research_campaigns = _load_jsons(root / "state" / "research_campaigns")
    experiment_runs = _load_jsons(root / "state" / "experiment_runs")
    metric_results = _load_jsons(root / "state" / "metric_results")
    research_recommendations = _load_jsons(root / "state" / "research_recommendations")
    run_traces = _load_jsons(root / "state" / "run_traces")
    eval_cases = _load_jsons(root / "state" / "eval_cases")
    eval_results = _load_jsons(root / "state" / "eval_results")
    consolidation_runs = _load_jsons(root / "state" / "consolidation_runs")
    digest_artifact_links = _load_jsons(root / "state" / "digest_artifact_links")
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
    operator_reply_transport_replay_plans = _load_jsons(root / "state" / "operator_reply_transport_replay_plans")
    operator_reply_transport_replays = _load_jsons(root / "state" / "operator_reply_transport_replays")
    operator_reply_messages = _load_jsons(root / "state" / "operator_reply_messages")
    operator_outbound_packets = _load_jsons(root / "state" / "operator_outbound_packets")
    operator_imported_reply_messages = _load_jsons(root / "state" / "operator_imported_reply_messages")
    operator_bridge_cycles = _load_jsons(root / "state" / "operator_bridge_cycles")
    operator_bridge_replay_plans = _load_jsons(root / "state" / "operator_bridge_replay_plans")
    operator_bridge_replays = _load_jsons(root / "state" / "operator_bridge_replays")

    summary = {
        "counts": {
            "tasks": len(tasks),
            "reviews": len(reviews),
            "approvals": len(approvals),
            "approval_checkpoints": len(approval_checkpoints),
            "artifacts": len(artifacts),
            "outputs": len(outputs),
            "flowstate_sources": len(flowstate_sources),
            "controls": len(controls),
            "control_actions": len(control_actions),
            "hermes_requests": len(hermes_requests),
            "hermes_results": len(hermes_results),
            "research_campaigns": len(research_campaigns),
            "experiment_runs": len(experiment_runs),
            "metric_results": len(metric_results),
            "research_recommendations": len(research_recommendations),
            "run_traces": len(run_traces),
            "eval_cases": len(eval_cases),
            "eval_results": len(eval_results),
            "consolidation_runs": len(consolidation_runs),
            "digest_artifact_links": len(digest_artifact_links),
            "memory_candidates": len(memory_candidates),
            "memory_retrievals": len(memory_retrievals),
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
            "operator_reply_messages": len(operator_reply_messages),
            "operator_outbound_packets": len(operator_outbound_packets),
            "operator_imported_reply_messages": len(operator_imported_reply_messages),
            "operator_bridge_cycles": len(operator_bridge_cycles),
            "operator_bridge_replay_plans": len(operator_bridge_replay_plans),
            "operator_bridge_replays": len(operator_bridge_replays),
        },
        "task_status_counts": {},
        "task_lifecycle_counts": {},
        "review_status_counts": {},
        "approval_status_counts": {},
        "artifact_lifecycle_counts": {},
        "output_status_counts": {},
        "flowstate_processing_counts": {},
        "control_run_state_counts": {},
        "control_safety_mode_counts": {},
        "hermes_result_status_counts": {},
        "research_campaign_status_counts": {},
        "experiment_run_status_counts": {},
        "research_recommendation_action_counts": {},
        "run_trace_kind_counts": {},
        "eval_case_status_counts": {},
        "eval_result_pass_counts": {},
        "consolidation_run_status_counts": {},
        "memory_candidate_type_counts": {},
        "memory_candidate_decision_counts": {},
        "memory_candidate_contradiction_counts": {},
        "memory_retrieval_count": 0,
        "operator_action_failure_kind_counts": {},
        "operator_queue_skip_kind_counts": {},
        "operator_bulk_skip_kind_counts": {},
        "action_pack_validation_status_counts": {},
        "repeated_problem_counts": {},
        "command_center_summary": {},
    }

    for task in tasks:
        status = normalize_status_name(task.get("status", "unknown"))
        lifecycle_state = task.get("lifecycle_state", "unknown")
        summary["task_status_counts"][status] = summary["task_status_counts"].get(status, 0) + 1
        summary["task_lifecycle_counts"][lifecycle_state] = summary["task_lifecycle_counts"].get(lifecycle_state, 0) + 1

    for review in reviews:
        status = review.get("status", "unknown")
        summary["review_status_counts"][status] = summary["review_status_counts"].get(status, 0) + 1

    for approval in approvals:
        status = approval.get("status", "unknown")
        summary["approval_status_counts"][status] = summary["approval_status_counts"].get(status, 0) + 1

    for artifact in artifacts:
        lifecycle_state = artifact.get("lifecycle_state", "unknown")
        summary["artifact_lifecycle_counts"][lifecycle_state] = (
            summary["artifact_lifecycle_counts"].get(lifecycle_state, 0) + 1
        )

    for output in outputs:
        status = output.get("status", "unknown")
        summary["output_status_counts"][status] = summary["output_status_counts"].get(status, 0) + 1

    for source in flowstate_sources:
        status = source.get("processing_status", "unknown")
        summary["flowstate_processing_counts"][status] = summary["flowstate_processing_counts"].get(status, 0) + 1

    for control in controls:
        run_state = control.get("run_state", "unknown")
        safety_mode = control.get("safety_mode", "unknown")
        summary["control_run_state_counts"][run_state] = summary["control_run_state_counts"].get(run_state, 0) + 1
        summary["control_safety_mode_counts"][safety_mode] = summary["control_safety_mode_counts"].get(safety_mode, 0) + 1

    for result in hermes_results:
        status = result.get("status", "unknown")
        summary["hermes_result_status_counts"][status] = summary["hermes_result_status_counts"].get(status, 0) + 1

    for campaign in research_campaigns:
        status = campaign.get("status", "unknown")
        summary["research_campaign_status_counts"][status] = summary["research_campaign_status_counts"].get(status, 0) + 1

    for run in experiment_runs:
        status = run.get("status", "unknown")
        summary["experiment_run_status_counts"][status] = summary["experiment_run_status_counts"].get(status, 0) + 1

    for recommendation in research_recommendations:
        action = recommendation.get("action", "unknown")
        summary["research_recommendation_action_counts"][action] = summary["research_recommendation_action_counts"].get(action, 0) + 1

    for trace in run_traces:
        trace_kind = trace.get("trace_kind", "unknown")
        summary["run_trace_kind_counts"][trace_kind] = summary["run_trace_kind_counts"].get(trace_kind, 0) + 1

    for eval_case in eval_cases:
        status = eval_case.get("status", "unknown")
        summary["eval_case_status_counts"][status] = summary["eval_case_status_counts"].get(status, 0) + 1

    for eval_result in eval_results:
        passed = "passed" if eval_result.get("passed") else "failed"
        summary["eval_result_pass_counts"][passed] = summary["eval_result_pass_counts"].get(passed, 0) + 1

    for consolidation_run in consolidation_runs:
        status = consolidation_run.get("status", "unknown")
        summary["consolidation_run_status_counts"][status] = summary["consolidation_run_status_counts"].get(status, 0) + 1

    for memory_candidate in memory_candidates:
        memory_type = memory_candidate.get("memory_type", "unknown")
        summary["memory_candidate_type_counts"][memory_type] = summary["memory_candidate_type_counts"].get(memory_type, 0) + 1
        decision_status = memory_candidate.get("decision_status", "unknown")
        contradiction_status = memory_candidate.get("contradiction_status", "unknown")
        summary["memory_candidate_decision_counts"][decision_status] = summary["memory_candidate_decision_counts"].get(decision_status, 0) + 1
        summary["memory_candidate_contradiction_counts"][contradiction_status] = summary["memory_candidate_contradiction_counts"].get(contradiction_status, 0) + 1

    summary["memory_retrieval_count"] = len(memory_retrievals)

    for execution in operator_action_executions:
        kind = execution.get("failure_kind")
        if kind:
            summary["operator_action_failure_kind_counts"][kind] = summary["operator_action_failure_kind_counts"].get(kind, 0) + 1
        validation_status = execution.get("source_action_pack_validation_status")
        if validation_status:
            summary["action_pack_validation_status_counts"][validation_status] = (
                summary["action_pack_validation_status_counts"].get(validation_status, 0) + 1
            )

    for queue_run in operator_queue_runs:
        validation_status = queue_run.get("source_action_pack_validation_status")
        if validation_status:
            summary["action_pack_validation_status_counts"][validation_status] = (
                summary["action_pack_validation_status_counts"].get(validation_status, 0) + 1
            )
        for skipped in queue_run.get("skipped_actions", []):
            kind = skipped.get("skip_kind", "unknown")
            summary["operator_queue_skip_kind_counts"][kind] = summary["operator_queue_skip_kind_counts"].get(kind, 0) + 1

    for bulk_run in operator_bulk_runs:
        validation_status = bulk_run.get("pack_validation_status")
        if validation_status:
            summary["action_pack_validation_status_counts"][validation_status] = (
                summary["action_pack_validation_status_counts"].get(validation_status, 0) + 1
            )
        for skipped in bulk_run.get("skipped_actions", []):
            kind = skipped.get("skip_kind", "unknown")
            summary["operator_bulk_skip_kind_counts"][kind] = summary["operator_bulk_skip_kind_counts"].get(kind, 0) + 1

    from scripts.operator_triage_support import build_triage_data

    repeated = build_triage_data(root, limit=10, allow_pack_rebuild=False).get("repeated_problem_detectors", {})
    summary["repeated_problem_counts"] = {
        "repeated_stale_actions": len(repeated.get("repeated_stale_actions", [])),
        "repeated_idempotency_skips": len(repeated.get("repeated_idempotency_skips", [])),
        "repeated_pinned_pack_validation_failures": len(repeated.get("repeated_pinned_pack_validation_failures", [])),
        "repeated_expired_pack_refusals": len(repeated.get("repeated_expired_pack_refusals", [])),
        "queue_repeated_stop_categories": len(repeated.get("queue_repeated_stop_categories", [])),
        "bulk_repeated_failure_categories": len(repeated.get("bulk_repeated_failure_categories", [])),
        "actions_missing_from_newest_pack": len(repeated.get("actions_missing_from_newest_pack", [])),
    }
    command_center_path = root / "state" / "logs" / "operator_command_center.json"
    decision_manifest_path = root / "state" / "logs" / "operator_decision_manifest.json"
    current_command_center = {}
    if command_center_path.exists():
        try:
            current_command_center = json.loads(command_center_path.read_text(encoding="utf-8"))
        except Exception:
            current_command_center = {}
    current_manifest = {}
    if decision_manifest_path.exists():
        try:
            current_manifest = json.loads(decision_manifest_path.read_text(encoding="utf-8"))
        except Exception:
            current_manifest = {}
    summary["command_center_summary"] = {
        "health_label": ((current_command_center.get("now") or {}).get("control_plane_health_label")),
        "top_next_command_count": len(current_command_center.get("next_actions", [])),
        "decision_manifest_ranked_count": len(current_manifest.get("ranked_next_commands", [])),
    }
    summary["reply_summary"] = {
        "latest_reply_plan_count": len(operator_reply_plans),
        "latest_reply_apply_count": len(operator_reply_applies),
        "latest_reply_ingress_count": len(operator_reply_ingress),
        "latest_reply_ingress_run_count": len(operator_reply_ingress_runs),
        "latest_reply_transport_cycle_count": len(operator_reply_transport_cycles),
        "latest_reply_transport_replay_plan_count": len(operator_reply_transport_replay_plans),
        "latest_reply_transport_replay_count": len(operator_reply_transport_replays),
        "invalid_reply_count": sum(1 for row in operator_reply_plans if row.get("unknown_tokens")),
        "blocked_reply_count": sum(
            1
            for row in operator_reply_applies
            for step in row.get("per_step_results", [])
            if step.get("status") in {"invalid_reply", "plan_blocked"}
        ),
        "ignored_ingress_count": sum(1 for row in operator_reply_ingress if row.get("result_kind") == "ignored_non_reply"),
        "invalid_ingress_count": sum(1 for row in operator_reply_ingress if row.get("result_kind") == "invalid_reply"),
        "blocked_ingress_count": sum(
            1
            for row in operator_reply_ingress
            if row.get("result_kind") in {"missing_inbox", "stale_inbox", "pack_refresh_required", "blocked", "duplicate_message"}
        ),
        "applied_ingress_count": sum(1 for row in operator_reply_ingress if row.get("result_kind") == "applied"),
        "duplicate_ingress_count": sum(1 for row in operator_reply_ingress if row.get("result_kind") == "duplicate_message"),
        "pending_inbound_message_count": sum(1 for row in operator_reply_messages if not row.get("processed_at")),
        "latest_outbound_packet_count": len(operator_outbound_packets),
        "latest_imported_reply_message_count": len(operator_imported_reply_messages),
        "latest_bridge_cycle_count": len(operator_bridge_cycles),
        "latest_bridge_replay_plan_count": len(operator_bridge_replay_plans),
        "latest_bridge_replay_count": len(operator_bridge_replays),
        "latest_ingress_source": {
            "source_kind": (operator_reply_ingress[-1] if operator_reply_ingress else {}).get("source_kind"),
            "source_channel": (operator_reply_ingress[-1] if operator_reply_ingress else {}).get("source_channel"),
            "source_message_id": (operator_reply_ingress[-1] if operator_reply_ingress else {}).get("source_message_id"),
            "source_user": (operator_reply_ingress[-1] if operator_reply_ingress else {}).get("source_user"),
        },
    }
    outbound_prompt_path = root / "state" / "logs" / "operator_outbound_prompt_latest.json"
    reply_ack_path = root / "state" / "logs" / "operator_reply_ack_latest.json"
    if outbound_prompt_path.exists():
        try:
            outbound_prompt = json.loads(outbound_prompt_path.read_text(encoding="utf-8"))
        except Exception:
            outbound_prompt = {}
    else:
        outbound_prompt = {}
    if reply_ack_path.exists():
        try:
            reply_ack = json.loads(reply_ack_path.read_text(encoding="utf-8"))
        except Exception:
            reply_ack = {}
    else:
        reply_ack = {}
    outbound_packet_path = root / "state" / "logs" / "operator_outbound_packet_latest.json"
    if outbound_packet_path.exists():
        try:
            outbound_packet = json.loads(outbound_packet_path.read_text(encoding="utf-8"))
        except Exception:
            outbound_packet = {}
    else:
        outbound_packet = {}
    summary["reply_transport_summary"] = {
        "reply_transport_ready": bool(outbound_prompt.get("reply_ready")) and outbound_prompt.get("pack_status") == "valid",
        "outbound_prompt_pack_id": outbound_prompt.get("pack_id"),
        "outbound_packet_pack_id": outbound_packet.get("pack_id"),
        "outbound_prompt_warning": outbound_prompt.get("warning", ""),
        "outbound_publish_ready": bool(outbound_packet.get("reply_ready")) and outbound_packet.get("pack_status") == "valid",
        "inbound_import_ready": True,
        "bridge_ready": bool(outbound_packet.get("reply_ready")) and outbound_packet.get("pack_status") == "valid",
        "latest_reply_ack_result_kind": ((reply_ack.get("latest_reply_received") or {}).get("result_kind")),
        "latest_reply_ack_guidance": reply_ack.get("next_guidance", ""),
        "latest_reply_transport_replay_ok": (operator_reply_transport_replays[-1] if operator_reply_transport_replays else {}).get("ok"),
        "latest_import_classification": (operator_imported_reply_messages[-1] if operator_imported_reply_messages else {}).get("classification"),
        "latest_bridge_result": (operator_bridge_cycles[-1] if operator_bridge_cycles else {}).get("ok"),
        "latest_bridge_replay_ok": (operator_bridge_replays[-1] if operator_bridge_replays else {}).get("ok"),
    }
    compare_reply_transport_path = root / "state" / "logs" / "operator_compare_reply_transport_cycles_latest.json"
    compare_bridge_cycles_path = root / "state" / "logs" / "operator_compare_bridge_cycles_latest.json"
    if compare_reply_transport_path.exists():
        try:
            compare_reply_transport = json.loads(compare_reply_transport_path.read_text(encoding="utf-8"))
        except Exception:
            compare_reply_transport = {}
    else:
        compare_reply_transport = {}
    summary["reply_transport_compare_summary"] = {
        "current_cycle_id": compare_reply_transport.get("current_cycle_id"),
        "other_cycle_id": compare_reply_transport.get("other_cycle_id"),
        "blocked_count_delta": compare_reply_transport.get("blocked_count_delta"),
        "invalid_count_delta": compare_reply_transport.get("invalid_count_delta"),
    }
    if compare_bridge_cycles_path.exists():
        try:
            compare_bridge_cycles = json.loads(compare_bridge_cycles_path.read_text(encoding="utf-8"))
        except Exception:
            compare_bridge_cycles = {}
    else:
        compare_bridge_cycles = {}
    summary["bridge_compare_summary"] = {
        "current_bridge_cycle_id": compare_bridge_cycles.get("current_bridge_cycle_id"),
        "other_bridge_cycle_id": compare_bridge_cycles.get("other_bridge_cycle_id"),
        "imported_count_delta": compare_bridge_cycles.get("imported_count_delta"),
        "reply_transport_blocked_delta": compare_bridge_cycles.get("reply_transport_blocked_delta"),
        "latest_bridge_replay_id": (operator_bridge_replays[-1] if operator_bridge_replays else {}).get("bridge_replay_id"),
    }

    out_path = root / "state" / "logs" / "state_export.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a compact state summary for operator handoff/debug.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    summary = build_state_export(root)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
