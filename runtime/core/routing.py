#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import (
    BackendAssignmentRecord,
    CapabilityProfileRecord,
    ModelRegistryEntryRecord,
    NodeRole,
    ProviderAdapterResultRecord,
    RoutingOverrideRecord,
    RoutingPolicyRecord,
    RoutingProvenanceRecord,
    RoutingDecisionRecord,
    RoutingRequestRecord,
    TaskPriority,
    TaskRiskLevel,
    new_id,
    now_iso,
)
from runtime.core.backend_assignments import build_backend_assignment_summary, save_backend_assignment
from runtime.core.node_registry import ensure_default_nodes, list_nodes
from runtime.controls.control_store import assert_control_allows, get_effective_control_state
from runtime.core.provenance_store import save_routing_provenance
from runtime.core.modality_contracts import build_modality_summary, ensure_default_modality_contracts


ACTIVE_QWEN_MODELS = [
    {
        "model_registry_entry_id": "model_qwen3_5_9b",
        "provider_id": "qwen",
        "provider_kind": "local_openai_compatible",
        "model_family": "qwen3.5",
        "model_name": "Qwen3.5-9B",
        "display_name": "Qwen3.5-9B",
        "priority_rank": 30,
        "default_execution_backend": "qwen_executor",
        "capability_profile_ids": ["cap_triage_qwen"],
        "host_role": NodeRole.PRIMARY.value,
        "host_name": "NIMO",
        "workload_tags": ["general", "chat"],
    },
    {
        "model_registry_entry_id": "model_qwen3_5_35b",
        "provider_id": "qwen",
        "provider_kind": "local_openai_compatible",
        "model_family": "qwen3.5",
        "model_name": "Qwen3.5-35B",
        "display_name": "Qwen3.5-35B",
        "priority_rank": 20,
        "default_execution_backend": "qwen_executor",
        "capability_profile_ids": ["cap_general_qwen"],
        "host_role": NodeRole.PRIMARY.value,
        "host_name": "NIMO",
        "workload_tags": ["general", "research"],
    },
    {
        "model_registry_entry_id": "model_qwen3_5_122b",
        "provider_id": "qwen",
        "provider_kind": "local_openai_compatible",
        "model_family": "qwen3.5",
        "model_name": "Qwen3.5-122B",
        "display_name": "Qwen3.5-122B",
        "priority_rank": 10,
        "default_execution_backend": "qwen_planner",
        "capability_profile_ids": ["cap_highstakes_qwen"],
        "host_role": NodeRole.PRIMARY.value,
        "host_name": "NIMO",
        "workload_tags": ["high_stakes", "deploy", "research"],
    },
    {
        "model_registry_entry_id": "model_local_embeddings",
        "provider_id": "local",
        "provider_kind": "local_support",
        "model_family": "local",
        "model_name": "Local-Embeddings",
        "display_name": "Local-Embeddings",
        "priority_rank": 5,
        "default_execution_backend": "memory_spine",
        "capability_profile_ids": ["cap_local_embeddings"],
        "host_role": NodeRole.LOCAL.value,
        "host_name": "LOCAL",
        "workload_tags": ["embeddings", "local_support"],
        "local_only": True,
    },
]

CAPABILITY_PROFILES = [
    {
        "capability_profile_id": "cap_triage_qwen",
        "profile_name": "qwen_triage",
        "provider_id": "qwen",
        "model_family": "qwen3.5",
        "capabilities": ["triage", "classification", "shortform"],
        "supported_task_types": ["general", "docs"],
        "supported_risk_levels": [TaskRiskLevel.NORMAL.value],
        "preferred_execution_backend": "qwen_executor",
    },
    {
        "capability_profile_id": "cap_general_qwen",
        "profile_name": "qwen_general",
        "provider_id": "qwen",
        "model_family": "qwen3.5",
        "capabilities": ["general_reasoning", "code_generation", "research_synthesis", "reviewable_candidate"],
        "supported_task_types": ["general", "docs", "code", "research", "review", "approval", "flowstate", "output"],
        "supported_risk_levels": [TaskRiskLevel.NORMAL.value, TaskRiskLevel.RISKY.value],
        "preferred_execution_backend": "qwen_executor",
    },
    {
        "capability_profile_id": "cap_highstakes_qwen",
        "profile_name": "qwen_highstakes",
        "provider_id": "qwen",
        "model_family": "qwen3.5",
        "capabilities": [
            "general_reasoning",
            "code_generation",
            "research_synthesis",
            "reviewable_candidate",
            "high_stakes_reasoning",
            "quant_analysis",
            "deployment_planning",
        ],
        "supported_task_types": ["deploy", "quant", "code", "research", "approval"],
        "supported_risk_levels": [TaskRiskLevel.HIGH_STAKES.value, TaskRiskLevel.RISKY.value],
        "preferred_execution_backend": "qwen_planner",
    },
    {
        "capability_profile_id": "cap_local_embeddings",
        "profile_name": "local_embeddings",
        "provider_id": "local",
        "model_family": "local",
        "capabilities": ["embedding", "local_support"],
        "supported_task_types": ["general", "flowstate", "output"],
        "supported_risk_levels": [
            TaskRiskLevel.NORMAL.value,
            TaskRiskLevel.RISKY.value,
            TaskRiskLevel.HIGH_STAKES.value,
        ],
        "preferred_execution_backend": "memory_spine",
    },
]

