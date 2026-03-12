#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.status import summarize_status
from runtime.dashboard.renderers.a2ui_renderer import render_operator_views
from runtime.dashboard.status_names import normalize_status_summary
from runtime.dashboard.runtime_5_2_prep import build_runtime_5_2_prep_summary
from runtime.core.task_lease import build_task_lease_summary
from runtime.integrations.research_backends import build_research_backend_summary
from runtime.memory.vault_export import build_vault_export_summary
from runtime.researchlab.experiment_store import build_experiment_summary
from runtime.researchlab.evidence_bundle import build_evidence_bundle_summary
from runtime.skills.skill_scheduler import build_skill_scheduler_summary
from runtime.evals.replay_runner import build_eval_run_summary


def _load_json_files(folder: Path) -> list[dict]:
    items: list[dict] = []
    if not folder.exists():
        return items
    for path in sorted(folder.glob("*.json")):
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return items


def _load_flowstate_index(root: Path) -> dict:
    path = root / "state" / "flowstate_sources" / "index.json"
    if not path.exists():
        return {"counts": {}, "items": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"counts": {}, "items": []}


def build_operator_snapshot(root: Path) -> dict:
    status = normalize_status_summary(summarize_status(root=root))
    runtime_5_2_prep = build_runtime_5_2_prep_summary(root=root)
    eval_scaffolding_summary = build_eval_run_summary(root=root)
    task_lease_summary = build_task_lease_summary(root=root)
    skill_scheduler_summary = build_skill_scheduler_summary(root=root)
    reviews = _load_json_files(root / "state" / "reviews")
    approvals = _load_json_files(root / "state" / "approvals")
    flowstate_index = _load_flowstate_index(root)

    pending_reviews = [
        {
            "review_id": r["review_id"],
            "task_id": r["task_id"],
            "reviewer_role": r["reviewer_role"],
            "status": r["status"],
            "summary": r["summary"],
            "linked_artifact_ids": r.get("linked_artifact_ids", []),
        }
        for r in reviews
        if r.get("status") == "pending"
    ]

    pending_approvals = [
        {
            "approval_id": a["approval_id"],
            "task_id": a["task_id"],
            "requested_reviewer": a["requested_reviewer"],
            "status": a["status"],
            "summary": a["summary"],
            "linked_artifact_ids": a.get("linked_artifact_ids", []),
            "resumable_checkpoint_id": a.get("resumable_checkpoint_id"),
        }
        for a in approvals
        if a.get("status") == "pending"
    ]

    flowstate_waiting = [
        {
            "source_id": item["source_id"],
            "title": item["title"],
            "processing_status": item["processing_status"],
            "promotion_request_ids": item.get("promotion_request_ids", []),
            "extraction_artifact_present": item.get("extraction_artifact_present", False),
            "distillation_artifact_present": item.get("distillation_artifact_present", False),
            "candidate_action_count": item.get("candidate_action_count", 0),
        }
        for item in flowstate_index.get("items", [])
        if item.get("processing_status") == "awaiting_promotion_approval"
    ]

    from scripts.operator_checkpoint_action_pack import classify_action_pack

    current_action_pack_path = root / "state" / "logs" / "operator_checkpoint_action_pack.json"
    current_action_pack = {"path": str(current_action_pack_path), "status": "malformed", "fresh": False}
    if current_action_pack_path.exists():
        try:
            current_action_pack = {"path": str(current_action_pack_path), **classify_action_pack(json.loads(current_action_pack_path.read_text(encoding="utf-8")))}
        except Exception as exc:
            current_action_pack = {"path": str(current_action_pack_path), "status": "malformed", "reason": str(exc), "fresh": False}

    candidate_apply_ready = [
        {
            "task_id": task["task_id"],
            "status": task["status"],
            "summary": task["summary"],
            "execution_backend": task.get("execution_backend"),
            "promoted_artifact_id": task.get("promoted_artifact_id"),
            "handoff": (
                "Approved and ready for live apply."
                if task.get("status") == "ready_to_ship"
                else "Already shipped; publish completion or final verification may be next."
            ),
            "next_action": (
                "Run Qwen candidate apply. Use --dry-run first if you want a no-write verification pass."
                if task.get("status") == "ready_to_ship"
                else "Confirm the linked artifact, then run publish-complete."
            ),
        }
        for task in status.get("ready_to_ship", []) + status.get("shipped", [])
        if task.get("promoted_artifact_id")
    ]

    if status.get("blocked"):
        operator_focus = "Inspect active control-state and blocked tasks before resuming any execution-bearing work."
    elif status.get("control_state", {}).get("effective", {}).get("has_active_controls"):
        operator_focus = "Inspect active control-state before promoting, resuming, or publishing work."
    elif pending_reviews:
        operator_focus = "Clear pending reviews first."
    elif pending_approvals:
        operator_focus = "Clear pending approvals next."
    elif status.get("revoked_outputs") or status.get("revoked_artifacts"):
        operator_focus = "Inspect revoked artifacts and outputs before continuing downstream work."
    elif status.get("impacted_outputs") or status.get("impacted_artifacts"):
        operator_focus = "Inspect impacted artifacts and outputs before shipping more work."
    elif candidate_apply_ready:
        operator_focus = "Apply or publish candidate-ready tasks."
    else:
        operator_focus = status.get("next_recommended_move", "")

    snapshot = {
        "status": status,
        "operator_control_plane": status.get("operator_control_plane", {}),
        "current_action_pack": current_action_pack,
        "current_command_center": (status.get("operator_control_plane", {}) or {}).get("current_command_center", {}),
        "current_decision_manifest": (status.get("operator_control_plane", {}) or {}).get("current_decision_manifest", {}),
        "current_decision_inbox": (status.get("operator_control_plane", {}) or {}).get("current_decision_inbox", {}),
        "current_decision_shortlist": (status.get("operator_control_plane", {}) or {}).get("current_decision_shortlist", {}),
        "reply_ingress_summary": (status.get("operator_control_plane", {}) or {}).get("reply_ingress_summary", {}),
        "current_outbound_prompt": (status.get("operator_control_plane", {}) or {}).get("current_outbound_prompt", {}),
        "current_outbound_packet": (status.get("operator_control_plane", {}) or {}).get("current_outbound_packet", {}),
        "current_reply_ack": (status.get("operator_control_plane", {}) or {}).get("current_reply_ack", {}),
        "gateway_bridge_summary": (status.get("operator_control_plane", {}) or {}).get("gateway_bridge_summary", {}),
        "routing_summary": status.get("routing_summary", {}),
        "discord_live_ops_summary": status.get("discord_live_ops_summary", {}),
        "openclaw_discord_bridge_summary": status.get("openclaw_discord_bridge_summary", {}),
        "backend_assignment_summary": status.get("backend_assignment_summary", {}),
        "execution_contract_summary": status.get("execution_contract_summary", {}),
        "token_budget_summary": status.get("token_budget_summary", {}),
        "degradation_summary": status.get("degradation_summary", {}),
        "heartbeat_summary": status.get("heartbeat_summary", {}),
        "node_registry_summary": (status.get("heartbeat_summary", {}) or {}).get("node_registry_summary", {}),
        "node_health_summary": (status.get("heartbeat_summary", {}) or {}).get("node_health_summary", {}),
        "hermes_summary": status.get("hermes_summary", {}),
        "autoresearch_summary": status.get("autoresearch_summary", {}),
        "eval_outcome_summary": status.get("eval_outcome_summary", {}),
        "eval_profile_summary": status.get("eval_profile_summary", {}),
        "browser_control_allowlist_summary": status.get("browser_control_allowlist_summary", {}),
        "browser_action_summary": status.get("browser_action_summary", {}),
        "voice_session_summary": status.get("voice_session_summary", {}),
        "task_lease_summary": task_lease_summary,
        "skill_scheduler_summary": skill_scheduler_summary,
        "research_backend_summary": build_research_backend_summary(root=root),
        "evidence_bundle_summary": build_evidence_bundle_summary(root=root),
        "vault_summary": build_vault_export_summary(root=root),
        "experiment_summary": build_experiment_summary(root=root),
        "task_envelope_summary": status.get("task_envelope_summary", {}),
        "candidate_promotion_summary": status.get("candidate_promotion_summary", {}),
        "provenance_summary": status.get("provenance_summary", {}),
        "replay_summary": status.get("replay_summary", {}),
        "multimodal_summary": status.get("multimodal_summary", {}),
        "memory_discipline_summary": status.get("memory_discipline_summary", {}),
        "promotion_governance_summary": status.get("promotion_governance_summary", {}),
        "rollback_summary": status.get("rollback_summary", {}),
        "approval_session_summary": status.get("approval_session_summary", {}),
        "subsystem_contract_summary": status.get("subsystem_contract_summary", {}),
        "trajectory_summary": status.get("trajectory_summary", {}),
        "operator_profile_summary": status.get("operator_profile_summary", {}),
        "policy_surface_summary": status.get("policy_surface_summary", {}),
        "active_nodes_summary": runtime_5_2_prep["active_nodes_summary"],
        "backend_health_summary": runtime_5_2_prep["backend_health_summary"],
        "accelerator_summary": runtime_5_2_prep["accelerator_summary"],
        "degraded_state_summary": runtime_5_2_prep["degraded_state_summary"],
        "reroute_summary": runtime_5_2_prep["reroute_summary"],
        "eval_scaffolding_summary": eval_scaffolding_summary,
        "latest_reply_ingress": (status.get("operator_control_plane", {}) or {}).get("latest_reply_ingress"),
        "latest_reply_ingress_run": (status.get("operator_control_plane", {}) or {}).get("latest_reply_ingress_run"),
        "latest_reply_transport_cycle": (status.get("operator_control_plane", {}) or {}).get("latest_reply_transport_cycle"),
        "latest_reply_transport_replay": (status.get("operator_control_plane", {}) or {}).get("latest_reply_transport_replay"),
        "latest_outbound_packet": (status.get("operator_control_plane", {}) or {}).get("latest_outbound_packet"),
        "latest_imported_reply_message": (status.get("operator_control_plane", {}) or {}).get("latest_imported_reply_message"),
        "latest_bridge_cycle": (status.get("operator_control_plane", {}) or {}).get("latest_bridge_cycle"),
        "latest_bridge_replay": (status.get("operator_control_plane", {}) or {}).get("latest_bridge_replay"),
        "reply_transport_replay_summary": (status.get("operator_control_plane", {}) or {}).get("reply_transport_replay_summary", {}),
        "bridge_replay_summary": (status.get("operator_control_plane", {}) or {}).get("bridge_replay_summary", {}),
        "doctor_summary": (status.get("operator_control_plane", {}) or {}).get("doctor_summary", {}),
        "latest_doctor_report": (status.get("operator_control_plane", {}) or {}).get("latest_doctor_report"),
        "latest_remediation_plan": (status.get("operator_control_plane", {}) or {}).get("latest_remediation_plan"),
        "latest_remediation_run": (status.get("operator_control_plane", {}) or {}).get("latest_remediation_run"),
        "remediation_run_summary": (status.get("operator_control_plane", {}) or {}).get("remediation_run_summary", {}),
        "latest_recovery_cycle": (status.get("operator_control_plane", {}) or {}).get("latest_recovery_cycle"),
        "recent_recovery_cycles": (status.get("operator_control_plane", {}) or {}).get("recent_recovery_cycles", []),
        "recovery_cycle_summary": (status.get("operator_control_plane", {}) or {}).get("recovery_cycle_summary", {}),
        "latest_control_plane_checkpoint": (status.get("operator_control_plane", {}) or {}).get("latest_control_plane_checkpoint"),
        "recent_control_plane_checkpoints": (status.get("operator_control_plane", {}) or {}).get("recent_control_plane_checkpoints", []),
        "control_plane_checkpoint_summary": (status.get("operator_control_plane", {}) or {}).get("control_plane_checkpoint_summary", {}),
        "latest_incident_report": (status.get("operator_control_plane", {}) or {}).get("latest_incident_report"),
        "recent_incident_reports": (status.get("operator_control_plane", {}) or {}).get("recent_incident_reports", []),
        "incident_summary": (status.get("operator_control_plane", {}) or {}).get("incident_summary", {}),
        "latest_compare_reply_transport_cycles": (status.get("operator_control_plane", {}) or {}).get("latest_compare_reply_transport_cycles"),
        "latest_compare_bridge_cycles": (status.get("operator_control_plane", {}) or {}).get("latest_compare_bridge_cycles"),
        "latest_compare_control_plane_checkpoints": (status.get("operator_control_plane", {}) or {}).get("latest_compare_control_plane_checkpoints"),
        "pending_reviews": pending_reviews,
        "pending_approvals": pending_approvals,
        "candidate_apply_ready": candidate_apply_ready,
        "flowstate_waiting_promotion": flowstate_waiting,
        "control_state": status.get("control_state", {}),
        "operator_focus": operator_focus,
        "counts": {
            "pending_reviews": len(pending_reviews),
            "pending_approvals": len(pending_approvals),
            "candidate_apply_ready": len(candidate_apply_ready),
            "flowstate_waiting_promotion": len(flowstate_waiting),
            "blocked": len(status.get("blocked", [])),
            "ready_to_ship": len(status.get("ready_to_ship", [])),
            "shipped": len(status.get("shipped", [])),
            "impacted_outputs": len(status.get("impacted_outputs", [])),
            "revoked_outputs": len(status.get("revoked_outputs", [])),
            "revoked_artifacts": len(status.get("revoked_artifacts", [])),
            "controls": status.get("counts", {}).get("controls", 0),
            "paused_controls": status.get("counts", {}).get("paused_controls", 0),
            "stopped_controls": status.get("counts", {}).get("stopped_controls", 0),
            "degraded_controls": status.get("counts", {}).get("degraded_controls", 0),
            "revoked_controls": status.get("counts", {}).get("revoked_controls", 0),
            "operator_action_executions": status.get("counts", {}).get("operator_action_executions", 0),
            "operator_queue_runs": status.get("counts", {}).get("operator_queue_runs", 0),
            "operator_bulk_runs": status.get("counts", {}).get("operator_bulk_runs", 0),
            "operator_task_interventions": status.get("counts", {}).get("operator_task_interventions", 0),
            "operator_safe_autofix_runs": status.get("counts", {}).get("operator_safe_autofix_runs", 0),
            "operator_reply_ingress": status.get("counts", {}).get("operator_reply_ingress", 0),
            "operator_reply_ingress_results": status.get("counts", {}).get("operator_reply_ingress_results", 0),
            "operator_reply_ingress_runs": status.get("counts", {}).get("operator_reply_ingress_runs", 0),
            "operator_reply_transport_cycles": status.get("counts", {}).get("operator_reply_transport_cycles", 0),
            "operator_reply_transport_replay_plans": status.get("counts", {}).get("operator_reply_transport_replay_plans", 0),
            "operator_reply_transport_replays": status.get("counts", {}).get("operator_reply_transport_replays", 0),
            "operator_outbound_packets": status.get("counts", {}).get("operator_outbound_packets", 0),
            "operator_imported_reply_messages": status.get("counts", {}).get("operator_imported_reply_messages", 0),
            "operator_bridge_cycles": status.get("counts", {}).get("operator_bridge_cycles", 0),
            "operator_bridge_replay_plans": status.get("counts", {}).get("operator_bridge_replay_plans", 0),
            "operator_bridge_replays": status.get("counts", {}).get("operator_bridge_replays", 0),
            "operator_doctor_reports": status.get("counts", {}).get("operator_doctor_reports", 0),
            "operator_remediation_plans": status.get("counts", {}).get("operator_remediation_plans", 0),
            "operator_remediation_runs": status.get("counts", {}).get("operator_remediation_runs", 0),
            "operator_remediation_step_runs": status.get("counts", {}).get("operator_remediation_step_runs", 0),
            "operator_recovery_cycles": status.get("counts", {}).get("operator_recovery_cycles", 0),
            "operator_control_plane_checkpoints": status.get("counts", {}).get("operator_control_plane_checkpoints", 0),
            "operator_incident_reports": status.get("counts", {}).get("operator_incident_reports", 0),
            "operator_incident_snapshots": status.get("counts", {}).get("operator_incident_snapshots", 0),
            "backend_health": runtime_5_2_prep["backend_health_summary"]["snapshot_count"],
            "accelerators": runtime_5_2_prep["accelerator_summary"]["summary_count"],
            "eval_runs": eval_scaffolding_summary["eval_run_count"],
            "registered_nodes": ((status.get("heartbeat_summary", {}) or {}).get("node_registry_summary", {}) or {}).get("registered_node_count", 0),
            "online_nodes": ((status.get("heartbeat_summary", {}) or {}).get("node_health_summary", {}) or {}).get("online_node_count", 0),
            "burst_online_nodes": ((status.get("heartbeat_summary", {}) or {}).get("node_health_summary", {}) or {}).get("burst_online_count", 0),
            "task_leases": task_lease_summary.get("task_lease_count", 0),
            "active_task_leases": task_lease_summary.get("active_task_lease_count", 0),
            "expired_task_leases": task_lease_summary.get("expired_task_lease_count", 0),
            "approved_skills": skill_scheduler_summary.get("registry_summary", {}).get("approved_skill_count", 0),
            "skill_candidates": skill_scheduler_summary.get("registry_summary", {}).get("skill_candidate_summary", {}).get("skill_candidate_count", 0),
        },
    }
    snapshot["ui_view_summary"] = render_operator_views(
        root=root,
        source_name="operator_snapshot",
        source_payload=snapshot,
    )

    out_path = root / "state" / "logs" / "operator_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an operator-facing dashboard snapshot.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    snapshot = build_operator_snapshot(root)
    print(json.dumps(snapshot, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
