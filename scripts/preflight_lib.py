#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
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
from runtime.integrations.research_backends import build_research_backend_summary
from runtime.memory.vault_export import build_vault_export_summary
from runtime.researchlab.experiment_store import build_experiment_summary
from runtime.researchlab.evidence_bundle import build_evidence_bundle_summary
from runtime.skills.skill_scheduler import build_skill_scheduler_summary
from runtime.evals.replay_runner import build_eval_run_summary
from runtime.core.routing import (
    legal_candidate_pool_for_runtime_policy_block,
    load_runtime_routing_policy,
    resolve_runtime_route_policy,
    runtime_routing_policy_path,
)
from runtime.core.status import build_discord_live_ops_summary

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
    "docs/operations.md",
    "docs/runtime-regression-runbook.md",
    "config/app.example.yaml",
    "config/channels.example.yaml",
    "config/models.example.yaml",
    "config/policies.example.yaml",
    "scripts/bootstrap.py",
    "scripts/doctor.py",
    "scripts/generate_config.py",
    "scripts/operator_checkpoint_action_pack.py",
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


def _non_localhost_urls(text: str) -> list[str]:
    hosts: list[str] = []
    for match in _URL_RE.findall(text or ""):
        host = (match or "").strip().lower()
        if host and host not in _LOCALHOST_HOSTS:
            hosts.append(host)
    return sorted(set(hosts))


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
            if remote_hosts:
                _add(
                    findings,
                    "fail",
                    "config",
                    "config/models.yaml includes non-localhost model endpoints.",
                    "Keep default runtime endpoints on localhost/127.0.0.1 unless a reviewed exception is explicitly intended.",
                    ", ".join(remote_hosts),
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
    skill_scheduler_summary = build_skill_scheduler_summary(root=root)
    vault_summary = build_vault_export_summary(root=root)
    experiment_summary = build_experiment_summary(root=root)
    research_backend_summary = build_research_backend_summary(root=root)
    evidence_bundle_summary = build_evidence_bundle_summary(root=root)

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
    if not node_health["primary_online_count"]:
        _add(
            findings,
            "warn",
            "runtime_prep",
            "Primary node heartbeat is missing or stale.",
            "Rebuild the heartbeat report or rerun bootstrap before taking node-aware migration tickets.",
        )
    elif node_health["stale_heartbeat_count"]:
        _add(
            findings,
            "pass",
            "runtime_prep",
            "Node registry is readable; some optional nodes are offline or stale.",
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
    if live_lane:
        lines.append(
            "live_lane: "
            f"route_selected={live_lane.get('route_selected')} "
            f"backend_execution_attempted={live_lane.get('backend_execution_attempted')} "
            f"failure_category={live_lane.get('failure_category') or 'none'} "
            f"selected_model={live_lane.get('selected_model_name') or 'unknown'} "
            f"selected_host={live_lane.get('selected_host_name') or 'unknown'}"
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
