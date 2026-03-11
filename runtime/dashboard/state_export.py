#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.controls.control_store import build_control_summary
from runtime.core.browser_control_allowlist import build_browser_control_allowlist_summary
from runtime.core.degradation_policy import build_degradation_summary
from runtime.core.eval_profiles import build_eval_profile_summary
from runtime.core.heartbeat_reports import build_heartbeat_report_summary
from runtime.core.routing import build_model_registry_summary
from runtime.core.token_budget import build_token_budget_summary
from runtime.core.voice_sessions import build_voice_session_summary
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


def _timestamp(row: dict) -> str:
    return row.get("updated_at") or row.get("created_at") or ""


def _latest_row(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    return max(rows, key=_timestamp)


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
    control_events = _load_jsons(root / "state" / "control_events")
    control_blocked_actions = _load_jsons(root / "state" / "control_blocked_actions")
    hermes_requests = _load_jsons(root / "state" / "hermes_requests")
    hermes_results = _load_jsons(root / "state" / "hermes_results")
    research_campaigns = _load_jsons(root / "state" / "research_campaigns")
    experiment_runs = _load_jsons(root / "state" / "experiment_runs")
    metric_results = _load_jsons(root / "state" / "metric_results")
    research_recommendations = _load_jsons(root / "state" / "research_recommendations")
    run_traces = _load_jsons(root / "state" / "run_traces")
    eval_cases = _load_jsons(root / "state" / "eval_cases")
    eval_results = _load_jsons(root / "state" / "eval_results")
    eval_profiles = _load_jsons(root / "state" / "eval_profiles")
    model_registry_entries = _load_jsons(root / "state" / "model_registry_entries")
    capability_profiles = _load_jsons(root / "state" / "capability_profiles")
    routing_policies = _load_jsons(root / "state" / "routing_policies")
    routing_overrides = _load_jsons(root / "state" / "routing_overrides")
    routing_requests = _load_jsons(root / "state" / "routing_requests")
    routing_decisions = _load_jsons(root / "state" / "routing_decisions")
    provider_adapter_results = _load_jsons(root / "state" / "provider_adapter_results")
    backend_execution_requests = _load_jsons(root / "state" / "backend_execution_requests")
    backend_execution_results = _load_jsons(root / "state" / "backend_execution_results")
    token_budgets = _load_jsons(root / "state" / "token_budgets")
    degradation_policies = _load_jsons(root / "state" / "degradation_policies")
    degradation_events = _load_jsons(root / "state" / "degradation_events")
    heartbeat_reports = _load_jsons(root / "state" / "heartbeat_reports")
    browser_control_allowlists = _load_jsons(root / "state" / "browser_control_allowlists")
    voice_sessions = _load_jsons(root / "state" / "voice_sessions")
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
    consolidation_runs = _load_jsons(root / "state" / "consolidation_runs")
    digest_artifact_links = _load_jsons(root / "state" / "digest_artifact_links")
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
    operator_reply_messages = _load_jsons(root / "state" / "operator_reply_messages")
    operator_outbound_packets = _load_jsons(root / "state" / "operator_outbound_packets")
    operator_imported_reply_messages = _load_jsons(root / "state" / "operator_imported_reply_messages")
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
            "control_events": len(control_events),
            "control_blocked_actions": len(control_blocked_actions),
            "hermes_requests": len(hermes_requests),
            "hermes_results": len(hermes_results),
            "research_campaigns": len(research_campaigns),
            "experiment_runs": len(experiment_runs),
            "metric_results": len(metric_results),
            "research_recommendations": len(research_recommendations),
            "run_traces": len(run_traces),
            "eval_cases": len(eval_cases),
            "eval_results": len(eval_results),
            "eval_profiles": len(eval_profiles),
            "model_registry_entries": len(model_registry_entries),
            "capability_profiles": len(capability_profiles),
            "routing_policies": len(routing_policies),
            "routing_overrides": len(routing_overrides),
            "routing_requests": len(routing_requests),
            "routing_decisions": len(routing_decisions),
            "provider_adapter_results": len(provider_adapter_results),
            "backend_execution_requests": len(backend_execution_requests),
            "backend_execution_results": len(backend_execution_results),
            "token_budgets": len(token_budgets),
            "degradation_policies": len(degradation_policies),
            "degradation_events": len(degradation_events),
            "heartbeat_reports": len(heartbeat_reports),
            "browser_control_allowlists": len(browser_control_allowlists),
            "voice_sessions": len(voice_sessions),
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
            "consolidation_runs": len(consolidation_runs),
            "digest_artifact_links": len(digest_artifact_links),
            "memory_candidates": len(memory_candidates),
            "memory_retrievals": len(memory_retrievals),
            "memory_validations": len(memory_validations),
            "memory_promotion_decisions": len(memory_promotion_decisions),
            "memory_rejection_decisions": len(memory_rejection_decisions),
            "memory_revocation_decisions": len(memory_revocation_decisions),
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
            "operator_doctor_reports": len(operator_doctor_reports),
            "operator_remediation_plans": len(operator_remediation_plans),
            "operator_remediation_runs": len(operator_remediation_runs),
            "operator_remediation_step_runs": len(operator_remediation_step_runs),
            "operator_recovery_cycles": len(operator_recovery_cycles),
            "operator_control_plane_checkpoints": len(operator_control_plane_checkpoints),
            "operator_incident_reports": len(operator_incident_reports),
            "operator_incident_snapshots": len(operator_incident_snapshots),
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
        "model_family_counts": {},
        "routing_backend_counts": {},
        "backend_execution_status_counts": {},
        "task_publish_readiness_counts": {},
        "autonomy_mode_counts": {},
        "candidate_record_lifecycle_counts": {},
        "candidate_validation_status_counts": {},
        "approval_session_state_counts": {},
        "rollback_action_kind_counts": {},
        "subsystem_contract_kind_counts": {},
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
        readiness = task.get("publish_readiness_status", "pending")
        summary["task_publish_readiness_counts"][readiness] = summary["task_publish_readiness_counts"].get(readiness, 0) + 1
        autonomy_mode = task.get("autonomy_mode", "step_mode")
        summary.setdefault("autonomy_mode_counts", {})
        summary["autonomy_mode_counts"][autonomy_mode] = summary["autonomy_mode_counts"].get(autonomy_mode, 0) + 1

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

    for entry in model_registry_entries:
        family = entry.get("model_family", "unknown")
        summary["model_family_counts"][family] = summary["model_family_counts"].get(family, 0) + 1

    for decision in routing_decisions:
        backend = decision.get("selected_execution_backend", "unknown")
        summary["routing_backend_counts"][backend] = summary["routing_backend_counts"].get(backend, 0) + 1

    for result in backend_execution_results:
        status = result.get("status", "unknown")
        summary["backend_execution_status_counts"][status] = summary["backend_execution_status_counts"].get(status, 0) + 1

    for candidate in candidate_records:
        lifecycle_state = candidate.get("lifecycle_state", "unknown")
        summary["candidate_record_lifecycle_counts"][lifecycle_state] = (
            summary["candidate_record_lifecycle_counts"].get(lifecycle_state, 0) + 1
        )

    for validation in candidate_validations:
        status = validation.get("status", "unknown")
        summary["candidate_validation_status_counts"][status] = (
            summary["candidate_validation_status_counts"].get(status, 0) + 1
        )

    for session in approval_sessions:
        state = session.get("session_state", "unknown")
        summary["approval_session_state_counts"][state] = summary["approval_session_state_counts"].get(state, 0) + 1

    for execution in rollback_executions:
        kind = execution.get("action_kind", "unknown")
        summary["rollback_action_kind_counts"][kind] = summary["rollback_action_kind_counts"].get(kind, 0) + 1

    for contract in subsystem_contracts:
        kind = contract.get("subsystem_kind", "unknown")
        summary["subsystem_contract_kind_counts"][kind] = summary["subsystem_contract_kind_counts"].get(kind, 0) + 1

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

    latest_routing_decision = _latest_row(routing_decisions)
    latest_backend_execution_request = _latest_row(backend_execution_requests)
    latest_backend_execution_result = _latest_row(backend_execution_results)
    latest_candidate = _latest_row(candidate_records)
    latest_candidate_validation = _latest_row(candidate_validations)
    latest_promotion_decision = _latest_row(promotion_decisions)
    latest_rejection_decision = _latest_row(rejection_decisions)
    latest_candidate_revocation = _latest_row(candidate_revocations)
    latest_task_provenance = _latest_row(task_provenance)
    latest_artifact_provenance = _latest_row(artifact_provenance)
    latest_routing_provenance = _latest_row(routing_provenance)
    latest_decision_provenance = _latest_row(decision_provenance)
    latest_publish_provenance = _latest_row(publish_provenance)
    latest_rollback_provenance = _latest_row(rollback_provenance)
    latest_memory_provenance = _latest_row(memory_provenance)
    latest_replay_plan = _latest_row(replay_plans)
    latest_replay_execution = _latest_row(replay_executions)
    latest_replay_result = _latest_row(replay_results)
    latest_rollback_plan = _latest_row(rollback_plans)
    latest_rollback_execution = _latest_row(rollback_executions)
    latest_revocation_impact = _latest_row(revocation_impacts)
    latest_approval_session = _latest_row(approval_sessions)
    latest_resume_token = _latest_row(approval_resume_tokens)
    latest_subsystem_contract = _latest_row(subsystem_contracts)
    latest_modality_contract = _latest_row(modality_contracts)
    latest_memory_candidate = _latest_row(memory_candidates)
    latest_memory_validation = _latest_row(memory_validations)
    latest_memory_promotion = _latest_row(memory_promotion_decisions)
    latest_memory_rejection = _latest_row(memory_rejection_decisions)
    latest_memory_revocation = _latest_row(memory_revocation_decisions)
    latest_output_dependency = _latest_row(output_dependencies)
    latest_blocked_action = _latest_row(control_blocked_actions)

    routing_summary = build_model_registry_summary(root=root)
    routing_summary["latest_routing_decision"] = latest_routing_decision
    summary["routing_summary"] = routing_summary
    summary["execution_contract_summary"] = {
        "backend_execution_request_count": len(backend_execution_requests),
        "backend_execution_result_count": len(backend_execution_results),
        "backend_execution_status_counts": dict(summary["backend_execution_status_counts"]),
        "backend_execution_kind_counts": {
            key: sum(1 for row in backend_execution_results if row.get("request_kind") == key)
            for key in sorted({row.get("request_kind", "unknown") for row in backend_execution_results})
        },
        "latest_backend_execution_request": latest_backend_execution_request,
        "latest_backend_execution_result": latest_backend_execution_result,
    }
    summary["token_budget_summary"] = build_token_budget_summary(root=root)
    summary["degradation_summary"] = build_degradation_summary(root=root)
    summary["heartbeat_summary"] = build_heartbeat_report_summary(root=root)
    summary["eval_profile_summary"] = build_eval_profile_summary(root=root)
    summary["browser_control_allowlist_summary"] = build_browser_control_allowlist_summary(root=root)
    summary["voice_session_summary"] = build_voice_session_summary(root=root)
    summary["task_envelope_summary"] = {
        "task_envelope_task_count": sum(1 for row in tasks if row.get("task_envelope")),
        "autonomy_mode_counts": dict(summary.get("autonomy_mode_counts", {})),
        "speculative_downstream_count": sum(1 for row in tasks if row.get("speculative_downstream")),
        "blocked_dependency_task_count": sum(1 for row in tasks if row.get("blocked_dependency_refs")),
    }
    summary["candidate_promotion_summary"] = {
        "candidate_count": len(candidate_records),
        "promotable_candidate_count": sum(1 for row in candidate_records if row.get("lifecycle_state") == "candidate"),
        "promoted_candidate_count": sum(1 for row in candidate_records if row.get("lifecycle_state") == "promoted"),
        "latest_candidate": latest_candidate,
        "latest_validation": latest_candidate_validation,
        "latest_promotion_decision": latest_promotion_decision,
        "latest_rejection_decision": latest_rejection_decision,
        "latest_revocation": latest_candidate_revocation,
    }
    summary["provenance_summary"] = {
        "task_provenance_count": len(task_provenance),
        "artifact_provenance_count": len(artifact_provenance),
        "routing_provenance_count": len(routing_provenance),
        "decision_provenance_count": len(decision_provenance),
        "publish_provenance_count": len(publish_provenance),
        "rollback_provenance_count": len(rollback_provenance),
        "memory_provenance_count": len(memory_provenance),
        "latest_task_provenance": latest_task_provenance,
        "latest_artifact_provenance": latest_artifact_provenance,
        "latest_routing_provenance": latest_routing_provenance,
        "latest_decision_provenance": latest_decision_provenance,
        "latest_publish_provenance": latest_publish_provenance,
        "latest_rollback_provenance": latest_rollback_provenance,
        "latest_memory_provenance": latest_memory_provenance,
    }
    summary["replay_summary"] = {
        "replay_plan_count": len(replay_plans),
        "replay_execution_count": len(replay_executions),
        "replay_result_count": len(replay_results),
        "replay_drift_count": sum(1 for row in replay_results if row.get("result_kind") == "drift"),
        "latest_replay_plan": latest_replay_plan,
        "latest_replay_execution": latest_replay_execution,
        "latest_replay_result": latest_replay_result,
    }
    summary["rollback_summary"] = {
        "rollback_plan_count": len(rollback_plans),
        "rollback_execution_count": len(rollback_executions),
        "revocation_impact_count": len(revocation_impacts),
        "latest_rollback_plan": latest_rollback_plan,
        "latest_rollback_execution": latest_rollback_execution,
        "latest_revocation_impact": latest_revocation_impact,
        "output_dependency_count": len(output_dependencies),
    }
    summary["control_summary"] = {
        "latest_control_event_id": (control_events[-1] if control_events else {}).get("control_event_id"),
        "latest_blocked_action_id": (control_blocked_actions[-1] if control_blocked_actions else {}).get("blocked_action_id"),
        "execution_freeze_count": sum(1 for row in controls if row.get("execution_freeze")),
        "promotion_freeze_count": sum(1 for row in controls if row.get("promotion_freeze")),
        "approval_freeze_count": sum(1 for row in controls if row.get("approval_freeze")),
        "memory_freeze_count": sum(1 for row in controls if row.get("memory_freeze")),
        "disabled_provider_count": sum(len(row.get("disabled_provider_ids", [])) for row in controls),
        "disabled_execution_backend_count": sum(len(row.get("disabled_execution_backends", [])) for row in controls),
    }
    summary["approval_session_summary"] = {
        "approval_session_count": len(approval_sessions),
        "approval_context_count": len(approval_decision_contexts),
        "approval_resume_token_count": len(approval_resume_tokens),
        "latest_approval_session": latest_approval_session,
        "latest_resume_token": latest_resume_token,
        "resumable_session_count": sum(1 for row in approval_sessions if row.get("resumable") and not row.get("terminal")),
        "terminal_session_count": sum(1 for row in approval_sessions if row.get("terminal")),
    }
    summary["subsystem_contract_summary"] = {
        "latest_subsystem_contract": latest_subsystem_contract,
        "subsystem_contract_count": len(subsystem_contracts),
    }
    enabled_input_modalities = sorted(
        {mod for row in modality_contracts if row.get("enabled") for mod in row.get("input_modalities", [])}
    )
    summary["multimodal_summary"] = {
        "modality_contract_count": len(modality_contracts),
        "enabled_modality_contract_count": sum(1 for row in modality_contracts if row.get("enabled")),
        "enabled_input_modalities": enabled_input_modalities,
        "runtime_modality_mode": "text_only_qwen",
        "multimodal_runtime_enabled": any(mod in {"image_ref", "audio_ref", "file_ref"} for mod in enabled_input_modalities),
        "latest_modality_contract": latest_modality_contract,
        "policy_tags": sorted({tag for row in modality_contracts for tag in row.get("policy_tags", [])}),
    }
    latest_memory_event = None
    for kind, rows in (
        ("promotion", memory_promotion_decisions),
        ("rejection", memory_rejection_decisions),
        ("revocation", memory_revocation_decisions),
    ):
        latest = _latest_row(rows)
        if latest and (latest_memory_event is None or _timestamp(latest) > latest_memory_event.get("updated_at", "")):
            latest_memory_event = {"event_kind": kind, **latest}
    summary["memory_discipline_summary"] = {
        "memory_candidate_count": len(memory_candidates),
        "memory_validation_count": len(memory_validations),
        "memory_promotion_count": len(memory_promotion_decisions),
        "memory_rejection_count": len(memory_rejection_decisions),
        "memory_revocation_count": len(memory_revocation_decisions),
        "latest_memory_candidate": latest_memory_candidate,
        "latest_memory_validation": latest_memory_validation,
        "latest_memory_event": latest_memory_event,
    }
    control_summary = build_control_summary(root=root)
    summary["promotion_governance_summary"] = {
        "candidate_count": len(candidate_records),
        "promotable_candidate_count": sum(1 for row in candidate_records if row.get("lifecycle_state") == "candidate"),
        "promoted_candidate_count": sum(1 for row in candidate_records if row.get("lifecycle_state") == "promoted"),
        "effective_control_status": (control_summary.get("effective") or {}).get("effective_status"),
        "promotion_freeze_active": bool(((control_summary.get("effective") or {}).get("emergency_flags") or {}).get("promotion_freeze")),
        "memory_freeze_active": bool(((control_summary.get("effective") or {}).get("emergency_flags") or {}).get("memory_freeze")),
        "latest_candidate": latest_candidate,
        "latest_output_dependency": latest_output_dependency,
        "latest_blocked_action": latest_blocked_action,
    }

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
        "latest_doctor_report_count": len(operator_doctor_reports),
        "latest_remediation_plan_count": len(operator_remediation_plans),
        "latest_remediation_run_count": len(operator_remediation_runs),
        "latest_remediation_step_run_count": len(operator_remediation_step_runs),
        "latest_recovery_cycle_count": len(operator_recovery_cycles),
        "latest_control_plane_checkpoint_count": len(operator_control_plane_checkpoints),
        "latest_incident_report_count": len(operator_incident_reports),
        "latest_incident_snapshot_count": len(operator_incident_snapshots),
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
        "doctor_health_status": (operator_doctor_reports[-1] if operator_doctor_reports else {}).get("health_status"),
        "doctor_active_issue_count": (operator_doctor_reports[-1] if operator_doctor_reports else {}).get("active_issue_count"),
    }
    compare_reply_transport_path = root / "state" / "logs" / "operator_compare_reply_transport_cycles_latest.json"
    compare_bridge_cycles_path = root / "state" / "logs" / "operator_compare_bridge_cycles_latest.json"
    compare_control_plane_checkpoints_path = root / "state" / "logs" / "operator_compare_control_plane_checkpoints_latest.json"
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
    if compare_control_plane_checkpoints_path.exists():
        try:
            compare_control_plane_checkpoints = json.loads(compare_control_plane_checkpoints_path.read_text(encoding="utf-8"))
        except Exception:
            compare_control_plane_checkpoints = {}
    else:
        compare_control_plane_checkpoints = {}
    summary["control_plane_checkpoint_summary"] = {
        "latest_control_plane_checkpoint_id": (operator_control_plane_checkpoints[-1] if operator_control_plane_checkpoints else {}).get("control_plane_checkpoint_id"),
        "control_plane_checkpoint_count": len(operator_control_plane_checkpoints),
        "latest_compare_checkpoint_id": compare_control_plane_checkpoints.get("current_checkpoint_id"),
    }
    summary["latest_compare_control_plane_checkpoints"] = compare_control_plane_checkpoints
    summary["incident_summary"] = {
        "latest_incident_report_id": (operator_incident_reports[-1] if operator_incident_reports else {}).get("incident_report_id"),
        "latest_incident_code": (operator_incident_reports[-1] if operator_incident_reports else {}).get("incident_code"),
        "latest_incident_severity": (operator_incident_reports[-1] if operator_incident_reports else {}).get("severity"),
        "operator_incident_report_count": len(operator_incident_reports),
        "operator_incident_snapshot_count": len(operator_incident_snapshots),
    }
    summary["doctor_summary"] = {
        "latest_doctor_report_id": (operator_doctor_reports[-1] if operator_doctor_reports else {}).get("doctor_report_id"),
        "health_status": (operator_doctor_reports[-1] if operator_doctor_reports else {}).get("health_status"),
        "highest_severity": (operator_doctor_reports[-1] if operator_doctor_reports else {}).get("highest_severity"),
        "active_issue_count": (operator_doctor_reports[-1] if operator_doctor_reports else {}).get("active_issue_count"),
        "latest_remediation_plan_id": (operator_remediation_plans[-1] if operator_remediation_plans else {}).get("remediation_plan_id"),
        "latest_remediation_run_id": (operator_remediation_runs[-1] if operator_remediation_runs else {}).get("remediation_run_id"),
        "next_recommended_commands": ((operator_doctor_reports[-1] if operator_doctor_reports else {}).get("next_recommended_commands", []))[:5],
    }
    summary["remediation_run_summary"] = {
        "latest_remediation_run_id": (operator_remediation_runs[-1] if operator_remediation_runs else {}).get("remediation_run_id"),
        "latest_remediation_run_ok": (operator_remediation_runs[-1] if operator_remediation_runs else {}).get("ok"),
        "latest_remediation_run_dry_run": (operator_remediation_runs[-1] if operator_remediation_runs else {}).get("dry_run"),
        "latest_remediation_run_attempted_step_count": (operator_remediation_runs[-1] if operator_remediation_runs else {}).get("attempted_step_count"),
        "latest_remediation_run_failed_step_count": (operator_remediation_runs[-1] if operator_remediation_runs else {}).get("failed_step_count"),
        "latest_remediation_run_stop_reason": (operator_remediation_runs[-1] if operator_remediation_runs else {}).get("stop_reason"),
    }
    summary["recovery_cycle_summary"] = {
        "latest_recovery_cycle_id": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("recovery_cycle_id"),
        "latest_recovery_cycle_ok": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("ok"),
        "latest_recovery_cycle_dry_run": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("dry_run"),
        "latest_recovery_cycle_active_issue_count_before": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("active_issue_count_before"),
        "latest_recovery_cycle_active_issue_count_after": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("active_issue_count_after"),
        "latest_recovery_cycle_issue_count_before": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("active_issue_count_before"),
        "latest_recovery_cycle_issue_count_after": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("active_issue_count_after"),
        "latest_recovery_cycle_stop_reason": (operator_recovery_cycles[-1] if operator_recovery_cycles else {}).get("stop_reason"),
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
