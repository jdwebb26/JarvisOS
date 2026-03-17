#!/usr/bin/env python3
from __future__ import annotations

import importlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile
from unittest.mock import patch
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from scripts.bootstrap import ensure_foundation, resolve_repo_root

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.dashboard.runtime_5_2_prep import (
    build_accelerator_summary,
    build_backend_health_summary,
    build_degraded_state_summary,
    ensure_runtime_5_2_prep_state,
)
from runtime.core.heartbeat_reports import build_node_health_summary
from runtime.core.node_registry import ensure_default_nodes
from runtime.core.task_lease import build_task_lease_summary
from runtime.core.workspace_registry import summarize_workspace_registry
from runtime.integrations.research_backends import build_research_backend_summary
from runtime.integrations.hermes_adapter import build_hermes_summary
from runtime.integrations.lane_activation import summarize_lane_activation
from runtime.integrations.autoresearch_adapter import build_autoresearch_summary
from runtime.memory.vault_export import build_vault_export_summary
from runtime.researchlab.experiment_store import build_experiment_summary
from runtime.researchlab.evidence_bundle import build_evidence_bundle_summary
from runtime.adaptation_lab.summary import summarize_adaptation_lab
from runtime.integrations.shadowbroker_adapter import (
    fetch_shadowbroker_snapshot,
    summarize_shadowbroker_backend,
    validate_shadowbroker_runtime,
)
from runtime.optimizer.eval_gate import summarize_optimizer_lane
from runtime.world_ops.summary import build_world_ops_summary
from runtime.skills.skill_scheduler import build_skill_scheduler_summary
from runtime.evals.replay_runner import build_eval_run_summary
from runtime.browser.reporting import build_browser_action_summary
from runtime.core.a2a_policy import build_a2a_policy_summary
from runtime.core.routing import (
    ensure_default_routing_contracts,
    legal_candidate_pool_for_runtime_policy_block,
    load_runtime_routing_policy,
    resolve_runtime_route_policy,
    runtime_routing_policy_path,
)
from runtime.core.status import (
    build_discord_live_ops_summary,
    build_extension_lane_status_summary,
    build_local_model_lane_proof_summary,
    build_openclaw_discord_bridge_summary,
    build_openclaw_discord_session_summary,
    build_routing_control_plane_summary,
)
from runtime.core.degradation_policy import build_degradation_summary
from runtime.core.heartbeat_reports import build_heartbeat_report_summary
from runtime.core.routing import build_model_registry_summary

ROOT = resolve_repo_root(Path(__file__).resolve().parents[1])
WORKSPACE = ROOT / "workspace"

REQUIRED_DIRS = [
    "config",
    "docs",
    "runtime",
    "runtime/core",
    "runtime/dashboard",
    "runtime/dashboard/renderers",
    "runtime/executor",
    "runtime/flowstate",
    "runtime/gateway",
    "runtime/controls",
    "runtime/integrations",
    "runtime/researchlab",
    "runtime/evals",
    "runtime/ralph",
    "runtime/memory",
    "runtime/world_ops",
    "runtime/adaptation_lab",
    "runtime/optimizer",
    "runtime/skills",
    "runtime/ui",
    "scripts",
    "state",
    "state/approvals",
    "state/artifacts",
    "state/events",
    "state/flowstate_sources",
    "state/heartbeat",
    "state/heartbeat_reports",
    "state/browser_control_allowlists",
    "state/voice_sessions",
    "state/logs",
    "state/memory",
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
    "state/research_queries",
    "state/evidence_bundles",
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
    "state/task_leases",
    "state/workspaces",
    "state/world_ops_feeds",
    "state/world_ops_events",
    "state/world_ops_briefs",
    "state/world_ops_snapshots",
    "state/shadowbroker_snapshots",
    "state/shadowbroker_events",
    "state/shadowbroker_backend_health",
    "state/shadowbroker_briefs",
    "state/lane_activation",
    "state/lane_activation_runs",
    "state/adaptation_jobs",
    "state/adaptation_datasets",
    "state/adaptation_results",
    "state/optimizer_runs",
    "state/optimizer_variants",
    "state/experiments",
    "state/skills",
    "state/skill_candidates",
    "state/ui_views",
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
    "state/tasks",
    "workspace",
    "workspace/vault",
    "workspace/vault/artifacts",
    "workspace/vault/briefs",
    "workspace/inbox",
    "workspace/out",
    "workspace/work",
]

REQUIRED_FILES = [
    "README.md",
    "docs/deployment.md",
    "docs/external_lane_activation.md",
    "docs/operator_go_live_checklist.md",
    "docs/operations.md",
    "docs/runtime-regression-runbook.md",
    ".env.external-lanes.example",
    "config/app.example.yaml",
    "config/channels.example.yaml",
    "config/models.example.yaml",
    "config/policies.example.yaml",
    "scripts/bootstrap.py",
    "scripts/doctor.py",
    "scripts/generate_config.py",
    "scripts/operator_checkpoint_action_pack.py",
    "scripts/operator_activate_external_lanes.py",
    "scripts/operator_activate_local_model_lanes.py",
    "scripts/operator_discord_runtime_check.py",
    "scripts/operator_go_live_gate.py",
    "scripts/repair_discord_sessions.py",
    "scripts/operator_action_executor.py",
    "scripts/operator_action_ledger.py",
    "scripts/operator_action_explain.py",
    "scripts/operator_bulk_action_runner.py",
    "scripts/operator_command_center.py",
    "scripts/operator_decision_inbox.py",
    "scripts/operator_reply_plan.py",
    "scripts/operator_apply_reply.py",
    "scripts/operator_reply_preview.py",
    "scripts/operator_reply_ingest.py",
    "scripts/operator_reply_ingress_runner.py",
    "scripts/operator_outbound_prompt.py",
    "scripts/operator_enqueue_reply_message.py",
    "scripts/operator_reply_ack.py",
    "scripts/operator_reply_transport_cycle.py",
    "scripts/operator_list_reply_transport_cycles.py",
    "scripts/operator_explain_reply_transport_cycle.py",
    "scripts/operator_compare_reply_transport_cycles.py",
    "scripts/operator_replay_transport_cycle.py",
    "scripts/operator_publish_outbound_packet.py",
    "scripts/operator_import_reply_message.py",
    "scripts/operator_list_outbound_packets.py",
    "scripts/operator_list_imported_reply_messages.py",
    "scripts/operator_bridge_cycle.py",
    "scripts/operator_list_bridge_cycles.py",
    "scripts/operator_explain_bridge_cycle.py",
    "scripts/operator_compare_bridge_cycles.py",
    "scripts/operator_replay_bridge_cycle.py",
    "scripts/operator_doctor.py",
    "scripts/operator_plan_remediation.py",
    "scripts/operator_explain_doctor_issue.py",
    "scripts/operator_list_doctor_reports.py",
    "scripts/operator_run_remediation_plan.py",
    "scripts/operator_list_remediation_runs.py",
    "scripts/operator_explain_remediation_run.py",
    "scripts/operator_recovery_cycle.py",
    "scripts/operator_list_recovery_cycles.py",
    "scripts/operator_explain_recovery_cycle.py",
    "scripts/operator_checkpoint_control_plane.py",
    "scripts/operator_list_control_plane_checkpoints.py",
    "scripts/operator_explain_control_plane_checkpoint.py",
    "scripts/operator_compare_control_plane_checkpoints.py",
    "scripts/operator_detect_incidents.py",
    "scripts/operator_list_incident_reports.py",
    "scripts/operator_explain_incident_report.py",
    "scripts/operator_decision_shortlist.py",
    "scripts/operator_compare_inbox.py",
    "scripts/operator_list_actions.py",
    "scripts/operator_list_tasks.py",
    "scripts/operator_list_runs.py",
    "scripts/operator_decision_manifest.py",
    "scripts/operator_compare_packs.py",
    "scripts/operator_compare_triage.py",
    "scripts/operator_triage_pack.py",
    "scripts/operator_task_intervene.py",
    "scripts/operator_safe_autofix.py",
    "scripts/operator_resume_action.py",
    "scripts/operator_queue_runner.py",
    "scripts/overnight_operator_run.py",
    "scripts/operator_handoff_pack.py",
    "scripts/smoke_test.py",
    "scripts/validate.py",
    "docs/jarvis_5_2_runtime_migration.md",
    "runtime/core/intake.py",
    "runtime/core/decision_router.py",
    "runtime/core/routing.py",
    "runtime/core/execution_contracts.py",
    "runtime/core/backend_assignments.py",
    "runtime/core/node_registry.py",
    "runtime/core/task_lease.py",
    "runtime/skills/registry.py",
    "runtime/skills/skill_store.py",
    "runtime/skills/skill_candidate.py",
    "runtime/skills/skill_scheduler.py",
    "runtime/ui/a2ui_schema.py",
    "runtime/ui/component_catalog.py",
    "runtime/dashboard/renderers/a2ui_renderer.py",
    "runtime/memory/vault_export.py",
    "runtime/memory/vault_index.py",
    "runtime/memory/brief_builder.py",
    "runtime/core/provenance_store.py",
    "runtime/core/replay_store.py",
    "runtime/core/modality_contracts.py",
    "runtime/core/candidate_store.py",
    "runtime/core/rollback_store.py",
    "runtime/core/approval_sessions.py",
    "runtime/core/subsystem_contracts.py",
    "runtime/core/approval_store.py",
    "runtime/controls/control_store.py",
    "runtime/integrations/hermes_adapter.py",
    "runtime/integrations/autoresearch_adapter.py",
    "runtime/integrations/research_backends.py",
    "runtime/integrations/searxng_client.py",
    "runtime/integrations/search_normalizer.py",
    "runtime/researchlab/runner.py",
    "runtime/researchlab/evidence_bundle.py",
    "runtime/evals/trace_store.py",
    "runtime/evals/replay_runner.py",
    "runtime/evals/scorers.py",
    "runtime/researchlab/experiment_store.py",
    "runtime/researchlab/optimizer.py",
    "runtime/ralph/consolidator.py",
    "runtime/memory/governance.py",
    "runtime/core/review_store.py",
    "runtime/core/publish_complete.py",
    "runtime/core/run_runtime_regression_pack.py",
    "runtime/gateway/complete_from_artifact.py",
    "runtime/gateway/hermes_execute.py",
    "runtime/gateway/autoresearch_campaign.py",
    "runtime/gateway/replay_eval.py",
    "runtime/gateway/ralph_consolidate.py",
    "runtime/gateway/memory_retrieve.py",
    "runtime/gateway/memory_decision.py",
    "runtime/gateway/discord_intake.py",
    "runtime/dashboard/operator_snapshot.py",
    "runtime/dashboard/runtime_5_2_prep.py",
]

