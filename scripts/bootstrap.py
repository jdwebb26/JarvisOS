#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
if str(DEFAULT_ROOT) not in sys.path:
    sys.path.insert(0, str(DEFAULT_ROOT))

from runtime.dashboard.runtime_5_2_prep import ensure_runtime_5_2_prep_state
from runtime.core.heartbeat_reports import write_node_heartbeat
from runtime.core.node_registry import ensure_default_nodes

ROOT_MARKERS = [
    "AGENTS.md",
    "scripts/bootstrap.py",
    "docs/spec/01_Jarvis_OS_v5_1_Rebuild_Spec.md",
]

REQUIRED_DIRS = [
    "docs",
    "config",
    "scripts",
    "runtime",
    "runtime/gateway",
    "runtime/core",
    "runtime/auditor",
    "runtime/reporter",
    "runtime/flowstate",
    "runtime/dashboard",
    "runtime/controls",
    "runtime/integrations",
    "runtime/researchlab",
    "runtime/evals",
    "runtime/ralph",
    "runtime/memory",
    "services",
    "services/discord",
    "services/models",
    "services/tools",
    "services/memory",
    "services/approvals",
    "state",
    "state/tasks",
    "state/artifacts",
    "state/approvals",
    "state/logs",
    "state/heartbeat",
    "state/heartbeat_reports",
    "state/browser_control_allowlists",
    "state/voice_sessions",
    "state/events",
    "state/memory",
    "state/flowstate_sources",
    "state/reviews",
    "state/controls",
    "state/control_actions",
    "state/control_events",
    "state/control_blocked_actions",
    "state/hermes_requests",
    "state/hermes_results",
    "state/research_campaigns",
    "state/experiment_runs",
    "state/metric_results",
    "state/research_recommendations",
    "state/lab_run_requests",
    "state/lab_run_results",
    "state/strategy_diversity_maps",
    "state/run_traces",
    "state/eval_runs",
    "state/eval_cases",
    "state/eval_results",
    "state/eval_outcomes",
    "state/eval_profiles",
    "state/model_registry_entries",
    "state/capability_profiles",
    "state/routing_policies",
    "state/routing_overrides",
    "state/routing_requests",
    "state/routing_decisions",
    "state/provider_adapter_results",
    "state/backend_assignments",
    "state/backend_execution_requests",
    "state/backend_execution_results",
    "state/backend_health",
    "state/accelerators",
    "state/nodes",
    "state/worker_heartbeats",
    "state/token_budgets",
    "state/degradation_policies",
    "state/degradation_events",
    "state/candidate_records",
    "state/candidate_validations",
    "state/promotion_decisions",
    "state/rejection_decisions",
    "state/candidate_revocations",
    "state/task_provenance",
    "state/artifact_provenance",
    "state/promotion_provenance",
    "state/routing_provenance",
    "state/decision_provenance",
    "state/publish_provenance",
    "state/rollback_provenance",
    "state/memory_provenance",
    "state/replay_plans",
    "state/replay_executions",
    "state/replay_results",
    "state/modality_contracts",
    "state/output_dependencies",
    "state/rollback_plans",
    "state/rollback_executions",
    "state/revocation_impacts",
    "state/approval_sessions",
    "state/approval_decision_contexts",
    "state/approval_resume_tokens",
    "state/subsystem_contracts",
    "state/trajectories",
    "state/operator_profiles",
    "state/consolidation_runs",
    "state/digest_artifact_links",
    "state/memory_candidates",
    "state/memory_entries",
    "state/memory_retrievals",
    "state/memory_validations",
    "state/memory_promotion_decisions",
    "state/memory_rejection_decisions",
    "state/memory_revocation_decisions",
    "state/operator_action_executions",
    "state/operator_queue_runs",
    "state/operator_bulk_runs",
    "state/operator_task_interventions",
    "state/operator_safe_autofix_runs",
    "state/operator_reply_plans",
    "state/operator_reply_applies",
    "state/operator_reply_ingress",
    "state/operator_reply_ingress_results",
    "state/operator_reply_ingress_runs",
    "state/operator_reply_messages",
    "state/operator_reply_transport_cycles",
    "state/operator_reply_transport_replay_plans",
    "state/operator_reply_transport_replays",
    "state/operator_outbound_packets",
    "state/operator_imported_reply_messages",
    "state/operator_gateway_inbound_messages",
    "state/operator_bridge_cycles",
    "state/operator_bridge_replay_plans",
    "state/operator_bridge_replays",
    "state/operator_doctor_reports",
    "state/operator_remediation_plans",
    "state/operator_remediation_runs",
    "state/operator_remediation_step_runs",
    "state/operator_recovery_cycles",
    "state/operator_control_plane_checkpoints",
    "state/operator_incident_reports",
    "state/operator_incident_snapshots",
    "workspace",
    "workspace/inbox",
    "workspace/work",
    "workspace/out",
    "systemd",
    "tests",
]