DEFAULT_RUNTIME_ROUTING_POLICY = {
    "schema_version": "v5.2_runtime_routing_v1",
    "defaults": {
        "preferred_provider": "qwen",
        "preferred_host_role": NodeRole.PRIMARY.value,
        "allowed_host_roles": [NodeRole.PRIMARY.value],
        "forbidden_host_roles": [NodeRole.BURST.value],
        "burst_allowed": False,
        "local_only": False,
    },
    "workload_policies": {
        "general": {"preferred_model": "Qwen3.5-35B"},
        "research": {"preferred_model": "Qwen3.5-35B"},
        "deploy": {"preferred_model": "Qwen3.5-122B"},
        "quant": {"preferred_model": "Qwen3.5-122B"},
        "embeddings": {
            "preferred_provider": "local",
            "preferred_model": "Local-Embeddings",
            "preferred_host_role": NodeRole.LOCAL.value,
            "allowed_host_roles": [NodeRole.LOCAL.value],
            "forbidden_host_roles": [NodeRole.PRIMARY.value, NodeRole.BURST.value],
            "allowed_families": ["local"],
            "local_only": True,
            "burst_allowed": False,
        },
    },
    "agent_policies": {
        "jarvis": {
            "preferred_provider": "qwen",
            "preferred_model": "Qwen3.5-9B",
            "preferred_host_role": NodeRole.PRIMARY.value,
            "allowed_host_roles": [NodeRole.PRIMARY.value],
            "forbidden_host_roles": [NodeRole.BURST.value],
            "allowed_fallbacks": ["Qwen3.5-35B", "Qwen3.5-122B"],
            "allowed_families": ["qwen3.5"],
            "burst_allowed": False,
        },
        "scout": {
            "preferred_provider": "qwen",
            "preferred_model": "Qwen3.5-35B",
            "preferred_host_role": NodeRole.PRIMARY.value,
            "allowed_host_roles": [NodeRole.PRIMARY.value],
            "forbidden_host_roles": [NodeRole.BURST.value],
            "allowed_fallbacks": ["Qwen3.5-122B"],
            "allowed_families": ["qwen3.5"],
            "burst_allowed": False,
        },
    },
    "channel_overrides": {},
}


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    base = Path(root or ROOT).resolve()
    path = base / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_registry_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("model_registry_entries", root=root)


def capability_profiles_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("capability_profiles", root=root)


def routing_policies_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("routing_policies", root=root)


def routing_overrides_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("routing_overrides", root=root)


def routing_requests_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("routing_requests", root=root)


def routing_decisions_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("routing_decisions", root=root)


def provider_adapter_results_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("provider_adapter_results", root=root)


def backend_assignments_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("backend_assignments", root=root)


def runtime_routing_policy_path(root: Optional[Path] = None) -> Path:
    return Path(root or ROOT).resolve() / "config" / "runtime_routing_policy.json"


def load_runtime_routing_policy(root: Optional[Path] = None) -> dict[str, Any]:
    path = runtime_routing_policy_path(root=root)
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_RUNTIME_ROUTING_POLICY))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return json.loads(json.dumps(DEFAULT_RUNTIME_ROUTING_POLICY))
    merged = json.loads(json.dumps(DEFAULT_RUNTIME_ROUTING_POLICY))
    for key in ("defaults", "workload_policies", "agent_policies", "channel_overrides"):
        merged[key].update(dict(payload.get(key) or {}))
    for key, value in payload.items():
        if key not in merged:
            merged[key] = value
    return merged