KEY_MODULES = [
    "runtime.core.intake",
    "runtime.core.decision_router",
    "runtime.core.routing",
    "runtime.core.node_registry",
    "runtime.core.task_lease",
    "runtime.skills.registry",
    "runtime.skills.skill_store",
    "runtime.skills.skill_candidate",
    "runtime.skills.skill_scheduler",
    "runtime.ui.a2ui_schema",
    "runtime.ui.component_catalog",
    "runtime.dashboard.renderers.a2ui_renderer",
    "runtime.memory.vault_export",
    "runtime.memory.vault_index",
    "runtime.memory.brief_builder",
    "runtime.core.candidate_store",
    "runtime.core.rollback_store",
    "runtime.core.approval_sessions",
    "runtime.core.subsystem_contracts",
    "runtime.core.review_store",
    "runtime.core.approval_store",
    "runtime.controls.control_store",
    "runtime.integrations.hermes_adapter",
    "runtime.integrations.autoresearch_adapter",
    "runtime.integrations.research_backends",
    "runtime.integrations.searxng_client",
    "runtime.integrations.search_normalizer",
    "runtime.researchlab.runner",
    "runtime.researchlab.evidence_bundle",
    "runtime.evals.trace_store",
    "runtime.evals.replay_runner",
    "runtime.evals.scorers",
    "runtime.researchlab.experiment_store",
    "runtime.researchlab.optimizer",
    "runtime.optimizer.dspy_runner",
    "runtime.optimizer.variant_store",
    "runtime.optimizer.eval_gate",
    "runtime.ralph.consolidator",
    "runtime.memory.governance",
    "runtime.core.publish_complete",
    "runtime.core.run_runtime_regression_pack",
    "runtime.gateway.complete_from_artifact",
    "runtime.gateway.hermes_execute",
    "runtime.gateway.autoresearch_campaign",
    "runtime.gateway.replay_eval",
    "runtime.gateway.ralph_consolidate",
    "runtime.gateway.memory_retrieve",
    "runtime.gateway.memory_decision",
    "runtime.dashboard.operator_snapshot",
]

CONFIG_FILES = [
    "config/app.yaml",
    "config/channels.yaml",
    "config/models.yaml",
    "config/policies.yaml",
]

EXAMPLE_CONFIG_FILES = [
    "config/app.example.yaml",
    "config/channels.example.yaml",
    "config/models.example.yaml",
    "config/policies.example.yaml",
]

QWEN_HINTS = ["family: qwen3.5", "qwen_only: true", "Qwen3.5-"]
EXPECTED_CHANNEL_KEYS = ["jarvis", "tasks", "outputs", "review", "audit", "code_review", "flowstate"]
_LOCALHOST_HOSTS = {"127.0.0.1", "localhost", "::1"}
_URL_RE = re.compile(r"https?://([^/\s:]+)")
_SHADOWBROKER_STALE_SNAPSHOT_SECONDS = int(os.environ.get("JARVIS_SHADOWBROKER_STALE_SNAPSHOT_SECONDS") or 3600)


@dataclass
class Finding:
    status: str
    category: str
    message: str
    remediation: str = ""
    details: str = ""

    def to_dict(self) -> dict[str, str]:
        payload = {
            "status": self.status,
            "category": self.category,
            "message": self.message,
        }
        if self.remediation:
            payload["remediation"] = self.remediation
        if self.details:
            payload["details"] = self.details
        return payload


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _add(finding_list: list[Finding], status: str, category: str, message: str, remediation: str = "", details: str = "") -> None:
    finding_list.append(Finding(status=status, category=category, message=message, remediation=remediation, details=details))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _write_probe(directory: Path) -> str | None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fd, probe_path = tempfile.mkstemp(prefix=".preflight_", dir=str(directory))
        os.close(fd)
        Path(probe_path).unlink(missing_ok=True)
        return None
    except Exception as exc:
        return str(exc)


def _config_text(root: Path, rel: str) -> str:
    path = root / rel
    if not path.exists():
        return ""
    return _read_text(path)