AUTO_CREATE_DIRS = [
    "state",
    "state/tasks",
    "state/artifacts",
    "state/approvals",
    "state/logs",
    "state/heartbeat",
    "state/heartbeat_reports",
    "state/browser_control_allowlists",
    "state/voice_sessions",
    "state/events",
    "state/memory",
    "state/flowstate_sources",
    "state/reviews",
    "state/controls",
    "state/control_actions",
    "state/control_events",
    "state/control_blocked_actions",
    "state/hermes_requests",
    "state/hermes_results",
    "state/research_campaigns",
    "state/experiment_runs",
    "state/metric_results",
    "state/research_recommendations",
    "state/lab_run_requests",
    "state/lab_run_results",
    "state/strategy_diversity_maps",
    "state/run_traces",
    "state/eval_runs",
    "state/eval_cases",
    "state/eval_results",
    "state/eval_outcomes",
    "state/eval_profiles",
    "state/model_registry_entries",
    "state/capability_profiles",
    "state/routing_policies",
    "state/routing_overrides",
    "state/routing_requests",
    "state/routing_decisions",
    "state/provider_adapter_results",
    "state/backend_assignments",
    "state/backend_execution_requests",
    "state/backend_execution_results",
    "state/backend_health",
    "state/accelerators",
    "state/nodes",
    "state/worker_heartbeats",
    "state/token_budgets",
    "state/degradation_policies",
    "state/degradation_events",
    "state/candidate_records",
    "state/candidate_validations",
    "state/promotion_decisions",
    "state/rejection_decisions",
    "state/candidate_revocations",
    "state/task_provenance",
    "state/artifact_provenance",
    "state/promotion_provenance",
    "state/routing_provenance",
    "state/decision_provenance",
    "state/publish_provenance",
    "state/rollback_provenance",
    "state/memory_provenance",
    "state/replay_plans",
    "state/replay_executions",
    "state/replay_results",
    "state/modality_contracts",
    "state/output_dependencies",
    "state/rollback_plans",
    "state/rollback_executions",
    "state/revocation_impacts",
    "state/approval_sessions",
    "state/approval_decision_contexts",
    "state/approval_resume_tokens",
    "state/subsystem_contracts",
    "state/trajectories",
    "state/operator_profiles",
    "state/consolidation_runs",
    "state/digest_artifact_links",
    "state/memory_candidates",
    "state/memory_entries",
    "state/memory_retrievals",
    "state/memory_validations",
    "state/memory_promotion_decisions",
    "state/memory_rejection_decisions",
    "state/memory_revocation_decisions",
    "state/operator_action_executions",
    "state/operator_queue_runs",
    "state/operator_bulk_runs",
    "state/operator_task_interventions",
    "state/operator_safe_autofix_runs",
    "state/operator_reply_plans",
    "state/operator_reply_applies",
    "state/operator_reply_ingress",
    "state/operator_reply_ingress_results",
    "state/operator_reply_ingress_runs",
    "state/operator_reply_messages",
    "state/operator_reply_transport_cycles",
    "state/operator_reply_transport_replay_plans",
    "state/operator_reply_transport_replays",
    "state/operator_outbound_packets",
    "state/operator_imported_reply_messages",
    "state/operator_gateway_inbound_messages",
    "state/operator_bridge_cycles",
    "state/operator_bridge_replay_plans",
    "state/operator_bridge_replays",
    "state/operator_doctor_reports",
    "state/operator_remediation_plans",
    "state/operator_remediation_runs",
    "state/operator_remediation_step_runs",
    "state/operator_recovery_cycles",
    "state/operator_control_plane_checkpoints",
    "state/operator_incident_reports",
    "state/operator_incident_snapshots",
    "workspace",
    "workspace/inbox",
    "workspace/work",
    "workspace/out",
]