def _merge_runtime_route_policy(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in dict(override or {}).items():
        if value is None:
            continue
        if isinstance(value, list):
            merged[key] = list(value)
        elif isinstance(value, dict):
            merged[key] = dict(value)
        else:
            merged[key] = value
    return merged


def _available_nodes_by_role(root: Path) -> dict[str, list[str]]:
    ensure_default_nodes(root=root)
    available: dict[str, list[str]] = {}
    for node in list_nodes(root=root):
        if str(node.status).lower() in {"stopped", "unreachable", "draining"}:
            continue
        available.setdefault(node.node_role, []).append(node.node_name)
    return available


def resolve_runtime_route_policy(
    *,
    agent_id: Optional[str],
    channel: Optional[str],
    workload_type: str,
    root: Path,
) -> dict[str, Any]:
    policy = load_runtime_routing_policy(root=root)
    defaults = dict(policy.get("defaults") or {})
    workload_policy = dict((policy.get("workload_policies") or {}).get(workload_type) or {})
    channel_override = dict((policy.get("channel_overrides") or {}).get(str(channel or "")) or {})
    agent_policy = dict((policy.get("agent_policies") or {}).get(str(agent_id or "")) or {})

    resolved = _merge_runtime_route_policy(defaults, workload_policy)
    resolved = _merge_runtime_route_policy(resolved, channel_override)
    ignored_overrides: list[dict[str, Any]] = []
    if agent_policy:
        if channel_override:
            requested_role = channel_override.get("preferred_host_role")
            agent_allowed_roles = list(agent_policy.get("allowed_host_roles") or [])
            agent_forbidden_roles = set(agent_policy.get("forbidden_host_roles") or [])
            if requested_role and (
                (agent_allowed_roles and requested_role not in agent_allowed_roles)
                or requested_role in agent_forbidden_roles
            ):
                ignored_overrides.append(
                    {
                        "scope": "channel",
                        "channel": channel,
                        "reason": "channel_override_conflicts_with_agent_host_policy",
                        "requested_preferred_host_role": requested_role,
                    }
                )
        resolved = _merge_runtime_route_policy(resolved, agent_policy)
    if workload_policy.get("local_only", False):
        resolved = _merge_runtime_route_policy(resolved, workload_policy)

    allowed_roles = list(resolved.get("allowed_host_roles") or [])
    forbidden_roles = set(resolved.get("forbidden_host_roles") or [])
    if not resolved.get("burst_allowed", False):
        forbidden_roles.add(NodeRole.BURST.value)
    if resolved.get("local_only", False):
        allowed_roles = [NodeRole.LOCAL.value]
        forbidden_roles.update({NodeRole.PRIMARY.value, NodeRole.BURST.value})
        resolved["preferred_host_role"] = NodeRole.LOCAL.value
    if allowed_roles:
        allowed_roles = [role for role in allowed_roles if role not in forbidden_roles]
    resolved["allowed_host_roles"] = allowed_roles
    resolved["forbidden_host_roles"] = sorted(forbidden_roles)
    resolved["policy_sources"] = {
        "workload_type": workload_type,
        "agent_id": agent_id,
        "channel": channel,
        "has_agent_policy": bool(agent_policy),
        "has_channel_override": bool(channel_override),
        "ignored_overrides": ignored_overrides,
    }
    return resolved


def _record_path(folder: Path, record_id: str) -> Path:
    return folder / f"{record_id}.json"


def _save_record(folder: Path, record_id: str, payload: dict) -> dict:
    _record_path(folder, record_id).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _load_rows(folder: Path) -> list[dict]:
    rows: list[dict] = []
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return rows


def save_model_registry_entry(record: ModelRegistryEntryRecord, root: Optional[Path] = None) -> ModelRegistryEntryRecord:
    record.updated_at = now_iso()
    _save_record(model_registry_dir(root), record.model_registry_entry_id, record.to_dict())
    return record


def save_capability_profile(record: CapabilityProfileRecord, root: Optional[Path] = None) -> CapabilityProfileRecord:
    record.updated_at = now_iso()
    _save_record(capability_profiles_dir(root), record.capability_profile_id, record.to_dict())
    return record


def save_routing_request(record: RoutingRequestRecord, root: Optional[Path] = None) -> RoutingRequestRecord:
    record.updated_at = now_iso()
    _save_record(routing_requests_dir(root), record.routing_request_id, record.to_dict())
    return record


def save_routing_policy(record: RoutingPolicyRecord, root: Optional[Path] = None) -> RoutingPolicyRecord:
    record.updated_at = now_iso()
    _save_record(routing_policies_dir(root), record.routing_policy_id, record.to_dict())
    return record


def save_routing_override(record: RoutingOverrideRecord, root: Optional[Path] = None) -> RoutingOverrideRecord:
    record.updated_at = now_iso()
    _save_record(routing_overrides_dir(root), record.routing_override_id, record.to_dict())
    return record


def save_routing_decision(record: RoutingDecisionRecord, root: Optional[Path] = None) -> RoutingDecisionRecord:
    record.updated_at = now_iso()
    _save_record(routing_decisions_dir(root), record.routing_decision_id, record.to_dict())
    return record


def save_provider_adapter_result(record: ProviderAdapterResultRecord, root: Optional[Path] = None) -> ProviderAdapterResultRecord:
    record.updated_at = now_iso()
    _save_record(provider_adapter_results_dir(root), record.provider_adapter_result_id, record.to_dict())
    return record


def list_model_registry_entries(root: Optional[Path] = None) -> list[ModelRegistryEntryRecord]:
    return [ModelRegistryEntryRecord.from_dict(row) for row in _load_rows(model_registry_dir(root))]


def list_capability_profiles(root: Optional[Path] = None) -> list[CapabilityProfileRecord]:
    return [CapabilityProfileRecord.from_dict(row) for row in _load_rows(capability_profiles_dir(root))]


def list_routing_decisions(root: Optional[Path] = None) -> list[RoutingDecisionRecord]:
    rows = [RoutingDecisionRecord.from_dict(row) for row in _load_rows(routing_decisions_dir(root))]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def list_routing_policies(root: Optional[Path] = None) -> list[RoutingPolicyRecord]:
    rows = [RoutingPolicyRecord.from_dict(row) for row in _load_rows(routing_policies_dir(root))]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def list_routing_overrides(root: Optional[Path] = None) -> list[RoutingOverrideRecord]:
    rows = [RoutingOverrideRecord.from_dict(row) for row in _load_rows(routing_overrides_dir(root))]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def latest_routing_decision(root: Optional[Path] = None) -> Optional[RoutingDecisionRecord]:
    rows = list_routing_decisions(root=root)
    return rows[0] if rows else None


def latest_routing_policy(root: Optional[Path] = None) -> Optional[RoutingPolicyRecord]:
    rows = list_routing_policies(root=root)
    return rows[0] if rows else None


def _override_is_active(record: RoutingOverrideRecord) -> bool:
    if not record.active:
        return False
    if not record.expires_at:
        return True
    return record.expires_at > now_iso()


def _matching_override_scope(record: RoutingOverrideRecord, *, lane: str) -> bool:
    if record.scope_type == "global":
        return True
    return record.scope_type == "lane" and record.scope_id == lane


def resolve_routing_policy(*, lane: str, root: Optional[Path] = None) -> dict[str, Any]:
    root_path = Path(root or ROOT).resolve()
    ensure_default_routing_contracts(root_path)
    policy = latest_routing_policy(root=root_path)
    if policy is None:
        raise ValueError("No routing policy is available.")
    default_family = policy.default_family
    lane_override_family = policy.lane_overrides.get(lane)
    effective_default_family = lane_override_family or default_family
    allowed_families = list(policy.allowed_families or [default_family])
    if effective_default_family not in allowed_families:
        allowed_families.append(effective_default_family)
    applied_overrides: list[RoutingOverrideRecord] = []
    for record in list_routing_overrides(root=root_path):
        if not _override_is_active(record):
            continue
        if not _matching_override_scope(record, lane=lane):
            continue
        applied_overrides.append(record)
    applied_overrides.sort(key=lambda item: (item.scope_type == "lane", item.updated_at))
    latest_override = applied_overrides[-1] if applied_overrides else None
    if latest_override is not None:
        effective_default_family = latest_override.override_family
        if latest_override.allowed_families:
            allowed_families = list(latest_override.allowed_families)
        elif effective_default_family not in allowed_families:
            allowed_families.append(effective_default_family)
    if effective_default_family not in allowed_families:
        allowed_families.append(effective_default_family)
    return {
        "policy": policy,
        "effective_default_family": effective_default_family,
        "allowed_families": allowed_families,
        "lane_override_family": lane_override_family,
        "active_overrides": applied_overrides,
        "latest_override": latest_override,
    }


def ensure_default_routing_contracts(root: Optional[Path] = None) -> dict[str, list[dict]]:
    root_path = Path(root or ROOT).resolve()
    ensure_default_nodes(root=root_path)
    for profile in CAPABILITY_PROFILES:
        path = _record_path(capability_profiles_dir(root_path), profile["capability_profile_id"])
        if not path.exists():
            save_capability_profile(
                CapabilityProfileRecord(
                    capability_profile_id=profile["capability_profile_id"],
                    created_at=now_iso(),
                    updated_at=now_iso(),
                    profile_name=profile["profile_name"],
                    provider_id=profile.get("provider_id", "qwen"),
                    model_family=profile.get("model_family", "qwen3.5"),
                    capabilities=list(profile["capabilities"]),
                    supported_task_types=list(profile["supported_task_types"]),
                    supported_risk_levels=list(profile["supported_risk_levels"]),
                    preferred_execution_backend=profile["preferred_execution_backend"],
                ),
                root=root_path,
            )
    for model in ACTIVE_QWEN_MODELS:
        path = _record_path(model_registry_dir(root_path), model["model_registry_entry_id"])
        if not path.exists():
            save_model_registry_entry(
                ModelRegistryEntryRecord(
                    model_registry_entry_id=model["model_registry_entry_id"],
                    created_at=now_iso(),
                    updated_at=now_iso(),
                    provider_id=model.get("provider_id", "qwen"),
                    provider_kind=model.get("provider_kind", "local_openai_compatible"),
                    model_family=model.get("model_family", "qwen3.5"),
                    model_name=model["model_name"],
                    display_name=model["display_name"],
                    capability_profile_ids=list(model["capability_profile_ids"]),
                    policy_tags=["qwen_only", "approved"],
                    priority_rank=model["priority_rank"],
                    default_execution_backend=model["default_execution_backend"],
                    host_role=model.get("host_role", NodeRole.PRIMARY.value),
                    host_name=model.get("host_name"),
                    workload_tags=list(model.get("workload_tags", [])),
                    local_only=bool(model.get("local_only", False)),
                    active=True,
                ),
                root=root_path,
            )
    if latest_routing_policy(root=root_path) is None:
        save_routing_policy(
            RoutingPolicyRecord(
                routing_policy_id="routing_policy_default",
                created_at=now_iso(),
                updated_at=now_iso(),
                actor="system",
                lane="routing",
                default_family="qwen3.5",
                allowed_families=["qwen3.5"],
                lane_overrides={},
            ),
            root=root_path,
        )
    return {
        "model_registry_entries": [row.to_dict() for row in list_model_registry_entries(root_path)],
        "capability_profiles": [row.to_dict() for row in list_capability_profiles(root_path)],
        "routing_policies": [row.to_dict() for row in list_routing_policies(root_path)],
        "routing_overrides": [row.to_dict() for row in list_routing_overrides(root_path)],
    }


def infer_required_capabilities(*, task_type: str, risk_level: str, priority: str, normalized_request: str) -> list[str]:
    capabilities: set[str] = {"general_reasoning", "reviewable_candidate"}
    text = (normalized_request or "").lower()
    if task_type == "code":
        capabilities.add("code_generation")
    if task_type == "research":
        capabilities.add("research_synthesis")
    if task_type in {"deploy", "quant"} or risk_level == TaskRiskLevel.HIGH_STAKES.value:
        capabilities.update({"high_stakes_reasoning", "deployment_planning"})
    if task_type == "quant" or "quant" in text or "strategy" in text:
        capabilities.add("quant_analysis")
    if task_type in {"general", "docs"} and risk_level == TaskRiskLevel.NORMAL.value and priority == TaskPriority.LOW.value:
        capabilities.add("triage")
    return sorted(capabilities)


def _candidate_entry_pool(
    *,
    allowed_families: list[str],
    root: Path,
) -> list[ModelRegistryEntryRecord]:
    effective_controls = get_effective_control_state(root=root)
    disabled_providers = set(effective_controls.get("disabled_provider_ids", []))
    disabled_backends = set(effective_controls.get("disabled_execution_backends", []))
    return [
        row
        for row in list_model_registry_entries(root)
        if row.active
        and row.model_family in allowed_families
        and row.provider_id not in disabled_providers
        and row.default_execution_backend not in disabled_backends
    ]


def _profile_score(profile: CapabilityProfileRecord, required_capabilities: list[str], task_type: str, risk_level: str) -> tuple[int, int, int]:
    matched_capabilities = len(set(required_capabilities).intersection(profile.capabilities))
    covers_task_type = 1 if task_type in profile.supported_task_types else 0
    covers_risk = 1 if risk_level in profile.supported_risk_levels else 0
    return (matched_capabilities, covers_task_type, covers_risk)


def _choose_entry(
    *,
    required_capabilities: list[str],
    task_type: str,
    risk_level: str,
    allowed_families: list[str],
    preferred_family: str,
    runtime_route_policy: dict[str, Any],
    root: Path,
) -> tuple[ModelRegistryEntryRecord, CapabilityProfileRecord, list[str]]:
    entries = _candidate_entry_pool(allowed_families=allowed_families, root=root)
    profiles_by_id = {row.capability_profile_id: row for row in list_capability_profiles(root) if row.active}
    available_nodes = _available_nodes_by_role(root)
    preferred_provider = str(runtime_route_policy.get("preferred_provider") or "")
    preferred_model = str(runtime_route_policy.get("preferred_model") or "")
    preferred_host_role = str(runtime_route_policy.get("preferred_host_role") or "")
    allowed_host_roles = list(runtime_route_policy.get("allowed_host_roles") or [])
    forbidden_host_roles = set(runtime_route_policy.get("forbidden_host_roles") or [])
    local_only = bool(runtime_route_policy.get("local_only", False))
    allowed_fallbacks = list(runtime_route_policy.get("allowed_fallbacks") or [])

    filtered_entries: list[ModelRegistryEntryRecord] = []
    for entry in entries:
        entry_role = str(entry.host_role or NodeRole.PRIMARY.value)
        entry_host = str(entry.host_name or "")
        if allowed_host_roles and entry_role not in allowed_host_roles:
            continue
        if entry_role in forbidden_host_roles:
            continue
        if local_only and entry_role != NodeRole.LOCAL.value:
            continue
        if entry_host and entry_host not in available_nodes.get(entry_role, []):
            continue
        filtered_entries.append(entry)

    if preferred_model and not any(row.model_name == preferred_model for row in filtered_entries) and allowed_fallbacks:
        filtered_entries = [row for row in filtered_entries if row.model_name in allowed_fallbacks]

    if not filtered_entries:
        raise ValueError("No routing candidates available within the allowed provider/host-role policy.")

    ranked: list[tuple[tuple[int, int, int, int], ModelRegistryEntryRecord, CapabilityProfileRecord]] = []
    for entry in filtered_entries:
        for profile_id in entry.capability_profile_ids:
            profile = profiles_by_id.get(profile_id)
            if profile is None:
                continue
            score = _profile_score(profile, required_capabilities, task_type, risk_level)
            preferred_family_bonus = 1 if entry.model_family == preferred_family else 0
            preferred_provider_bonus = 1 if preferred_provider and entry.provider_id == preferred_provider else 0
            preferred_model_bonus = 1 if preferred_model and entry.model_name == preferred_model else 0
            preferred_host_bonus = 1 if preferred_host_role and str(entry.host_role or "") == preferred_host_role else 0
            ranked.append(
                (
                    (
                        preferred_model_bonus,
                        preferred_provider_bonus,
                        preferred_host_bonus,
                        *score,
                        preferred_family_bonus,
                        -entry.priority_rank,
                    ),
                    entry,
                    profile,
                )
            )
    if not ranked:
        raise ValueError("No active routing candidates were available for the current routing policy.")
    ranked.sort(key=lambda item: item[0], reverse=True)
    selected_entry, selected_profile = ranked[0][1], ranked[0][2]
    candidate_model_names = [item[1].model_name for item in ranked]
    seen: list[str] = []
    for model_name in candidate_model_names:
        if model_name not in seen:
            seen.append(model_name)
    return selected_entry, selected_profile, seen


def route_task_intent(
    *,
    task_id: str,
    normalized_request: str,
    task_type: str,
    risk_level: str,
    priority: str,
    actor: str,
    lane: str,
    agent_id: Optional[str] = None,
    channel: Optional[str] = None,
    workload_type: Optional[str] = None,
    root: Optional[Path] = None,
) -> dict:
    root_path = Path(root or ROOT).resolve()
    ensure_default_routing_contracts(root_path)
    modality_summary = build_modality_summary(root_path)
    resolved_workload_type = str(workload_type or task_type or "general")
    runtime_route_policy = resolve_runtime_route_policy(
        agent_id=agent_id or lane,
        channel=channel,
        workload_type=resolved_workload_type,
        root=root_path,
    )
    effective_policy = resolve_routing_policy(lane=lane, root=root_path)
    policy = effective_policy["policy"]
    latest_override = effective_policy["latest_override"]
    allowed_families = list(runtime_route_policy.get("allowed_families") or effective_policy["allowed_families"])
    preferred_family = str(effective_policy["effective_default_family"])
    if runtime_route_policy.get("preferred_provider") == "local":
        preferred_family = "local"
    assert_control_allows(
        action="route_selection",
        root=root_path,
        task_id=task_id,
        actor=actor,
        lane=lane,
    )
    effective_controls = get_effective_control_state(root=root_path)
    policy_constraints = {
        "default_family": preferred_family,
        "allowed_families": list(allowed_families),
        "provider_policy": "qwen_only" if allowed_families == ["qwen3.5"] else "policy_override",
        "routing_policy_id": policy.routing_policy_id,
        "lane_override_family": effective_policy["lane_override_family"],
        "active_override_ids": [row.routing_override_id for row in effective_policy["active_overrides"]],
        "latest_override_id": latest_override.routing_override_id if latest_override is not None else None,
        "enabled_input_modalities": list(modality_summary.get("enabled_input_modalities", [])),
        "multimodal_runtime_enabled": False,
        "disabled_provider_ids": list(effective_controls.get("disabled_provider_ids", [])),
        "disabled_execution_backends": list(effective_controls.get("disabled_execution_backends", [])),
        "workload_type": resolved_workload_type,
        "agent_id": agent_id or lane,
        "channel": channel,
        "preferred_provider": runtime_route_policy.get("preferred_provider"),
        "preferred_model": runtime_route_policy.get("preferred_model"),
        "preferred_host_role": runtime_route_policy.get("preferred_host_role"),
        "allowed_host_roles": list(runtime_route_policy.get("allowed_host_roles") or []),
        "forbidden_host_roles": list(runtime_route_policy.get("forbidden_host_roles") or []),
        "burst_allowed": bool(runtime_route_policy.get("burst_allowed", False)),
        "local_only": bool(runtime_route_policy.get("local_only", False)),
        "allowed_fallbacks": list(runtime_route_policy.get("allowed_fallbacks") or []),
        "ignored_overrides": list((runtime_route_policy.get("policy_sources") or {}).get("ignored_overrides") or []),
    }
    required_capabilities = infer_required_capabilities(
        task_type=task_type,
        risk_level=risk_level,
        priority=priority,
        normalized_request=normalized_request,
    )
    if resolved_workload_type == "embeddings":
        required_capabilities = sorted(set(required_capabilities + ["embedding", "local_support"]))
    request = save_routing_request(
        RoutingRequestRecord(
            routing_request_id=new_id("rreq"),
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            normalized_request=normalized_request,
            task_type=task_type,
            risk_level=risk_level,
            priority=priority,
            required_capabilities=required_capabilities,
            policy_constraints=policy_constraints,
            status="completed",
        ),
        root=root_path,
    )
    entry, profile, candidate_model_names = _choose_entry(
        required_capabilities=required_capabilities,
        task_type=task_type,
        risk_level=risk_level,
        allowed_families=allowed_families,
        preferred_family=preferred_family,
        runtime_route_policy=runtime_route_policy,
        root=root_path,
    )
    eligible_provider_ids = sorted({row.provider_id for row in _candidate_entry_pool(allowed_families=allowed_families, root=root_path)})
    decision = save_routing_decision(
        RoutingDecisionRecord(
            routing_decision_id=new_id("rdec"),
            routing_request_id=request.routing_request_id,
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            selected_model_registry_entry_id=entry.model_registry_entry_id,
            selected_capability_profile_id=profile.capability_profile_id,
            selected_provider_id=entry.provider_id,
            selected_model_name=entry.model_name,
            selected_execution_backend=profile.preferred_execution_backend or entry.default_execution_backend,
            selected_node_role=entry.host_role or NodeRole.PRIMARY.value,
            selected_host_name=entry.host_name,
            selection_reason=(
                f"Matched capabilities {required_capabilities} under routing family {preferred_family} "
                f"with provider {entry.provider_id} on host role {entry.host_role or NodeRole.PRIMARY.value} "
                f"using profile {profile.profile_name}."
            ),
            candidate_model_names=candidate_model_names,
            policy_constraints={**policy_constraints, "eligible_provider_ids": eligible_provider_ids},
            status="selected",
        ),
        root=root_path,
    )
    adapter_result = save_provider_adapter_result(
        ProviderAdapterResultRecord(
            provider_adapter_result_id=new_id("pres"),
            routing_decision_id=decision.routing_decision_id,
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            provider_id=entry.provider_id,
            model_name=entry.model_name,
            execution_backend=decision.selected_execution_backend,
            adapter_kind="routing_binding",
            status="ready",
            summary="Bound task to active provider-agnostic Qwen routing contract.",
            metadata={
                "model_registry_entry_id": entry.model_registry_entry_id,
                "capability_profile_id": profile.capability_profile_id,
                "candidate_model_names": candidate_model_names,
                "selected_node_role": decision.selected_node_role,
                "selected_host_name": decision.selected_host_name,
            },
        ),
        root=root_path,
    )
    assignment = save_backend_assignment(
        BackendAssignmentRecord(
            backend_assignment_id=new_id("bassign"),
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            routing_request_id=request.routing_request_id,
            routing_decision_id=decision.routing_decision_id,
            provider_adapter_result_id=adapter_result.provider_adapter_result_id,
            provider_id=entry.provider_id,
            model_name=entry.model_name,
            execution_backend=decision.selected_execution_backend,
            selected_node_role=decision.selected_node_role,
            selected_host_name=decision.selected_host_name,
            model_registry_entry_id=entry.model_registry_entry_id,
            capability_profile_id=profile.capability_profile_id,
            assignment_reason=decision.selection_reason,
            status="assigned",
            source_refs={
                "routing_policy_id": policy.routing_policy_id,
                "routing_override_id": latest_override.routing_override_id if latest_override is not None else None,
            },
        ),
        root=root_path,
    )
    provenance = save_routing_provenance(
        RoutingProvenanceRecord(
            routing_provenance_id=new_id("rprov"),
            routing_request_id=request.routing_request_id,
            routing_decision_id=decision.routing_decision_id,
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            selected_provider_id=entry.provider_id,
            selected_model_name=entry.model_name,
            selected_execution_backend=decision.selected_execution_backend,
            selected_node_role=decision.selected_node_role,
            selected_host_name=decision.selected_host_name,
            source_refs={
                "provider_adapter_result_id": adapter_result.provider_adapter_result_id,
                "backend_assignment_id": assignment.backend_assignment_id,
                "model_registry_entry_id": entry.model_registry_entry_id,
                "capability_profile_id": profile.capability_profile_id,
            },
            replay_input={
                "task_type": task_type,
                "risk_level": risk_level,
                "priority": priority,
                "workload_type": resolved_workload_type,
                "normalized_request": normalized_request,
                "required_capabilities": list(required_capabilities),
                "policy_constraints": {**dict(policy_constraints), "eligible_provider_ids": eligible_provider_ids},
            },
        ),
        root=root_path,
    )
    return {
        "request": request.to_dict(),
        "decision": decision.to_dict(),
        "provider_adapter_result": adapter_result.to_dict(),
        "backend_assignment": assignment.to_dict(),
        "provenance": provenance.to_dict(),
        "active_registry": {
            "provider_policy": "qwen_only" if allowed_families == ["qwen3.5"] else "policy_override",
            "default_family": preferred_family,
            "allowed_families": list(allowed_families),
            "eligible_provider_ids": eligible_provider_ids,
            "active_model_names": [
                row.model_name
                for row in sorted(
                    [row for row in list_model_registry_entries(root_path) if row.active and row.model_family in allowed_families],
                    key=lambda row: row.priority_rank,
                    reverse=True,
                )
            ],
            "active_model_count": sum(1 for row in list_model_registry_entries(root_path) if row.active and row.model_family in allowed_families),
            "enabled_input_modalities": list(modality_summary.get("enabled_input_modalities", [])),
            "routing_policy_id": policy.routing_policy_id,
            "lane_override_family": effective_policy["lane_override_family"],
            "latest_override_id": latest_override.routing_override_id if latest_override is not None else None,
            "disabled_provider_ids": list(effective_controls.get("disabled_provider_ids", [])),
            "disabled_execution_backends": list(effective_controls.get("disabled_execution_backends", [])),
        },
    }


def build_model_registry_summary(root: Optional[Path] = None) -> dict:
    root_path = Path(root or ROOT).resolve()
    ensure_default_routing_contracts(root_path)
    modality_summary = build_modality_summary(root_path)
    effective_controls = get_effective_control_state(root=root_path)
    effective_policy = resolve_routing_policy(lane="routing", root=root_path)
    policy = effective_policy["policy"]
    active_overrides = [row for row in list_routing_overrides(root_path) if _override_is_active(row)]
    latest_override = active_overrides[0] if active_overrides else None
    allowed_families = list(effective_policy["allowed_families"])
    preferred_family = str(effective_policy["effective_default_family"])
    disabled_providers = set(effective_controls.get("disabled_provider_ids", []))
    disabled_backends = set(effective_controls.get("disabled_execution_backends", []))
    entries = [
        row
        for row in list_model_registry_entries(root_path)
        if row.active
        and row.model_family in allowed_families
        and row.provider_id not in disabled_providers
        and row.default_execution_backend not in disabled_backends
    ]
    decisions = list_routing_decisions(root_path)
    latest = decisions[0].to_dict() if decisions else None
    backend_assignment_summary = build_backend_assignment_summary(root=root_path)
    return {
        "provider_policy": "qwen_only" if allowed_families == ["qwen3.5"] else "policy_override",
        "architecture_mode": "provider_agnostic",
        "routing_policy_id": policy.routing_policy_id,
        "default_family": preferred_family,
        "allowed_families": list(allowed_families),
        "lane_overrides": dict(policy.lane_overrides),
        "latest_override": latest_override.to_dict() if latest_override is not None else None,
        "active_override_count": len(active_overrides),
        "provider_ids": sorted({row.provider_id for row in entries}),
        "active_model_names": [row.model_name for row in sorted(entries, key=lambda row: row.priority_rank, reverse=True)],
        "active_model_count": len(entries),
        "enabled_input_modalities": list(modality_summary.get("enabled_input_modalities", [])),
        "multimodal_runtime_enabled": False,
        "disabled_provider_ids": get_effective_control_state(root=root_path).get("disabled_provider_ids", []),
        "disabled_execution_backends": get_effective_control_state(root=root_path).get("disabled_execution_backends", []),
        "latest_routing_decision": latest,
        "backend_assignment_summary": backend_assignment_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the active provider-agnostic routing registry.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    ensure_default_routing_contracts(root)
    print(json.dumps(build_model_registry_summary(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