def validate_runtime_routing_policy_config(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    ensure_default_routing_contracts(root)
    path = runtime_routing_policy_path(root=root)
    if not path.exists():
        _add(
            findings,
            "pass",
            "config",
            "Optional runtime routing policy file is absent; built-in routing defaults remain active.",
            details=str(path),
        )
        return findings
    try:
        payload = load_runtime_routing_policy(root=root)
    except Exception as exc:
        _add(
            findings,
            "fail",
            "config",
            "Runtime routing policy config is invalid.",
            "Fix `config/runtime_routing_policy.json` so validate can confirm routing policy before runtime use.",
            str(exc),
        )
        return findings
    _add(
        findings,
        "pass",
        "config",
        "Runtime routing policy config is valid.",
        details=f"path={path} schema_version={payload.get('schema_version')}",
    )
    semantic_blocks: list[tuple[str, Optional[str], Optional[str], str]] = [
        ("defaults", None, None, "general"),
    ]
    semantic_blocks.extend(("workload", None, None, name) for name in sorted((payload.get("workload_policies") or {}).keys()))
    semantic_blocks.extend(("agent", name, None, "general") for name in sorted((payload.get("agent_policies") or {}).keys()))
    semantic_blocks.extend(("channel", None, name, "general") for name in sorted((payload.get("channel_overrides") or {}).keys()))
    for kind, agent_id, channel, workload_type in semantic_blocks:
        resolved = resolve_runtime_route_policy(
            agent_id=agent_id,
            channel=channel,
            workload_type=workload_type,
            root=root,
        )
        allowed_families = list(resolved.get("allowed_families") or ["qwen3.5"])
        pool = legal_candidate_pool_for_runtime_policy_block(
            runtime_route_policy=resolved,
            allowed_families=allowed_families,
            root=root,
        )
        label = (
            f"{kind}:{agent_id}"
            if agent_id
            else f"{kind}:{channel}"
            if channel
            else f"{kind}:{workload_type}"
        )
        if not pool["legal_entries"]:
            _add(
                findings,
                "fail",
                "config",
                f"Runtime routing policy block `{label}` has no legal candidate pool.",
                "Adjust preferred provider/model/family/host-role constraints so at least one legal candidate remains.",
                (
                    f"workload_type={workload_type} preferred_provider={resolved.get('preferred_provider')} "
                    f"preferred_model={resolved.get('preferred_model')} allowed_families={allowed_families} "
                    f"allowed_host_roles={resolved.get('allowed_host_roles')} forbidden_host_roles={resolved.get('forbidden_host_roles')}"
                ),
            )
            continue
        preferred_model = resolved.get("preferred_model")
        if preferred_model and not pool["preferred_model_entries"] and not resolved.get("allowed_fallbacks"):
            _add(
                findings,
                "fail",
                "config",
                f"Runtime routing policy block `{label}` names a preferred model with no legal candidate.",
                "Pick a preferred model that exists in the active legal candidate pool or define legal fallbacks.",
                f"preferred_model={preferred_model} legal_model_names={pool['legal_model_names']}",
            )
        preferred_provider = resolved.get("preferred_provider")
        if preferred_provider and not pool["preferred_provider_entries"]:
            _add(
                findings,
                "fail",
                "config",
                f"Runtime routing policy block `{label}` names a preferred provider with no legal candidate.",
                "Pick a preferred provider that has legal candidates under the current family/host-role policy.",
                f"preferred_provider={preferred_provider} legal_provider_ids={pool['legal_provider_ids']}",
            )
        if resolved.get("local_only") and not any(str(row.host_role or "") == "local" for row in pool["legal_entries"]):
            _add(
                findings,
                "fail",
                "config",
                f"Runtime routing policy block `{label}` is local_only but has no legal local candidate.",
                "Keep at least one active local candidate for local_only policy blocks.",
                f"legal_model_names={pool['legal_model_names']}",
            )
        allowed_fallbacks = list(resolved.get("allowed_fallbacks") or [])
        if allowed_fallbacks and not pool["fallback_entries"]:
            _add(
                findings,
                "fail",
                "config",
                f"Runtime routing policy block `{label}` names fallbacks that are not legal candidates.",
                "Keep fallback models present in the active legal candidate pool and within host-role boundaries.",
                f"allowed_fallbacks={allowed_fallbacks} legal_model_names={pool['legal_model_names']}",
            )
    return findings


def check_routing_policy_openclaw_drift(root: Path) -> list[Finding]:
    """Advisory check: detect drift between runtime_routing_policy.json and openclaw.json.

    Reuses the sync logic from sync_routing_policy_to_openclaw.py in dry-run mode.
    Emits warn-level findings when the two configs disagree on agent model assignments.
    """
    findings: list[Finding] = []
    policy_path = root / "config" / "runtime_routing_policy.json"
    openclaw_path = Path.home() / ".openclaw" / "openclaw.json"

    if not policy_path.exists() or not openclaw_path.exists():
        _add(
            findings,
            "pass",
            "drift",
            "Routing-policy ↔ openclaw.json drift check skipped (one or both files absent).",
            details=f"policy_exists={policy_path.exists()} openclaw_exists={openclaw_path.exists()}",
        )
        return findings

    try:
        from scripts.sync_routing_policy_to_openclaw import compute_sync_plan

        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        openclaw = json.loads(openclaw_path.read_text(encoding="utf-8"))
        changes = compute_sync_plan(policy, openclaw)
    except Exception as exc:
        _add(
            findings,
            "warn",
            "drift",
            "Routing-policy ↔ openclaw.json drift check failed to run.",
            "Ensure scripts/sync_routing_policy_to_openclaw.py is importable and both JSON files are valid.",
            str(exc),
        )
        return findings

    if not changes:
        _add(
            findings,
            "pass",
            "drift",
            "Routing policy and openclaw.json agent model configs are in sync.",
        )
    else:
        for change in changes:
            _add(
                findings,
                "warn",
                "drift",
                f"Routing-policy ↔ openclaw.json drift: agent `{change['agent_id']}` field `{change['field']}` "
                f"is `{change['current']}` in openclaw.json but policy wants `{change['desired']}`.",
                "Run `python3 scripts/sync_routing_policy_to_openclaw.py` to re-sync, or update the routing policy.",
                change.get("reason", ""),
            )
    return findings


# Maps routing-policy preferred_provider values to the BackendRuntime identifier
# used by backend_dispatch when the task is dispatched on the Python execution track.
_PROVIDER_TO_PYTHON_BACKEND: dict[str, str] = {
    "nvidia": "nvidia_executor",
}
# Providers handled entirely by the embedded gateway (not Python dispatch).
_GATEWAY_HANDLED_PROVIDERS: set[str] = {"qwen", "lmstudio", "local"}


def check_backend_adapter_coverage(root: Path) -> list[Finding]:
    """Advisory check: verify that every routed execution backend has a wired adapter.

    Walks agent_policies in the routing policy.  For each agent whose
    preferred_provider maps to a Python-track backend, checks that
    backend_dispatch has a wired adapter for it.  Gateway-handled providers
    (qwen/lmstudio) are skipped because they never reach Python dispatch.
    """
    findings: list[Finding] = []
    policy_path = root / "config" / "runtime_routing_policy.json"

    if not policy_path.exists():
        _add(
            findings,
            "pass",
            "backend_coverage",
            "Backend adapter coverage check skipped (routing policy absent).",
        )
        return findings

    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _add(
            findings,
            "warn",
            "backend_coverage",
            "Backend adapter coverage check failed to parse routing policy.",
            details=str(exc),
        )
        return findings

    from runtime.executor.backend_dispatch import list_registered_backends
    registry = list_registered_backends()
    wired = set(registry.get("wired") or [])
    gateway_handled = set(registry.get("gateway_handled") or [])

    agent_policies = policy.get("agent_policies") or {}
    gaps: list[str] = []

    for agent_id, ap in sorted(agent_policies.items()):
        provider = str(ap.get("preferred_provider") or "").lower()
        if not provider or provider in _GATEWAY_HANDLED_PROVIDERS:
            continue
        expected_backend = _PROVIDER_TO_PYTHON_BACKEND.get(provider)
        if expected_backend is None:
            _add(
                findings,
                "warn",
                "backend_coverage",
                f"Agent `{agent_id}` uses provider `{provider}` which has no known Python-track backend mapping.",
                "Add a mapping in _PROVIDER_TO_PYTHON_BACKEND or confirm this provider is gateway-handled.",
                f"agent_id={agent_id} preferred_provider={provider}",
            )
            continue
        if expected_backend in wired or expected_backend in gateway_handled:
            continue
        gaps.append(f"{agent_id}→{expected_backend}(provider={provider})")

    if gaps:
        for gap in gaps:
            _add(
                findings,
                "warn",
                "backend_coverage",
                f"Backend adapter gap: {gap} — routed backend has no wired adapter in backend_dispatch.",
                "Wire the adapter in runtime/executor/backend_dispatch.py or adjust the routing policy.",
                f"wired={sorted(wired)} gateway_handled={sorted(gateway_handled)}",
            )
    else:
        _add(
            findings,
            "pass",
            "backend_coverage",
            "All routed execution backends have wired adapters or are gateway-handled.",
            details=f"wired={sorted(wired)} gateway_handled={sorted(gateway_handled)}",
        )

    return findings


# Maps Python-track backends to the third-party packages they require at runtime.
_BACKEND_REQUIRED_PACKAGES: dict[str, list[str]] = {
    "nvidia_executor": ["requests"],
    "qwen_agent_bridge": ["qwen_agent", "numpy"],
}


def check_backend_dependency_health(root: Path) -> list[Finding]:
    """Advisory check: verify that Python packages required by wired backends are importable.

    Reports the active Python interpreter and, for each wired backend that has
    declared dependencies in _BACKEND_REQUIRED_PACKAGES, checks whether the
    required package can be imported.  Failures are warn-level (advisory) since
    the backend may not be actively routed.
    """
    findings: list[Finding] = []
    python_exe = sys.executable
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    _add(
        findings,
        "pass",
        "dependency_health",
        f"Validating backend dependencies under Python {python_version}.",
        details=f"executable={python_exe}",
    )

    for backend, packages in sorted(_BACKEND_REQUIRED_PACKAGES.items()):
        for package in packages:
            try:
                importlib.import_module(package)
                _add(
                    findings,
                    "pass",
                    "dependency_health",
                    f"Backend `{backend}` dependency `{package}` is importable.",
                    details=f"python={python_exe}",
                )
            except ImportError:
                _add(
                    findings,
                    "warn",
                    "dependency_health",
                    f"Backend `{backend}` dependency `{package}` is NOT importable under Python {python_version}.",
                    f"Install `{package}` into {python_exe} (`{python_exe} -m pip install {package}`) or switch to an interpreter that has it.",
                    f"python={python_exe} backend={backend} package={package}",
                )

    return findings


def _non_localhost_urls(text: str) -> list[str]:
    hosts: list[str] = []
    for match in _URL_RE.findall(text or ""):
        host = (match or "").strip().lower()
        if host and host not in _LOCALHOST_HOSTS:
            hosts.append(host)
    return sorted(set(hosts))


def _trusted_runtime_hosts(hosts: list[str]) -> tuple[list[str], list[str]]:
    trusted: list[str] = []
    untrusted: list[str] = []
    for host in hosts:
        normalized = str(host or "").strip().lower()
        if not normalized:
            continue
        try:
            ip = ipaddress.ip_address(normalized)
            if not ip.is_global:
                trusted.append(normalized)
            else:
                untrusted.append(normalized)
            continue
        except ValueError:
            pass
        if normalized.endswith(".local") or normalized.endswith(".internal") or "." not in normalized:
            trusted.append(normalized)
        else:
            untrusted.append(normalized)
    return sorted(set(trusted)), sorted(set(untrusted))


def run_validate(root: Path, *, strict: bool = False) -> dict:
    requested_root = root.expanduser().resolve()
    root = resolve_repo_root(requested_root)
    findings: list[Finding] = []
    foundation = ensure_foundation(root)
    runtime_prep = ensure_runtime_5_2_prep_state(root=root)
    default_nodes = ensure_default_nodes(root=root)

    if root.exists():
        _add(findings, "pass", "repo", "Repo root exists.", details=str(root))
    else:
        _add(findings, "fail", "repo", "Repo root does not exist.", "Run from the repo checkout or pass --root to the correct path.", str(root))

    if (root / ".git").exists():
        _add(findings, "pass", "repo", "Git metadata directory is present.")
    else:
        _add(findings, "warn", "repo", "Git metadata directory is missing.", "If this is a source export rather than a git checkout, ignore this warning.")

    if requested_root != root:
        _add(findings, "pass", "repo", "Resolved the requested path to the repo root.", details=f"requested={requested_root}")

    if foundation["created_dirs"]:
        _add(
            findings,
            "pass",
            "foundation",
            "Auto-created managed state/workspace directories.",
            details=", ".join(foundation["created_dirs"]),
        )
    if runtime_prep["seeded_files"]:
        _add(
            findings,
            "pass",
            "runtime_prep",
            "Seeded 5.2-prep backend/accelerator scaffolding files.",
            details=", ".join(runtime_prep["seeded_files"]),
        )
    if default_nodes:
        _add(
            findings,
            "pass",
            "runtime_prep",
            "Seeded node registry scaffolding.",
            details=", ".join(sorted(row.node_name for row in default_nodes)),
        )

    copied_configs = {rel: result for rel, result in foundation["copied_configs"].items() if result == "copied"}
    if copied_configs:
        _add(
            findings,
            "pass",
            "foundation",
            "Created missing live config skeletons from example files.",
            details=", ".join(sorted(copied_configs)),
        )

    for rel in REQUIRED_DIRS:
        path = root / rel
        if not path.exists():
            _add(findings, "fail", "filesystem", f"Missing required directory `{rel}`.", f"Create `{rel}` or rerun `python3 scripts/bootstrap.py --copy-examples`.")
        elif not path.is_dir():
            _add(findings, "fail", "filesystem", f"Required path `{rel}` is not a directory.", f"Replace `{rel}` with a directory.")
        else:
            _add(findings, "pass", "filesystem", f"Directory `{rel}` is present.")

    for rel in REQUIRED_FILES:
        path = root / rel
        if not path.exists():
            _add(findings, "fail", "files", f"Missing required file `{rel}`.", f"Restore `{rel}` from the repo or regenerate the deployment packet.")
        elif not path.is_file():
            _add(findings, "fail", "files", f"Required path `{rel}` is not a file.", f"Replace `{rel}` with the expected file.")
        elif path.stat().st_size == 0:
            _add(findings, "fail", "files", f"Required file `{rel}` is empty.", f"Regenerate or restore `{rel}`.")
        else:
            _add(findings, "pass", "files", f"File `{rel}` is present.")

    qwen_example_files = {
        "config/app.example.yaml",
        "config/models.example.yaml",
        "config/policies.example.yaml",
    }
    for rel in EXAMPLE_CONFIG_FILES:
        text = _config_text(root, rel)
        if not text:
            continue
        if rel in qwen_example_files and not any(hint in text for hint in QWEN_HINTS):
            _add(findings, "fail", "config", f"Example config `{rel}` is missing Qwen-family hints.", "Keep example configs explicitly Qwen-only.")
        else:
            _add(findings, "pass", "config", f"Example config `{rel}` is Qwen-oriented.")

    for rel in CONFIG_FILES:
        path = root / rel
        if not path.exists():
            _add(findings, "warn", "config", f"Live config `{rel}` is missing.", "Run `python3 scripts/generate_config.py` or copy the example config into place.")
            continue
        text = _read_text(path)
        if path.stat().st_size == 0:
            _add(findings, "fail", "config", f"Live config `{rel}` is empty.", f"Regenerate `{rel}` with `python3 scripts/generate_config.py --force`.")
            continue
        if "REPLACE_ME" in text:
            _add(findings, "warn", "config", f"Live config `{rel}` still contains placeholder values.", "Fill in real Discord or environment-specific values before deployment.")
        else:
            _add(findings, "pass", "config", f"Live config `{rel}` has no obvious placeholders.")
        if rel.endswith("models.yaml") and "qwen3.5" not in text.lower():
            _add(findings, "fail", "config", "config/models.yaml is not clearly pinned to Qwen 3.5.", "Keep model config on the Qwen 3.5 family only.")
        elif rel.endswith("models.yaml"):
            _add(findings, "pass", "config", "config/models.yaml is pinned to Qwen 3.5.")
            remote_hosts = _non_localhost_urls(text)
            trusted_hosts, untrusted_hosts = _trusted_runtime_hosts(remote_hosts)
            if untrusted_hosts:
                _add(
                    findings,
                    "fail",
                    "config",
                    "config/models.yaml includes non-localhost model endpoints.",
                    "Keep default runtime endpoints on localhost/127.0.0.1 unless a reviewed exception is explicitly intended.",
                    ", ".join(untrusted_hosts),
                )
            elif trusted_hosts:
                _add(
                    findings,
                    "pass",
                    "config",
                    "config/models.yaml uses trusted non-public runtime endpoints.",
                    details=", ".join(trusted_hosts),
                )
            else:
                _add(findings, "pass", "config", "config/models.yaml keeps model endpoints on localhost.")
        if rel.endswith("app.yaml"):
            if "0.0.0.0" in text:
                _add(
                    findings,
                    "fail",
                    "config",
                    "config/app.yaml contains a wildcard bind posture.",
                    "Use localhost-only defaults for v5.1 unless a reviewed deployment override is explicitly required.",
                )
            else:
                _add(findings, "pass", "config", "config/app.yaml has no wildcard bind posture.")
        if rel.endswith("channels.yaml"):
            missing = [key for key in EXPECTED_CHANNEL_KEYS if key not in text]
            if missing:
                _add(findings, "warn", "config", f"config/channels.yaml is missing channel keys: {', '.join(missing)}.", "Add the missing channel mappings before live Discord deployment.")
            else:
                _add(findings, "pass", "config", "config/channels.yaml includes the expected operator channel names.")

    findings.extend(validate_runtime_routing_policy_config(root))
    findings.extend(check_routing_policy_openclaw_drift(root))
    findings.extend(check_backend_adapter_coverage(root))
    findings.extend(check_backend_dependency_health(root))

    for rel in ["state/logs", "workspace/out", "workspace/vault"]:
        error = _write_probe(root / rel)
        if error is None:
            _add(findings, "pass", "filesystem", f"Directory `{rel}` is writable.")
        else:
            _add(findings, "fail", "filesystem", f"Directory `{rel}` is not writable.", f"Fix permissions on `{rel}` before deployment.", error)

    backend_health = build_backend_health_summary(root=root)
    accelerator_summary = build_accelerator_summary(root=root)
    eval_run_summary = build_eval_run_summary(root=root)
    degraded_state = build_degraded_state_summary(root=root)
    node_health = build_node_health_summary(root=root)
    task_lease_summary = build_task_lease_summary(root=root)
    workspace_registry_summary = summarize_workspace_registry(root=root)
    skill_scheduler_summary = build_skill_scheduler_summary(root=root)
    vault_summary = build_vault_export_summary(root=root)
    experiment_summary = build_experiment_summary(root=root)
    research_backend_summary = build_research_backend_summary(root=root)
    evidence_bundle_summary = build_evidence_bundle_summary(root=root)
    world_ops_summary = build_world_ops_summary(root=root)
    shadowbroker_summary = summarize_shadowbroker_backend(root=root)
    adaptation_lab_summary = summarize_adaptation_lab(root=root)
    optimizer_summary = summarize_optimizer_lane(root=root)

    if backend_health["snapshot_count"]:
        _add(findings, "pass", "runtime_prep", "Backend health scaffolding is present.")
    else:
        _add(findings, "warn", "runtime_prep", "Backend health scaffolding is missing.", "Run `python3 scripts/bootstrap.py` to seed backend health scaffolding.")

    if accelerator_summary["summary_count"]:
        _add(findings, "pass", "runtime_prep", "Accelerator scaffolding is present.")
    else:
        _add(findings, "warn", "runtime_prep", "Accelerator scaffolding is missing.", "Run `python3 scripts/bootstrap.py` to seed accelerator scaffolding.")

    if eval_runs_dir := (root / "state" / "eval_runs"):
        if eval_runs_dir.exists():
            _add(findings, "pass", "runtime_prep", "Eval run scaffolding directory is present.")
        else:
            _add(findings, "warn", "runtime_prep", "Eval run scaffolding directory is missing.", "Run `python3 scripts/bootstrap.py` to create `state/eval_runs`.")

    if node_health["registered_node_count"]:
        _add(
            findings,
            "pass",
            "runtime_prep",
            "Node registry scaffolding is present.",
            details=(
                f"registered_nodes={node_health['registered_node_count']} "
                f"online_nodes={node_health['online_node_count']} "
                f"burst_online={node_health['burst_online_count']}"
            ),
        )
    else:
        _add(findings, "warn", "runtime_prep", "Node registry scaffolding is missing.", "Run `python3 scripts/bootstrap.py` to seed node scaffolding.")

    if node_health["primary_online_count"]:
        _add(findings, "pass", "runtime_prep", "Primary node heartbeat is present.")
    else:
        _add(findings, "warn", "runtime_prep", "Primary node heartbeat is missing or stale.", "Run `python3 scripts/bootstrap.py` or rebuild the heartbeat report.")

    if node_health["burst_online_count"]:
        _add(findings, "pass", "runtime_prep", "At least one burst node heartbeat is present.")
    else:
        _add(findings, "pass", "runtime_prep", "No burst node is currently online; optional burst capacity remains non-critical.")

    _add(
        findings,
        "pass",
        "runtime_prep",
        "Task lease scaffolding is present.",
        details=(
            f"leases={task_lease_summary['task_lease_count']} "
            f"active={task_lease_summary['active_task_lease_count']} "
            f"expired={task_lease_summary['expired_task_lease_count']} "
            f"requeued={task_lease_summary['requeued_task_lease_count']}"
        ),
    )
    _add(
        findings,
        "pass",
        "runtime_prep",
        "Workspace registry is present and keeps jarvis-v5 as central runtime truth.",
        details=(
            f"workspaces={workspace_registry_summary['workspace_count']} "
            f"default_home={workspace_registry_summary['default_home_workspace_id']} "
            f"operator_approved={workspace_registry_summary['operator_approved_workspace_count']} "
            f"writable={workspace_registry_summary['writable_workspace_count']}"
        ),
    )
    _add(
        findings,
        "pass",
        "world_ops",
        "World-ops sidecar summary is readable and remains non-authoritative.",
        details=(
            f"active_feeds={world_ops_summary['active_feed_count']} "
            f"degraded_feeds={world_ops_summary['degraded_feed_count']} "
            f"recent_events={world_ops_summary['recent_event_count']}"
        ),
    )
    _add(
        findings,
        "pass",
        "adaptation_lab",
        "Adaptation lab sidecar summary is readable and remains eval/operator gated.",
        details=(
            f"datasets={adaptation_lab_summary['dataset_count']} "
            f"jobs={adaptation_lab_summary['job_count']} "
            f"blocked_jobs={adaptation_lab_summary['blocked_job_count']}"
        ),
    )
    _add(
        findings,
        "pass",
        "optimizer",
        "DSPy optimizer summary is readable and remains eval/operator gated.",
        details=(
            f"variants={optimizer_summary['variant_summary']['variant_count']} "
            f"runs={optimizer_summary['optimizer_run_count']} "
            f"blocked_runs={optimizer_summary['blocked_run_count']}"
        ),
    )
    _add(
        findings,
        "pass",
        "runtime_prep",
        "Skills scaffolding is present.",
        details=(
            f"approved_skills={skill_scheduler_summary['registry_summary']['approved_skill_count']} "
            f"skill_candidates={skill_scheduler_summary['registry_summary']['skill_candidate_summary']['skill_candidate_count']} "
            f"schedule_ready={skill_scheduler_summary['scheduler_readiness']['schedule_ready_skill_count']}"
        ),
    )
    _add(
        findings,
        "pass",
        "vault",
        "Knowledge vault export scaffolding is present and non-authoritative.",
        details=(
            f"exports={vault_summary['export_count']} "
            f"exportable_artifacts={vault_summary['exportable_artifact_count']}"
        ),
    )
    _add(
        findings,
        "pass",
        "experiments",
        "Self-optimization experiment scaffolding is present.",
        details=(
            f"experiments={experiment_summary['experiment_count']} "
            f"frontier_size={experiment_summary['frontier_size']}"
        ),
    )
    _add(
        findings,
        "pass",
        "research",
        "Research backend abstraction and evidence bundle scaffolding are present.",
        details=(
            f"backends={research_backend_summary['research_backend_count']} "
            f"healthy_backends={research_backend_summary['healthy_research_backend_count']} "
            f"evidence_bundles={evidence_bundle_summary['evidence_bundle_count']}"
        ),
    )

    if degraded_state["degraded_backend_count"]:
        _add(
            findings,
            "warn",
            "runtime_prep",
            "Backend health summary reports degraded lanes.",
            "Inspect doctor output and backend health scaffolding before any future routing-core migration.",
            details=", ".join(f"{row['lane']}={row['status']}" for row in backend_health["unhealthy_lanes"][:5]),
        )
    else:
        _add(findings, "pass", "runtime_prep", "Backend health scaffolding reports no degraded lanes.")

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    for module_name in KEY_MODULES:
        try:
            importlib.import_module(module_name)
            _add(findings, "pass", "imports", f"Module `{module_name}` imports cleanly.")
        except Exception as exc:
            _add(findings, "fail", "imports", f"Module `{module_name}` failed to import.", f"Fix the import error in `{module_name}` before deployment.", str(exc))

    regression_entry = root / "runtime" / "core" / "run_runtime_regression_pack.py"
    if regression_entry.exists():
        _add(findings, "pass", "runtime", "Runtime regression pack entrypoint is present.")
    else:
        _add(findings, "fail", "runtime", "Runtime regression pack entrypoint is missing.", "Restore `runtime/core/run_runtime_regression_pack.py`.")

    operator_snapshot = root / "state" / "logs" / "operator_snapshot.json"
    if operator_snapshot.exists():
        _add(findings, "pass", "operator", "Operator snapshot log exists.")
    else:
        _add(findings, "warn", "operator", "Operator snapshot log does not exist yet.", "Run a dashboard rebuild or smoke to generate operator-facing logs.")

    operator_handoff_pack = root / "state" / "logs" / "operator_handoff_pack.json"
    if operator_handoff_pack.exists():
        try:
            handoff = json.loads(operator_handoff_pack.read_text(encoding="utf-8"))
        except Exception as exc:
            _add(findings, "warn", "operator", "Operator handoff pack exists but is malformed.", "Rebuild the handoff pack after dashboard regeneration.", str(exc))
        else:
            required_pack_keys = {"backend_health_summary", "degraded_state_summary", "eval_scaffolding_summary"}
            required_pack_keys.update({"active_nodes_summary", "heartbeat_summary"})
            pack = dict(handoff.get("pack") or handoff)
            missing = sorted(required_pack_keys - set(pack))
            if missing:
                _add(findings, "warn", "operator", "Operator handoff pack is missing 5.2-prep summary fields.", "Rebuild the handoff pack after bootstrap/smoke.", ", ".join(missing))
            else:
                _add(findings, "pass", "operator", "Operator handoff pack includes 5.2-prep runtime summaries.")
    else:
        _add(findings, "warn", "operator", "Operator handoff pack does not exist yet.", "Run smoke or `python3 scripts/operator_handoff_pack.py` before operator handoff.")

    pass_count = sum(1 for item in findings if item.status == "pass")
    warn_count = sum(1 for item in findings if item.status == "warn")
    fail_count = sum(1 for item in findings if item.status == "fail")
    ok = fail_count == 0 and (warn_count == 0 or not strict)

    next_actions = [item.remediation for item in findings if item.status == "fail" and item.remediation]
    if not next_actions and warn_count:
        next_actions = [item.remediation for item in findings if item.status == "warn" and item.remediation][:3]

    report = {
        "ok": ok,
        "strict": strict,
        "timestamp_utc": now_iso(),
        "root": str(root),
        "requested_root": str(requested_root),
        "summary": {
            "pass": pass_count,
            "warn": warn_count,
            "fail": fail_count,
        },
        "foundation": foundation,
        "findings": [item.to_dict() for item in findings],
        "next_actions": next_actions,
    }
    return report


def write_report(root: Path, name: str, payload: dict) -> Path:
    path = root / "state" / "logs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def render_validate_report(report: dict) -> str:
    lines = [
        f"validate: {'PASS' if report['ok'] else 'FAIL'}",
        f"root: {report['root']}",
        (
            "summary: "
            f"pass={report['summary']['pass']} "
            f"warn={report['summary']['warn']} "
            f"fail={report['summary']['fail']}"
        ),
    ]
    for item in report["findings"]:
        if item["status"] == "pass":
            continue
        lines.append(f"- {item['status'].upper()} [{item['category']}] {item['message']}")
        if item.get("remediation"):
            lines.append(f"  next: {item['remediation']}")
    if report["ok"]:
        lines.append("next: run `python3 scripts/smoke_test.py` for a runtime-local deployment smoke.")
    return "\n".join(lines)


def build_doctor_report(root: Path) -> dict:
    validation = run_validate(root, strict=False)
    findings: list[Finding] = []

    for item in validation["findings"]:
        findings.append(Finding(**item))

    tasks_count = len(list((root / "state" / "tasks").glob("*.json")))
    outputs_count = len(list((root / "workspace" / "out").glob("*.json")))
    approvals_count = len(list((root / "state" / "approvals").glob("*.json")))
    controls_count = len(list((root / "state" / "controls").glob("*.json")))
    research_campaigns_count = len(list((root / "state" / "research_campaigns").glob("*.json")))
    run_traces_count = len(list((root / "state" / "run_traces").glob("*.json")))
    eval_results_count = len(list((root / "state" / "eval_results").glob("*.json")))
    consolidation_runs_count = len(list((root / "state" / "consolidation_runs").glob("*.json")))
    memory_retrievals_count = len(list((root / "state" / "memory_retrievals").glob("*.json")))
    reviews_count = len(list((root / "state" / "reviews").glob("*.json")))
    backend_health = build_backend_health_summary(root=root)
    accelerator_summary = build_accelerator_summary(root=root)
    eval_run_summary = build_eval_run_summary(root=root)
    degraded_state = build_degraded_state_summary(root=root)
    node_health = build_node_health_summary(root=root)
    task_lease_summary = build_task_lease_summary(root=root)
    skill_scheduler_summary = build_skill_scheduler_summary(root=root)
    discord_live_ops_summary = build_discord_live_ops_summary(root=root)
    openclaw_discord_bridge_summary = build_openclaw_discord_bridge_summary(root=root)
    openclaw_discord_session_summary = build_openclaw_discord_session_summary(root=root)
    routing_control_plane_summary = build_routing_control_plane_summary(
        routing_summary=build_model_registry_summary(root),
        degradation_summary=build_degradation_summary(root),
        heartbeat_summary=build_heartbeat_report_summary(root=root),
    )
    world_ops_summary = build_world_ops_summary(root=root)
    adaptation_lab_summary = summarize_adaptation_lab(root=root)
    optimizer_summary = summarize_optimizer_lane(root=root)
    local_model_lane_proof_summary = build_local_model_lane_proof_summary(root=root)
    hermes_summary = build_hermes_summary(root=root)
    autoresearch_summary = build_autoresearch_summary(root=root)
    browser_action_summary = build_browser_action_summary(root=root)
    a2a_policy_summary = build_a2a_policy_summary(root=root)
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
    live_lane_diagnostic = dict(discord_live_ops_summary.get("live_lane_diagnostic") or {})

    _add(findings, "pass", "runtime_state", "State directories are readable.", details=f"tasks={tasks_count} approvals={approvals_count} reviews={reviews_count} outputs={outputs_count} controls={controls_count} research_campaigns={research_campaigns_count} run_traces={run_traces_count} eval_results={eval_results_count} consolidation_runs={consolidation_runs_count} memory_retrievals={memory_retrievals_count}")
    _add(
        findings,
        "pass",
        "runtime_prep",
        "5.2-prep runtime scaffolding summary loaded.",
        details=(
            f"backend_snapshots={backend_health['snapshot_count']} "
            f"accelerator_summaries={accelerator_summary['summary_count']} "
            f"eval_runs={eval_run_summary['eval_run_count']} "
            f"registered_nodes={node_health['registered_node_count']} "
            f"online_nodes={node_health['online_node_count']} "
            f"task_leases={task_lease_summary['task_lease_count']} "
            f"approved_skills={skill_scheduler_summary['registry_summary']['approved_skill_count']} "
            f"skill_candidates={skill_scheduler_summary['registry_summary']['skill_candidate_summary']['skill_candidate_count']}"
        ),
    )
    if backend_health["unhealthy_lane_count"]:
        _add(
            findings,
            "warn",
            "runtime_prep",
            "One or more backend lanes are marked unhealthy in the 5.2-prep scaffold.",
            "Inspect backend health rows before taking routing-core migration tickets.",
            ", ".join(f"{row['lane']}={row['status']}" for row in backend_health["unhealthy_lanes"][:5]),
        )
    if degraded_state["degraded_backend_count"]:
        _add(
            findings,
            "warn",
            "runtime_prep",
            "Degraded backend posture is present in runtime-prep summaries.",
            "Use operator snapshot / handoff summaries to inspect degraded lanes before migration work.",
        )
    if node_health.get("primary_outage_count", 0):
        _add(
            findings,
            "warn",
            "runtime_prep",
            "Primary node heartbeat is missing or stale.",
            "Rebuild the heartbeat report or rerun bootstrap before taking node-aware migration tickets.",
        )
    elif node_health.get("optional_burst_offline_count", 0):
        _add(
            findings,
            "pass",
            "runtime_prep",
            "Primary runtime remains healthy while the optional burst worker is offline.",
            details=", ".join(row["node_name"] for row in node_health["optional_burst_offline_nodes"][:5]),
        )
    elif node_health["stale_heartbeat_count"]:
        _add(
            findings,
            "pass",
            "runtime_prep",
            "Node registry is readable; some non-primary optional nodes are offline or stale.",
            details=", ".join(row["node_name"] for row in node_health["stale_nodes"][:5]),
        )
    if task_lease_summary["expired_task_lease_count"]:
        _add(
            findings,
            "warn",
            "runtime_prep",
            "Expired task leases are present and may need reclaim handling.",
            "Inspect task_lease_summary in operator surfaces before enabling any future burst-worker execution flow.",
        )
    if skill_scheduler_summary["registry_summary"]["skill_candidate_summary"]["skill_candidate_count"]:
        _add(
            findings,
            "pass",
            "runtime_prep",
            "Skill candidates are present and remain bounded behind review/eval gating.",
        )
    if discord_live_ops_summary["discord_origin_task_count"]:
        failure_category = str(live_lane_diagnostic.get("failure_category") or "")
        next_inspect = str(live_lane_diagnostic.get("next_inspect") or "")
        if failure_category:
            _add(
                findings,
                "warn",
                "live_lane",
                f"Latest Discord live-lane task is degraded or blocked: {failure_category}.",
                next_inspect or "Inspect discord_live_ops_summary in status/operator snapshot.",
                details=(
                    f"route_selected={live_lane_diagnostic.get('route_selected')} "
                    f"backend_execution_attempted={live_lane_diagnostic.get('backend_execution_attempted')} "
                    f"selected_backend={live_lane_diagnostic.get('selected_backend') or 'unknown'} "
                    f"selected_model={live_lane_diagnostic.get('selected_model_name') or 'unknown'} "
                    f"selected_host={live_lane_diagnostic.get('selected_host_name') or 'unknown'}"
                ),
            )
        else:
            _add(
                findings,
                "pass",
                "live_lane",
                "Discord live-lane summary is available and no active failure category is recorded.",
                details=(
                    f"route_selected={live_lane_diagnostic.get('route_selected')} "
                    f"backend_execution_attempted={live_lane_diagnostic.get('backend_execution_attempted')}"
                ),
            )
    elif discord_live_ops_summary.get("latest_discord_routing_refusal"):
        refusal = discord_live_ops_summary["latest_discord_routing_refusal"]
        _add(
            findings,
            "warn",
            "live_lane",
            "Latest Discord live-lane intake was refused by routing.",
            "Inspect routing_summary.latest_failed_routing_request and runtime_routing_policy.json.",
            details=str(refusal.get("failure_reason") or ""),
        )

    if openclaw_discord_bridge_summary.get("recent_discord_attempt_count"):
        latest_bridge_failure = dict(openclaw_discord_bridge_summary.get("latest_failure") or {})
        latest_bridge_attempt = dict(openclaw_discord_bridge_summary.get("latest_attempt") or {})
        if latest_bridge_failure:
            _add(
                findings,
                "warn",
                "openclaw_bridge",
                f"Latest mirrored OpenClaw Discord activity recorded a failure: {latest_bridge_failure.get('failure_class')}.",
                "Inspect openclaw_discord_bridge_summary and the external OpenClaw Discord/gateway runtime.",
                details=(
                    f"source_message_id={latest_bridge_attempt.get('source_message_id') or 'unknown'} "
                    f"model={latest_bridge_attempt.get('selected_model_name') or 'unknown'} "
                    f"provider={latest_bridge_attempt.get('selected_provider_id') or 'unknown'}"
                ),
            )
        else:
            _add(
                findings,
                "pass",
                "openclaw_bridge",
                "Mirrored OpenClaw Discord activity summary is available.",
                details=(
                    f"recent_attempts={openclaw_discord_bridge_summary.get('recent_discord_attempt_count', 0)} "
                    f"latest_success={bool(openclaw_discord_bridge_summary.get('latest_successful_reply'))}"
                ),
            )

    if openclaw_discord_session_summary.get("malformed_session_count"):
        latest_malformed = dict(openclaw_discord_session_summary.get("latest_malformed_session") or {})
        _add(
            findings,
            "warn",
            "openclaw_session",
            f"Malformed external Discord session detected: {latest_malformed.get('malformed_reason') or 'invalid_session_history'}.",
            latest_malformed.get("operator_action_required")
            or "Run `python3 scripts/repair_discord_sessions.py --repair-all-malformed --repair`.",
            details=(
                f"session_id={latest_malformed.get('session_id') or 'unknown'} "
                f"model={latest_malformed.get('selected_model_name') or latest_malformed.get('model_override') or 'unknown'} "
                f"compactions={latest_malformed.get('compaction_count', 0)}"
            ),
        )

    if world_ops_summary.get("degraded_feed_count"):
        _add(
            findings,
            "warn",
            "world_ops",
            "One or more world-ops feeds are degraded or unavailable.",
            "Inspect world_ops_summary and the latest feed/error state before trusting external world-status inputs.",
            details=(
                f"active_feeds={world_ops_summary.get('active_feed_count', 0)} "
                f"degraded_feeds={world_ops_summary.get('degraded_feed_count', 0)} "
                f"recent_events={world_ops_summary.get('recent_event_count', 0)}"
            ),
        )
    else:
        _add(
            findings,
            "pass",
            "world_ops",
            "World-ops sidecar summary is available.",
            details=(
                f"active_feeds={world_ops_summary.get('active_feed_count', 0)} "
                f"recent_events={world_ops_summary.get('recent_event_count', 0)}"
            ),
        )
    shadowbroker_runtime = validate_shadowbroker_runtime()
    if str(shadowbroker_runtime.get("status") or "") == "blocked_shadowbroker_invalid_config":
        _add(
            findings,
            "fail",
            "shadowbroker",
            "ShadowBroker sidecar config is invalid.",
            "Fix JARVIS_SHADOWBROKER_BASE_URL / JARVIS_SHADOWBROKER_TIMEOUT_SECONDS before operator use.",
            details=str(shadowbroker_runtime.get("reason") or ""),
        )
    elif not shadowbroker_summary.get("configured"):
        _add(
            findings,
            "warn",
            "shadowbroker",
            "ShadowBroker sidecar is not configured.",
            "Configure JARVIS_SHADOWBROKER_BASE_URL if you want ShadowBroker-backed OSINT snapshots.",
        )
    elif not shadowbroker_summary.get("healthy"):
        _add(
            findings,
            "warn",
            "shadowbroker",
            "ShadowBroker sidecar is configured but degraded or unreachable.",
            "Inspect shadowbroker_summary and the external ShadowBroker service/runtime.",
            details=str(shadowbroker_summary.get("degraded_reason") or shadowbroker_summary.get("backend_status") or ""),
        )
    elif shadowbroker_summary.get("latest_snapshot_age_seconds") is not None and int(shadowbroker_summary.get("latest_snapshot_age_seconds") or 0) > _SHADOWBROKER_STALE_SNAPSHOT_SECONDS:
        _add(
            findings,
            "warn",
            "shadowbroker",
            "ShadowBroker sidecar is healthy but the latest snapshot is stale.",
            "Refresh ShadowBroker collection before claiming current OSINT coverage.",
            details=(
                f"snapshot_age_seconds={shadowbroker_summary.get('latest_snapshot_age_seconds')} "
                f"stale_threshold_seconds={_SHADOWBROKER_STALE_SNAPSHOT_SECONDS}"
            ),
        )
    else:
        _add(
            findings,
            "pass",
            "shadowbroker",
            "ShadowBroker sidecar summary is available.",
            details=(
                f"recent_events={shadowbroker_summary.get('recent_event_count', 0)} "
                f"evidence_bundles={shadowbroker_summary.get('evidence_bundle_count', 0)}"
            ),
        )

    if adaptation_lab_summary.get("blocked_job_count"):
        _add(
            findings,
            "warn",
            "adaptation_lab",
            "One or more adaptation jobs are blocked by missing runtime requirements or pending gates.",
            "Inspect adaptation_lab_summary before treating fine-tuning as available.",
            details=(
                f"jobs={adaptation_lab_summary.get('job_count', 0)} "
                f"blocked_jobs={adaptation_lab_summary.get('blocked_job_count', 0)}"
            ),
        )
    else:
        _add(
            findings,
            "pass",
            "adaptation_lab",
            "Adaptation lab summary is available and promotion remains blocked by default.",
            details=(
                f"datasets={adaptation_lab_summary.get('dataset_count', 0)} "
                f"jobs={adaptation_lab_summary.get('job_count', 0)}"
            ),
        )
    if optimizer_summary.get("blocked_run_count"):
        _add(
            findings,
            "warn",
            "optimizer",
            "One or more DSPy optimizer runs are blocked by missing runtime requirements or pending gates.",
            "Inspect optimizer_summary before treating DSPy optimization as available.",
            details=(
                f"variants={optimizer_summary.get('variant_summary', {}).get('variant_count', 0)} "
                f"runs={optimizer_summary.get('optimizer_run_count', 0)} "
                f"blocked_runs={optimizer_summary.get('blocked_run_count', 0)}"
            ),
        )
    else:
        _add(
            findings,
            "pass",
            "optimizer",
            "DSPy optimizer summary is available and remains eval/operator gated.",
            details=(
                f"variants={optimizer_summary.get('variant_summary', {}).get('variant_count', 0)} "
                f"runs={optimizer_summary.get('optimizer_run_count', 0)}"
            ),
        )

    state_export = root / "state" / "logs" / "state_export.json"
    if state_export.exists():
        _add(findings, "pass", "operator", "state_export.json is present for operator/dashboard visibility.")
    else:
        _add(findings, "warn", "operator", "state_export.json is missing.", "Run a dashboard rebuild or smoke before operator handoff.")

    regression = _run_python_json(root, [sys.executable, str(root / "runtime" / "core" / "run_runtime_regression_pack.py")])
    if regression["ok"]:
        pack = regression["payload"]
        _add(findings, "pass", "runtime", f"Runtime regression pack is green ({pack.get('passed')}/{pack.get('total')} passed).")
    else:
        _add(findings, "fail", "runtime", "Runtime regression pack is not green.", "Fix the failing smoke(s) before deployment.", regression["message"])

    fail_count = sum(1 for item in findings if item.status == "fail")
    warn_count = sum(1 for item in findings if item.status == "warn")
    if fail_count:
        verdict = "blocked"
    elif warn_count:
        verdict = "healthy_with_warnings"
    else:
        verdict = "healthy"

    grouped: dict[str, list[dict]] = {}
    for item in findings:
        grouped.setdefault(item.category, []).append(item.to_dict())

    next_actions = [item.remediation for item in findings if item.status == "fail" and item.remediation]
    if not next_actions:
        next_actions = [item.remediation for item in findings if item.status == "warn" and item.remediation][:5]
    if regression["ok"]:
        next_actions.append("After a green baseline, use operator snapshot / dashboard outputs to work the next ready_to_ship or publish-complete handoff.")

    return {
        "ok": fail_count == 0,
        "verdict": verdict,
        "timestamp_utc": now_iso(),
        "root": str(root),
        "summary": {
            "pass": sum(1 for item in findings if item.status == "pass"),
            "warn": warn_count,
            "fail": fail_count,
            "tasks": tasks_count,
            "approvals": approvals_count,
            "controls": controls_count,
            "research_campaigns": research_campaigns_count,
            "run_traces": run_traces_count,
            "eval_results": eval_results_count,
            "consolidation_runs": consolidation_runs_count,
            "memory_retrievals": memory_retrievals_count,
            "reviews": reviews_count,
            "outputs": outputs_count,
            "backend_health_snapshots": backend_health["snapshot_count"],
            "accelerator_summaries": accelerator_summary["summary_count"],
            "eval_runs": eval_run_summary["eval_run_count"],
            "registered_nodes": node_health["registered_node_count"],
            "online_nodes": node_health["online_node_count"],
            "task_leases": task_lease_summary["task_lease_count"],
            "approved_skills": skill_scheduler_summary["registry_summary"]["approved_skill_count"],
            "skill_candidates": skill_scheduler_summary["registry_summary"]["skill_candidate_summary"]["skill_candidate_count"],
        },
        "groups": grouped,
        "next_actions": next_actions,
        "regression_pack": regression["payload"] if regression["ok"] else None,
        "live_lane_diagnostic": live_lane_diagnostic,
        "routing_control_plane_summary": routing_control_plane_summary,
        "openclaw_discord_bridge_summary": openclaw_discord_bridge_summary,
        "openclaw_discord_session_summary": openclaw_discord_session_summary,
        "world_ops_summary": world_ops_summary,
        "shadowbroker_summary": shadowbroker_summary,
        "adaptation_lab_summary": adaptation_lab_summary,
        "optimizer_summary": optimizer_summary,
        "local_model_lane_proof_summary": local_model_lane_proof_summary,
        "extension_lane_status_summary": extension_lane_status_summary,
        "lane_activation_summary": lane_activation_summary,
    }


def render_doctor_report(report: dict) -> str:
    lines = [
        f"doctor: {report['verdict']}",
        f"root: {report['root']}",
        (
            "summary: "
            f"pass={report['summary']['pass']} "
            f"warn={report['summary']['warn']} "
            f"fail={report['summary']['fail']} "
            f"tasks={report['summary']['tasks']} "
            f"outputs={report['summary']['outputs']} "
            f"backend_health={report['summary'].get('backend_health_snapshots', 0)} "
            f"eval_runs={report['summary'].get('eval_runs', 0)} "
            f"nodes={report['summary'].get('registered_nodes', 0)} "
            f"online_nodes={report['summary'].get('online_nodes', 0)} "
            f"task_leases={report['summary'].get('task_leases', 0)} "
            f"approved_skills={report['summary'].get('approved_skills', 0)} "
            f"skill_candidates={report['summary'].get('skill_candidates', 0)}"
        ),
    ]
    live_lane = report.get("live_lane_diagnostic") or {}
    routing_truth = report.get("routing_control_plane_summary") or {}
    if live_lane:
        lines.append(
            "live_lane: "
            f"route_selected={live_lane.get('route_selected')} "
            f"backend_execution_attempted={live_lane.get('backend_execution_attempted')} "
            f"failure_category={live_lane.get('failure_category') or 'none'} "
            f"selected_model={live_lane.get('selected_model_name') or 'unknown'} "
            f"selected_host={live_lane.get('selected_host_name') or 'unknown'}"
        )
    if routing_truth:
        lines.append(
            "routing_truth: "
            f"state={routing_truth.get('latest_route_state')} "
            f"legality={routing_truth.get('latest_route_legality')} "
            f"fallback_blocked={routing_truth.get('fallback_blocked_for_safety')} "
            f"primary_posture={routing_truth.get('primary_runtime_posture')} "
            f"burst_posture={routing_truth.get('burst_capacity_posture')} "
            f"model={(routing_truth.get('latest_selected_route') or {}).get('model_name') or 'unknown'} "
            f"host={(routing_truth.get('latest_selected_route') or {}).get('host_name') or 'unknown'}"
        )
    bridge = report.get("openclaw_discord_bridge_summary") or {}
    if bridge:
        latest_attempt = bridge.get("latest_attempt") or {}
        latest_failure = bridge.get("latest_failure") or {}
        lines.append(
            "openclaw_bridge: "
            f"recent_attempts={bridge.get('recent_discord_attempt_count', 0)} "
            f"latest_model={latest_attempt.get('selected_model_name') or 'unknown'} "
            f"latest_provider={latest_attempt.get('selected_provider_id') or 'unknown'} "
            f"latest_failure={latest_failure.get('failure_class') or 'none'}"
        )
    session_summary = report.get("openclaw_discord_session_summary") or {}
    if session_summary:
        latest_malformed = session_summary.get("latest_malformed_session") or {}
        lines.append(
            "openclaw_sessions: "
            f"detected={session_summary.get('detected_session_count', 0)} "
            f"malformed={session_summary.get('malformed_session_count', 0)} "
            f"latest_reason={latest_malformed.get('malformed_reason') or 'none'} "
            f"latest_session_id={latest_malformed.get('session_id') or 'none'}"
        )
    shadowbroker = report.get("shadowbroker_summary") or {}
    if shadowbroker:
        lines.append(
            "shadowbroker: "
            f"configured={shadowbroker.get('configured')} "
            f"healthy={shadowbroker.get('healthy')} "
            f"status={shadowbroker.get('backend_status') or 'unknown'} "
            f"recent_events={shadowbroker.get('recent_event_count', 0)} "
            f"evidence_bundles={shadowbroker.get('evidence_bundle_count', 0)} "
            f"snapshot_age_s={shadowbroker.get('latest_snapshot_age_seconds')} "
            f"latency_ms={((shadowbroker.get('backend_latency_summary') or {}).get('latest_latency_ms'))}"
        )
    extension_lanes = report.get("extension_lane_status_summary") or {}
    if extension_lanes:
        counts = extension_lanes.get("classification_counts") or {}
        lines.append(
            "extension_lanes: "
            f"live={counts.get('live_and_usable', 0)} "
            f"blocked={counts.get('implemented_but_blocked_by_external_runtime', 0)} "
            f"scaffold={counts.get('scaffold_only', 0)} "
            f"deprecated={counts.get('deprecated_alias', 0)}"
        )
    lane_activation = report.get("lane_activation_summary") or {}
    if lane_activation:
        lines.append(
            "lane_activation: "
            f"live={lane_activation.get('live_lane_count', 0)} "
            f"blocked={lane_activation.get('blocked_lane_count', 0)} "
            f"degraded={lane_activation.get('degraded_lane_count', 0)} "
            f"not_run={lane_activation.get('never_activated_count', 0)}"
        )
    local_model_lane_proof = report.get("local_model_lane_proof_summary") or {}
    if local_model_lane_proof:
        proof_rows = {str(row.get("lane") or ""): row for row in list(local_model_lane_proof.get("rows") or [])}
        unsloth = proof_rows.get("adaptation_lab_unsloth", {})
        dspy = proof_rows.get("optimizer_dspy", {})
        lines.append(
            "local_model_proofs: "
            f"unsloth={unsloth.get('latest_activation_status', 'not_run')}/{unsloth.get('latest_runtime_status', 'not_run')} "
            f"dspy={dspy.get('latest_activation_status', 'not_run')}/{dspy.get('latest_runtime_status', 'not_run')}"
        )
    for category, items in report["groups"].items():
        noteworthy = [item for item in items if item["status"] != "pass"]
        if not noteworthy:
            continue
        lines.append(f"{category}:")
        for item in noteworthy:
            lines.append(f"- {item['status'].upper()} {item['message']}")
            if item.get("remediation"):
                lines.append(f"  next: {item['remediation']}")
    if report["next_actions"]:
        lines.append("next actions:")
        for action in report["next_actions"][:5]:
            lines.append(f"- {action}")
    return "\n".join(lines)


def _run_python_json(root: Path, cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return {"ok": False, "message": stderr or stdout or f"exit {proc.returncode}"}
    try:
        return {"ok": True, "payload": json.loads(stdout) if stdout else {}}
    except Exception:
        return {"ok": False, "message": f"non-JSON output: {stdout[:800]}"}


class _ShadowbrokerFakeResponse:
    def __init__(self, body: str, *, status: int = 200) -> None:
        self._body = body.encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def smoke_shadowbroker_missing_config(root: Path) -> dict:
    result = fetch_shadowbroker_snapshot(feed_id="shadowbroker_smoke_missing", root=root)
    ok = result.get("backend_status") == "blocked_shadowbroker_not_configured"
    return {
        "ok": ok,
        "summary": {
            "backend_status": result.get("backend_status"),
            "degraded_reason": result.get("degraded_reason"),
        },
        "message": (
            "missing-config path reports blocked_shadowbroker_not_configured"
            if ok
            else f"unexpected missing-config status: {result.get('backend_status')}"
        ),
    }


def smoke_shadowbroker_mocked_success(root: Path) -> dict:
    def _fake_urlopen(url: str, *, headers: dict[str, str], timeout_seconds: float, verify_ssl: bool):
        if url.endswith("/healthz"):
            return _ShadowbrokerFakeResponse("{}", status=200)
        return _ShadowbrokerFakeResponse(
            """{
  "snapshot_id": "shadowbroker_smoke_snapshot",
  "events": [
    {
      "event_id": "shadowbroker_smoke_event",
      "title": "Smoke test event",
      "summary": "Controlled ShadowBroker smoke payload.",
      "region": "global",
      "event_type": "smoke_signal",
      "risk_posture": "low",
      "url": "https://shadowbroker.example/smoke"
    }
  ]
}""",
            status=200,
        )

    with patch("runtime.integrations.shadowbroker_adapter._urlopen", side_effect=_fake_urlopen):
        result = fetch_shadowbroker_snapshot(
            feed_id="shadowbroker_smoke_success",
            metadata_override={"base_url": "https://shadowbroker.invalid", "timeout_seconds": 5, "verify_ssl": True},
            root=root,
        )
    ok = bool(result.get("ok")) and (result.get("snapshot") or {}).get("snapshot_id") == "shadowbroker_smoke_snapshot"
    return {
        "ok": ok,
        "summary": {
            "backend_status": result.get("backend_status"),
            "snapshot_id": (result.get("snapshot") or {}).get("snapshot_id"),
            "event_count": len(result.get("normalized_events") or []),
        },
        "message": (
            "mocked ShadowBroker success path returned a real normalized snapshot"
            if ok
            else "mocked ShadowBroker success path did not return the expected normalized snapshot"
        ),
    }


def smoke_shadowbroker_bad_payload(root: Path) -> dict:
    def _fake_urlopen(url: str, *, headers: dict[str, str], timeout_seconds: float, verify_ssl: bool):
        if url.endswith("/healthz"):
            return _ShadowbrokerFakeResponse("{}", status=200)
        return _ShadowbrokerFakeResponse("{bad json", status=200)

    with patch("runtime.integrations.shadowbroker_adapter._urlopen", side_effect=_fake_urlopen):
        result = fetch_shadowbroker_snapshot(
            feed_id="shadowbroker_smoke_bad_payload",
            metadata_override={"base_url": "https://shadowbroker.invalid", "timeout_seconds": 5, "verify_ssl": True},
            root=root,
        )
    ok = result.get("backend_status") == "degraded_shadowbroker_bad_payload"
    return {
        "ok": ok,
        "summary": {
            "backend_status": result.get("backend_status"),
            "degraded_reason": result.get("degraded_reason"),
        },
        "message": (
            "mocked ShadowBroker bad-payload path is classified explicitly"
            if ok
            else f"unexpected bad-payload status: {result.get('backend_status')}"
        ),
    }


def run_smoke(root: Path) -> dict:
    root = root.resolve()
    steps: list[dict] = []

    validation = run_validate(root, strict=False)
    steps.append(
        {
            "step": "validate",
            "ok": validation["ok"],
            "summary": validation["summary"],
            "message": "validate passed" if validation["ok"] else "validate found blocking failures",
        }
    )
    if not validation["ok"]:
        return {
            "ok": False,
            "timestamp_utc": now_iso(),
            "root": str(root),
            "steps": steps,
            "message": "Smoke stopped at validate.",
        }

    shadowbroker_missing = smoke_shadowbroker_missing_config(root)
    steps.append(
        {
            "step": "shadowbroker_missing_config",
            "ok": shadowbroker_missing["ok"],
            "summary": shadowbroker_missing["summary"],
            "message": shadowbroker_missing["message"],
        }
    )
    if not shadowbroker_missing["ok"]:
        return {
            "ok": False,
            "timestamp_utc": now_iso(),
            "root": str(root),
            "steps": steps,
            "message": "Smoke stopped at shadowbroker_missing_config.",
        }

    shadowbroker_mocked_success = smoke_shadowbroker_mocked_success(root)
    steps.append(
        {
            "step": "shadowbroker_mocked_success",
            "ok": shadowbroker_mocked_success["ok"],
            "summary": shadowbroker_mocked_success["summary"],
            "message": shadowbroker_mocked_success["message"],
        }
    )
    if not shadowbroker_mocked_success["ok"]:
        return {
            "ok": False,
            "timestamp_utc": now_iso(),
            "root": str(root),
            "steps": steps,
            "message": "Smoke stopped at shadowbroker_mocked_success.",
        }

    shadowbroker_bad_payload = smoke_shadowbroker_bad_payload(root)
    steps.append(
        {
            "step": "shadowbroker_bad_payload",
            "ok": shadowbroker_bad_payload["ok"],
            "summary": shadowbroker_bad_payload["summary"],
            "message": shadowbroker_bad_payload["message"],
        }
    )
    if not shadowbroker_bad_payload["ok"]:
        return {
            "ok": False,
            "timestamp_utc": now_iso(),
            "root": str(root),
            "steps": steps,
            "message": "Smoke stopped at shadowbroker_bad_payload.",
        }

    pack = _run_python_json(root, [sys.executable, str(root / "runtime" / "core" / "run_runtime_regression_pack.py")])
    steps.append(
        {
            "step": "runtime_regression_pack",
            "ok": pack["ok"] and bool(pack["payload"].get("ok")),
            "summary": pack.get("payload", {}),
            "message": (
                f"regression pack green ({pack['payload'].get('passed')}/{pack['payload'].get('total')} passed)"
                if pack["ok"] and pack["payload"].get("ok")
                else pack.get("message", "runtime regression pack failed")
            ),
        }
    )
    if not (pack["ok"] and pack["payload"].get("ok")):
        return {
            "ok": False,
            "timestamp_utc": now_iso(),
            "root": str(root),
            "steps": steps,
            "message": "Smoke stopped at runtime_regression_pack.",
        }

    rebuild_payload: dict = {}
    rebuild_ok = False
    rebuild_message = ""
    try:
        from runtime.dashboard.rebuild_all import rebuild_all
        from scripts.operator_handoff_pack import build_operator_handoff_pack

        rebuild_payload = rebuild_all(root=root)
        rebuild_ok = bool(rebuild_payload.get("ok"))
        rebuild_message = (
            "dashboard/state summaries rebuilt"
            if rebuild_ok
            else f"dashboard rebuild reported errors: {rebuild_payload.get('errors', [])}"
        )
    except Exception as exc:
        rebuild_payload = {"ok": False, "errors": [str(exc)]}
        rebuild_message = f"dashboard rebuild failed: {exc}"

    steps.append(
        {
            "step": "dashboard_rebuild",
            "ok": rebuild_ok,
            "summary": rebuild_payload,
            "message": rebuild_message,
        }
    )
    if not rebuild_ok:
        return {
            "ok": False,
            "timestamp_utc": now_iso(),
            "root": str(root),
            "steps": steps,
            "message": "Smoke stopped at dashboard_rebuild.",
        }

    handoff = build_operator_handoff_pack(root)
    handoff_pack = handoff.get("pack", {})
    handoff_ok = all(
        key in handoff_pack
        for key in ("backend_health_summary", "degraded_state_summary", "eval_scaffolding_summary")
    )
    steps.append(
        {
            "step": "operator_handoff_pack",
            "ok": handoff_ok,
            "summary": {
                "has_backend_health_summary": "backend_health_summary" in handoff_pack,
                "has_degraded_state_summary": "degraded_state_summary" in handoff_pack,
                "has_eval_scaffolding_summary": "eval_scaffolding_summary" in handoff_pack,
            },
            "message": (
                "operator handoff pack includes 5.2-prep runtime summaries"
                if handoff_ok
                else "operator handoff pack is missing one or more 5.2-prep runtime summaries"
            ),
        }
    )
    if not handoff_ok:
        return {
            "ok": False,
            "timestamp_utc": now_iso(),
            "root": str(root),
            "steps": steps,
            "message": "Smoke stopped at operator_handoff_pack.",
        }

    return {
        "ok": True,
        "timestamp_utc": now_iso(),
        "root": str(root),
        "steps": steps,
        "message": "Repo-local deployment smoke is green and dashboard/operator summaries were rebuilt. Next operator move: inspect operator_snapshot/state_export and work candidate-ready or shipped tasks through apply/publish-complete.",
    }


def render_smoke_report(report: dict) -> str:
    status = "PASS" if report["ok"] else "FAIL"
    lines = [f"smoke: {status}", f"root: {report['root']}"]
    for step in report["steps"]:
        lines.append(f"- {step['step']}: {'ok' if step['ok'] else 'fail'} :: {step['message']}")
    lines.append(f"next: {report['message']}")
    return "\n".join(lines)