EXAMPLE_CONFIG_MAP = [
    ("config/app.example.yaml", "config/app.yaml"),
    ("config/channels.example.yaml", "config/channels.yaml"),
    ("config/models.example.yaml", "config/models.yaml"),
    ("config/policies.example.yaml", "config/policies.yaml"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def looks_like_repo_root(path: Path) -> bool:
    return all((path / marker).exists() for marker in ROOT_MARKERS)


def resolve_repo_root(path: Path) -> Path:
    candidate = path.expanduser().resolve()
    search_roots = [candidate, *candidate.parents]

    for root in search_roots:
        if looks_like_repo_root(root):
            return root

    for root in search_roots:
        nested = root / "jarvis-v5"
        if looks_like_repo_root(nested):
            return nested

    return candidate


def ensure_dir(path: Path) -> bool:
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True)
    return existed


def ensure_dirs(root: Path, rel_paths: list[str]) -> tuple[list[str], list[str]]:
    created_dirs: list[str] = []
    existing_dirs: list[str] = []

    for rel in rel_paths:
        p = root / rel
        existed = ensure_dir(p)
        if existed:
            existing_dirs.append(rel)
        else:
            created_dirs.append(rel)

    return created_dirs, existing_dirs


def maybe_copy(src: Path, dst: Path, force: bool) -> str:
    if not src.exists():
        return "missing_source"

    if dst.exists() and dst.stat().st_size > 0 and not force:
        return "kept_existing"

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return "copied"


def ensure_config_skeletons(root: Path, *, force: bool = False) -> dict[str, str]:
    copied_configs: dict[str, str] = {}
    for src_rel, dst_rel in EXAMPLE_CONFIG_MAP:
        copied_configs[dst_rel] = maybe_copy(root / src_rel, root / dst_rel, force=force)
    return copied_configs


def ensure_foundation(root: Path, *, force: bool = False) -> dict[str, object]:
    resolved_root = resolve_repo_root(root)
    created_dirs, existing_dirs = ensure_dirs(resolved_root, AUTO_CREATE_DIRS)
    copied_configs = ensure_config_skeletons(resolved_root, force=force)
    runtime_prep = ensure_runtime_5_2_prep_state(root=resolved_root)
    default_nodes = ensure_default_nodes(root=resolved_root)
    write_node_heartbeat(
        node_name="NIMO",
        actor="system",
        lane="bootstrap",
        backend_summary=["qwen_planner", "qwen_executor", "operator"],
        model_family_summary=["qwen"],
        capability_summary={"bootstrap_seed": True},
        metadata={"scaffolding_only": True, "seed_source": "bootstrap"},
        root=resolved_root,
    )
    return {
        "root": str(resolved_root),
        "created_dirs": created_dirs,
        "existing_dirs_count": len(existing_dirs),
        "copied_configs": copied_configs,
        "runtime_5_2_prep": runtime_prep,
        "default_nodes": [row.to_dict() for row in default_nodes],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap Jarvis v5 scaffold.")
    parser.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        help="Project root path",
    )
    parser.add_argument(
        "--copy-examples",
        action="store_true",
        help="Retained for compatibility; missing live config skeletons are copied by default.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite when used with --copy-examples",
    )
    args = parser.parse_args()

    requested_root = Path(args.root).expanduser().resolve()
    root = resolve_repo_root(requested_root)

    created_dirs, existing_dirs = ensure_dirs(root, REQUIRED_DIRS)
    copied_configs = ensure_config_skeletons(root, force=args.force)
    runtime_prep = ensure_runtime_5_2_prep_state(root=root)
    default_nodes = ensure_default_nodes(root=root)
    write_node_heartbeat(
        node_name="NIMO",
        actor="system",
        lane="bootstrap",
        backend_summary=["qwen_planner", "qwen_executor", "operator"],
        model_family_summary=["qwen"],
        capability_summary={"bootstrap_seed": True},
        metadata={"scaffolding_only": True, "seed_source": "bootstrap"},
        root=root,
    )

    report = {
        "ok": True,
        "timestamp_utc": now_iso(),
        "root": str(root),
        "requested_root": str(requested_root),
        "created_dirs": created_dirs,
        "existing_dirs_count": len(existing_dirs),
        "copy_examples_enabled": True,
        "copy_examples_requested": args.copy_examples,
        "copied_configs": copied_configs,
        "runtime_5_2_prep": runtime_prep,
        "default_nodes": [row.to_dict() for row in default_nodes],
    }

    report_path = root / "state" / "logs" / "bootstrap_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
