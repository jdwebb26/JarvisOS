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
    AuthorityClass,
    BackendAssignmentRecord,
    CapabilityProfileRecord,
    ModelRegistryEntryRecord,
    ModelTier,
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
from runtime.core.backend_assignments import (
    assert_forbidden_downgrade,
    build_backend_assignment_summary,
    minimum_tier_by_authority_class,
    save_backend_assignment,
)
from runtime.core.degradation_policy import list_active_degradation_modes
from runtime.core.heartbeat_reports import heartbeat_is_stale, read_node_heartbeat
from runtime.core.node_registry import ensure_default_nodes, get_node, list_nodes
from runtime.core.task_lease import get_active_lease
from runtime.controls.control_store import assert_control_allows, get_effective_control_state
from runtime.core.provenance_store import save_routing_provenance
from runtime.core.modality_contracts import build_modality_summary, ensure_default_modality_contracts
from runtime.core.agent_roster import build_agent_roster_summary
from runtime.core.runtime_profiles import apply_profile_overrides, get_active_profile


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
    # Kitt's preferred provider — NVIDIA-hosted Kimi 2.5.
    # Execution backend is "nvidia_executor"; Python adapter + gateway both dispatch via NVIDIA API.
    # Fallback to qwen3.5 is defined in runtime_routing_policy.json agent_policies.kitt.allowed_fallbacks.
    {
        "model_registry_entry_id": "model_kimi_k2_5_nvidia",
        "provider_id": "nvidia",
        "provider_kind": "remote_openai_compatible",
        "model_family": "kimi",
        "model_name": "moonshotai/kimi-k2.5",
        "display_name": "Kimi 2.5 (NVIDIA)",
        "priority_rank": 15,
        "default_execution_backend": "nvidia_executor",
        "capability_profile_ids": ["cap_general_kimi"],
        "host_role": NodeRole.PRIMARY.value,
        "host_name": None,  # Remote API provider — not bound to a local host node
        "workload_tags": ["general", "research", "quant"],
        "policy_tags": ["nvidia_approved"],
    },
    # OpenAI GPT — disabled by default (requires OPENAI_API_KEY).
    # A ChatGPT subscription does NOT fund API usage.
    # See https://platform.openai.com/account/billing for API billing.
    {
        "model_registry_entry_id": "model_gpt_4_1_mini_openai",
        "provider_id": "openai",
        "provider_kind": "remote_openai_compatible",
        "model_family": "gpt",
        "model_name": "gpt-4.1-mini",
        "display_name": "GPT-4.1 Mini (OpenAI)",
        "priority_rank": 12,
        "default_execution_backend": "openai_executor",
        "capability_profile_ids": ["cap_general_gpt"],
        "host_role": NodeRole.PRIMARY.value,
        "host_name": None,  # Remote API provider
        "workload_tags": ["general", "research", "code"],
        "policy_tags": ["openai_approved"],
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
    # Kitt's capability profile — NVIDIA-hosted Kimi 2.5.
    # Covers quant/high-stakes so Kitt's preferred model is not filtered out for quant tasks.
    {
        "capability_profile_id": "cap_general_kimi",
        "profile_name": "kimi_general",
        "provider_id": "nvidia",
        "model_family": "kimi",
        "capabilities": [
            "general_reasoning",
            "code_generation",
            "research_synthesis",
            "reviewable_candidate",
            "high_stakes_reasoning",
            "quant_analysis",
            "deployment_planning",
        ],
        "supported_task_types": ["general", "docs", "code", "research", "review", "approval", "flowstate", "output", "deploy", "quant"],
        "supported_risk_levels": [TaskRiskLevel.NORMAL.value, TaskRiskLevel.RISKY.value, TaskRiskLevel.HIGH_STAKES.value],
        "preferred_execution_backend": "nvidia_executor",
    },
    # OpenAI GPT capability profile — general-purpose reasoning + code.
    {
        "capability_profile_id": "cap_general_gpt",
        "profile_name": "gpt_general",
        "provider_id": "openai",
        "model_family": "gpt",
        "capabilities": [
            "general_reasoning",
            "code_generation",
            "research_synthesis",
            "reviewable_candidate",
        ],
        "supported_task_types": ["general", "docs", "code", "research", "review", "flowstate", "output"],
        "supported_risk_levels": [TaskRiskLevel.NORMAL.value, TaskRiskLevel.RISKY.value],
        "preferred_execution_backend": "openai_executor",
    },
    {
        "model_registry_entry_id": "model_vizor_personal",
        "provider_id": "vizor_personal",
        "provider_kind": "local_openai_compatible",
        "model_family": "qwen3-vl",
        "model_name": "vizor-personal",
        "display_name": "Vizor EyeNet-Personal",
        "priority_rank": 15,
        "default_execution_backend": "openai_executor",
        "capability_profile_ids": ["cap_general_qwen", "cap_multimodal"],
        "host_role": NodeRole.PRIMARY.value,
        "host_name": "NIMO",
        "workload_tags": ["visual_quant", "chart_analysis"],
        "supported_task_types": ["general", "quant"],
        "supported_risk_levels": [TaskRiskLevel.NORMAL.value],
        "preferred_execution_backend": "openai_executor",
    },
    {
        "model_registry_entry_id": "model_vizor_swarm",
        "provider_id": "vizor_swarm",
        "provider_kind": "local_openai_compatible",
        "model_family": "qwen3-vl",
        "model_name": "vizor-swarm",
        "display_name": "Vizor EyeNet-Swarm",
        "priority_rank": 25,
        "default_execution_backend": "openai_executor",
        "capability_profile_ids": ["cap_general_qwen", "cap_multimodal"],
        "host_role": NodeRole.PRIMARY.value,
        "host_name": "NIMO",
        "workload_tags": ["visual_quant", "chart_analysis"],
        "supported_task_types": ["general", "quant"],
        "supported_risk_levels": [TaskRiskLevel.NORMAL.value],
        "preferred_execution_backend": "openai_executor",
    },
    {
        "model_registry_entry_id": "model_ict_expert",
        "provider_id": "ict_expert",
        "provider_kind": "local_openai_compatible",
        "model_family": "qwen3-vl",
        "model_name": "ict-expert-v1",
        "display_name": "ICT Methodology Expert",
        "priority_rank": 15,
        "default_execution_backend": "openai_executor",
        "capability_profile_ids": ["cap_general_qwen", "cap_multimodal"],
        "host_role": NodeRole.PRIMARY.value,
        "host_name": "NIMO",
        "workload_tags": ["ict_methodology", "chart_analysis"],
        "supported_task_types": ["general", "quant"],
        "supported_risk_levels": [TaskRiskLevel.NORMAL.value],
        "preferred_execution_backend": "openai_executor",
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
        "hal": {
            "preferred_provider": "qwen",
            "preferred_model": "Qwen3.5-35B",
            "preferred_host_role": NodeRole.PRIMARY.value,
            "allowed_host_roles": [NodeRole.PRIMARY.value],
            "forbidden_host_roles": [NodeRole.BURST.value],
            "allowed_fallbacks": ["Qwen3.5-122B"],
            "allowed_families": ["qwen3.5"],
            "burst_allowed": False,
        },
        "archimedes": {
            "preferred_provider": "qwen",
            "preferred_model": "Qwen3.5-122B",
            "preferred_host_role": NodeRole.PRIMARY.value,
            "allowed_host_roles": [NodeRole.PRIMARY.value],
            "forbidden_host_roles": [NodeRole.BURST.value],
            "allowed_fallbacks": ["Qwen3.5-35B"],
            "allowed_families": ["qwen3.5"],
            "burst_allowed": False,
        },
        "anton": {
            "preferred_provider": "qwen",
            "preferred_model": "Qwen3.5-122B",
            "preferred_host_role": NodeRole.PRIMARY.value,
            "allowed_host_roles": [NodeRole.PRIMARY.value],
            "forbidden_host_roles": [NodeRole.BURST.value],
            "allowed_fallbacks": ["Qwen3.5-35B"],
            "allowed_families": ["qwen3.5"],
            "burst_allowed": False,
        },
        "hermes": {
            "preferred_provider": "qwen",
            "preferred_model": "Qwen3.5-122B",
            "preferred_host_role": NodeRole.PRIMARY.value,
            "allowed_host_roles": [NodeRole.PRIMARY.value],
            "forbidden_host_roles": [NodeRole.BURST.value],
            "allowed_fallbacks": ["Qwen3.5-35B"],
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
        "bowser": {
            "preferred_provider": "qwen",
            "preferred_model": "Qwen3.5-35B",
            "preferred_host_role": NodeRole.PRIMARY.value,
            "allowed_host_roles": [NodeRole.PRIMARY.value],
            "forbidden_host_roles": [NodeRole.BURST.value],
            "allowed_fallbacks": ["Qwen3.5-122B"],
            "allowed_families": ["qwen3.5"],
            "burst_allowed": False,
        },
        "muse": {
            "preferred_provider": "qwen",
            "preferred_model": "Qwen3.5-35B",
            "preferred_host_role": NodeRole.PRIMARY.value,
            "allowed_host_roles": [NodeRole.PRIMARY.value],
            "forbidden_host_roles": [NodeRole.BURST.value],
            "allowed_fallbacks": ["Qwen3.5-9B"],
            "allowed_families": ["qwen3.5"],
            "burst_allowed": False,
        },
        "ralph": {
            "preferred_provider": "qwen",
            "preferred_model": "Qwen3.5-35B",
            "preferred_host_role": NodeRole.PRIMARY.value,
            "allowed_host_roles": [NodeRole.PRIMARY.value],
            "forbidden_host_roles": [NodeRole.BURST.value],
            "allowed_fallbacks": ["Qwen3.5-122B"],
            "allowed_families": ["qwen3.5"],
            "burst_allowed": False,
        },
        "vizor": {
            "preferred_provider": "vizor_personal",
            "preferred_model": "vizor-personal",
            "preferred_host_role": NodeRole.PRIMARY.value,
            "allowed_host_roles": [NodeRole.PRIMARY.value],
            "forbidden_host_roles": [NodeRole.BURST.value],
            "allowed_fallbacks": ["vizor-swarm", "Qwen3.5-35B"],
            "allowed_families": ["qwen3-vl", "qwen3.5"],
            "burst_allowed": False,
        },
        "ict": {
            "preferred_provider": "ict_expert",
            "preferred_model": "ict-expert-v1",
            "preferred_host_role": NodeRole.PRIMARY.value,
            "allowed_host_roles": [NodeRole.PRIMARY.value],
            "forbidden_host_roles": [NodeRole.BURST.value],
            "allowed_fallbacks": ["Qwen3.5-35B", "Qwen3.5-122B"],
            "allowed_families": ["qwen3-vl", "qwen3.5"],
            "burst_allowed": False,
        },
    },
    "channel_overrides": {},
}

_TIER_FLOOR_ORDER = {
    ModelTier.ROUTING.value: 0,
    ModelTier.GENERAL.value: 1,
    ModelTier.FLOWSTATE.value: 1,
    ModelTier.CODER.value: 2,
    ModelTier.MULTIMODAL.value: 2,
    ModelTier.HEAVY_REASONING.value: 3,
}
_HEALTHY_STATUSES = {"healthy", "ok", "idle", "ready"}
_DEGRADED_STATUSES = {"degraded", "warning"}
_UNHEALTHY_STATUSES = {"unhealthy", "down", "failed", "unreachable", "stopped", "draining", "offline"}


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


def _ensure_mapping(value: Any, *, context: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Invalid runtime routing policy: {context} must be a JSON object.")
    return dict(value)


def _ensure_string_list(value: Any, *, context: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"Invalid runtime routing policy: {context} must be a list of non-empty strings.")
    return [item.strip() for item in value]


def _ensure_optional_string(value: Any, *, context: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid runtime routing policy: {context} must be a non-empty string when provided.")
    return value.strip()


def _ensure_optional_bool(value: Any, *, context: str) -> Optional[bool]:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"Invalid runtime routing policy: {context} must be a boolean when provided.")
    return value


def _validate_host_role_list(roles: list[str], *, context: str) -> list[str]:
    invalid = [role for role in roles if role not in NodeRole.values()]
    if invalid:
        raise ValueError(
            f"Invalid runtime routing policy: {context} contains unknown host roles {sorted(invalid)}."
        )
    seen: list[str] = []
    for role in roles:
        if role not in seen:
            seen.append(role)
    return seen


def _validate_runtime_route_policy_block(block: dict[str, Any], *, context: str) -> dict[str, Any]:
    allowed_keys = {
        "preferred_provider",
        "preferred_model",
        "preferred_host_role",
        "allowed_host_roles",
        "forbidden_host_roles",
        "allowed_fallbacks",
        "allowed_families",
        "burst_allowed",
        "local_only",
    }
    unknown_keys = sorted(set(block) - allowed_keys)
    if unknown_keys:
        raise ValueError(f"Invalid runtime routing policy: {context} contains unknown keys {unknown_keys}.")
    normalized: dict[str, Any] = {}
    preferred_provider = _ensure_optional_string(block.get("preferred_provider"), context=f"{context}.preferred_provider")
    preferred_model = _ensure_optional_string(block.get("preferred_model"), context=f"{context}.preferred_model")
    preferred_host_role = _ensure_optional_string(block.get("preferred_host_role"), context=f"{context}.preferred_host_role")
    if preferred_host_role is not None and preferred_host_role not in NodeRole.values():
        raise ValueError(
            f"Invalid runtime routing policy: {context}.preferred_host_role must be one of {sorted(NodeRole.values())}."
        )
    if preferred_provider is not None:
        normalized["preferred_provider"] = preferred_provider
    if preferred_model is not None:
        normalized["preferred_model"] = preferred_model
    if preferred_host_role is not None:
        normalized["preferred_host_role"] = preferred_host_role

    allowed_host_roles = _validate_host_role_list(
        _ensure_string_list(block.get("allowed_host_roles"), context=f"{context}.allowed_host_roles"),
        context=f"{context}.allowed_host_roles",
    )
    forbidden_host_roles = _validate_host_role_list(
        _ensure_string_list(block.get("forbidden_host_roles"), context=f"{context}.forbidden_host_roles"),
        context=f"{context}.forbidden_host_roles",
    )
    if "allowed_host_roles" in block:
        normalized["allowed_host_roles"] = allowed_host_roles
    if "forbidden_host_roles" in block:
        normalized["forbidden_host_roles"] = forbidden_host_roles

    allowed_fallbacks = _ensure_string_list(block.get("allowed_fallbacks"), context=f"{context}.allowed_fallbacks")
    allowed_families = _ensure_string_list(block.get("allowed_families"), context=f"{context}.allowed_families")
    if "allowed_fallbacks" in block:
        normalized["allowed_fallbacks"] = allowed_fallbacks
    if "allowed_families" in block:
        normalized["allowed_families"] = allowed_families

    burst_allowed = _ensure_optional_bool(block.get("burst_allowed"), context=f"{context}.burst_allowed")
    local_only = _ensure_optional_bool(block.get("local_only"), context=f"{context}.local_only")
    if burst_allowed is not None:
        normalized["burst_allowed"] = burst_allowed
    if local_only is not None:
        normalized["local_only"] = local_only

    return normalized


def validate_runtime_routing_policy(payload: dict[str, Any]) -> dict[str, Any]:
    policy = _ensure_mapping(payload, context="runtime_routing_policy")
    validated: dict[str, Any] = {
        "schema_version": str(policy.get("schema_version") or DEFAULT_RUNTIME_ROUTING_POLICY["schema_version"]),
        "defaults": _validate_runtime_route_policy_block(
            _ensure_mapping(policy.get("defaults"), context="defaults"),
            context="defaults",
        ),
        "workload_policies": {},
        "agent_policies": {},
        "channel_overrides": {},
    }
    for section in ("workload_policies", "agent_policies", "channel_overrides"):
        raw_section = _ensure_mapping(policy.get(section), context=section)
        validated_section: dict[str, Any] = {}
        for key, value in raw_section.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"Invalid runtime routing policy: {section} keys must be non-empty strings.")
            validated_section[key.strip()] = _validate_runtime_route_policy_block(
                _ensure_mapping(value, context=f"{section}.{key}"),
                context=f"{section}.{key}",
            )
        validated[section] = validated_section
    return validated


def load_runtime_routing_policy(root: Optional[Path] = None) -> dict[str, Any]:
    resolved_root = Path(root or ROOT).resolve()
    path = runtime_routing_policy_path(root=resolved_root)
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_RUNTIME_ROUTING_POLICY))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid runtime routing policy JSON at {path}: {exc}") from exc
    merged = json.loads(json.dumps(DEFAULT_RUNTIME_ROUTING_POLICY))
    validated = validate_runtime_routing_policy(payload)
    for key in ("defaults", "workload_policies", "agent_policies", "channel_overrides"):
        merged[key].update(validated.get(key) or {})
    for key, value in payload.items():
        if key not in merged:
            merged[key] = value

    # Apply active runtime profile overrides to agent_policies
    try:
        profile_state = get_active_profile(root=resolved_root)
        profile_name = profile_state.get("profile", "local_only")
        merged["agent_policies"] = apply_profile_overrides(
            merged["agent_policies"], profile_name
        )
        merged["_active_profile"] = profile_name
    except Exception:
        merged["_active_profile"] = "local_only"

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


def _infer_authority_class(*, task_type: str, risk_level: str) -> str:
    if task_type in {"deploy", "quant"} or risk_level == TaskRiskLevel.HIGH_STAKES.value:
        return AuthorityClass.APPROVAL_REQUIRED.value
    if task_type == "code" or risk_level == TaskRiskLevel.RISKY.value:
        return AuthorityClass.REVIEW_REQUIRED.value
    return AuthorityClass.SUGGEST_ONLY.value


def _infer_model_tier(entry: ModelRegistryEntryRecord, profile: CapabilityProfileRecord) -> str:
    name = str(entry.model_name or "").lower()
    capabilities = set(profile.capabilities or [])
    if "122" in name or "high_stakes_reasoning" in capabilities or "deployment_planning" in capabilities:
        return ModelTier.HEAVY_REASONING.value
    if "35" in name or {"general_reasoning", "code_generation", "research_synthesis"}.intersection(capabilities):
        return ModelTier.GENERAL.value
    if "embedding" in capabilities or entry.provider_id == "local":
        return ModelTier.GENERAL.value
    return ModelTier.ROUTING.value


def _tier_meets_floor(candidate_tier: str, minimum_tier: str) -> bool:
    return _TIER_FLOOR_ORDER.get(candidate_tier, 0) >= _TIER_FLOOR_ORDER.get(minimum_tier, 0)


def _latest_backend_health_snapshot(root: Path) -> dict[str, Any]:
    folder = root / "state" / "backend_health"
    latest: tuple[str, dict[str, Any]] | None = None
    if not folder.exists():
        return {}
    for path in sorted(folder.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        stamp = str(payload.get("generated_at") or payload.get("updated_at") or payload.get("created_at") or "")
        if latest is None or stamp > latest[0]:
            latest = (stamp, payload)
    return dict(latest[1]) if latest else {}


def _status_rank(value: str) -> int:
    lowered = str(value or "").strip().lower()
    if lowered in _HEALTHY_STATUSES:
        return 3
    if lowered in _DEGRADED_STATUSES:
        return 2
    if lowered:
        return 1
    return 0


def _backend_health_status(backend_runtime: str, *, root: Path) -> str:
    latest = _latest_backend_health_snapshot(root)
    lanes = list(latest.get("lanes") or [])
    statuses = [
        str(row.get("status") or "unknown").strip().lower()
        for row in lanes
        if str(row.get("backend") or "").strip() == str(backend_runtime or "").strip()
    ]
    if not statuses:
        return "unknown"
    if any(status in _UNHEALTHY_STATUSES for status in statuses):
        return "unhealthy"
    if any(status in _DEGRADED_STATUSES for status in statuses):
        return "degraded"
    if any(status in _HEALTHY_STATUSES for status in statuses):
        return "healthy"
    return statuses[0]


def _node_runtime_signal(node_name: Optional[str], *, root: Path) -> dict[str, Any]:
    if not node_name:
        # Remote API providers (host_name=None) are not bound to a local host node.
        # Treat as healthy by default; degradation is signalled via degradation_policy events.
        return {
            "node_name": None,
            "node_status": "healthy",
            "heartbeat_known": False,
            "current_task_count": None,
            "available_backends": [],
        }
    node = get_node(node_name, root=root)
    heartbeat = read_node_heartbeat(node_name, root=root)
    heartbeat_known = heartbeat is not None and not heartbeat_is_stale(heartbeat)
    if heartbeat_known:
        return {
            "node_name": node_name,
            "node_status": str(heartbeat.get("node_status") or heartbeat.get("heartbeat_status") or "unknown").lower(),
            "heartbeat_known": True,
            "current_task_count": heartbeat.get("current_task_count"),
            "available_backends": list(heartbeat.get("available_backends") or []),
        }
    return {
        "node_name": node_name,
        "node_status": str(getattr(node, "status", "unknown") or "unknown").lower(),
        "heartbeat_known": False,
        "current_task_count": None,
        "available_backends": list(getattr(node, "available_backends", []) or []),
    }


def _latency_preference(*, workload_type: str, task_type: str, priority: str, normalized_request: str) -> str:
    token_count = len([part for part in str(normalized_request or "").split() if part])
    if workload_type == "embeddings":
        return "local_only"
    if task_type == "general" and priority in {TaskPriority.LOW.value, TaskPriority.NORMAL.value} and token_count <= 24:
        return "low_latency"
    if task_type in {"research", "docs"} or token_count >= 80:
        return "throughput"
    return "balanced"


def _context_estimate(normalized_request: str) -> dict[str, Any]:
    token_count = len([part for part in str(normalized_request or "").split() if part])
    if token_count >= 120:
        bucket = "large"
    elif token_count >= 40:
        bucket = "medium"
    else:
        bucket = "small"
    return {
        "token_estimate": token_count * 24,
        "request_token_count": token_count,
        "bucket": bucket,
    }


def _candidate_latency_fit(*, tier: str, latency_preference: str) -> int:
    if latency_preference == "local_only":
        return 3 if tier == ModelTier.GENERAL.value else 1
    if latency_preference == "low_latency":
        if tier == ModelTier.ROUTING.value:
            return 3
        if tier == ModelTier.GENERAL.value:
            return 2
        return 1
    if latency_preference == "throughput":
        if tier == ModelTier.HEAVY_REASONING.value:
            return 3
        if tier == ModelTier.GENERAL.value:
            return 2
        return 1
    if tier == ModelTier.GENERAL.value:
        return 3
    if tier == ModelTier.HEAVY_REASONING.value:
        return 2
    return 1


def _candidate_context_fit(*, tier: str, context_bucket: str) -> int:
    if context_bucket == "large":
        if tier == ModelTier.HEAVY_REASONING.value:
            return 3
        if tier == ModelTier.GENERAL.value:
            return 2
        return 1
    if context_bucket == "medium":
        if tier in {ModelTier.GENERAL.value, ModelTier.HEAVY_REASONING.value}:
            return 3
        return 2
    if tier == ModelTier.ROUTING.value:
        return 3
    if tier == ModelTier.GENERAL.value:
        return 2
    return 1


def _active_degradation_index(*, root: Path) -> dict[str, Any]:
    active = list_active_degradation_modes(root=root)
    return {
        "by_subsystem": {str(row.get("subsystem")): dict(row) for row in active},
        "by_mode": {str(row.get("degradation_mode")): dict(row) for row in active},
        "items": active,
    }


def _lease_signal(*, task_id: str, entry: ModelRegistryEntryRecord, backend_runtime: str, root: Path) -> dict[str, Any]:
    lease = get_active_lease(task_id, root=root)
    if lease is None:
        return {
            "active_lease_id": None,
            "lease_ready": True,
            "lease_reason": "no_active_lease",
            "lease_bonus": 0,
        }
    host_name = str(entry.host_name or "")
    holder_runtime = str(lease.holder_backend_runtime or "")
    if str(entry.host_role or NodeRole.PRIMARY.value) == NodeRole.BURST.value:
        if lease.holder_node_id != host_name:
            return {
                "active_lease_id": lease.task_lease_id,
                "lease_ready": False,
                "lease_reason": "burst_candidate_conflicts_with_active_lease_holder",
                "lease_bonus": -3,
            }
        if holder_runtime not in {"", BackendRuntime.UNASSIGNED.value, backend_runtime}:
            return {
                "active_lease_id": lease.task_lease_id,
                "lease_ready": False,
                "lease_reason": "burst_candidate_conflicts_with_active_lease_backend",
                "lease_bonus": -3,
            }
    bonus = 2 if lease.holder_node_id == host_name else 0
    return {
        "active_lease_id": lease.task_lease_id,
        "lease_ready": True,
        "lease_reason": "active_lease_aligned" if bonus else "active_lease_present",
        "lease_bonus": bonus,
    }


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


def list_routing_requests(root: Optional[Path] = None) -> list[RoutingRequestRecord]:
    rows = [RoutingRequestRecord.from_dict(row) for row in _load_rows(routing_requests_dir(root))]
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


def latest_failed_routing_request(root: Optional[Path] = None) -> Optional[RoutingRequestRecord]:
    for row in list_routing_requests(root=root):
        if row.status == "failed":
            return row
    return None


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
                    policy_tags=list(model.get("policy_tags") or ["qwen_only", "approved"]),
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


def legal_candidate_pool_for_runtime_policy_block(
    *,
    runtime_route_policy: dict[str, Any],
    allowed_families: list[str],
    root: Path,
) -> dict[str, Any]:
    entries = _candidate_entry_pool(allowed_families=allowed_families, root=root)
    available_nodes = _available_nodes_by_role(root)
    preferred_provider = str(runtime_route_policy.get("preferred_provider") or "")
    preferred_model = str(runtime_route_policy.get("preferred_model") or "")
    allowed_host_roles = list(runtime_route_policy.get("allowed_host_roles") or [])
    forbidden_host_roles = set(runtime_route_policy.get("forbidden_host_roles") or [])
    local_only = bool(runtime_route_policy.get("local_only", False))
    allowed_fallbacks = list(runtime_route_policy.get("allowed_fallbacks") or [])

    legal_entries: list[ModelRegistryEntryRecord] = []
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
        legal_entries.append(entry)

    fallback_entries = [row for row in legal_entries if row.model_name in allowed_fallbacks] if allowed_fallbacks else []
    preferred_model_entries = [row for row in legal_entries if row.model_name == preferred_model] if preferred_model else []
    preferred_provider_entries = [row for row in legal_entries if row.provider_id == preferred_provider] if preferred_provider else []
    return {
        "legal_entries": legal_entries,
        "legal_model_names": sorted({row.model_name for row in legal_entries}),
        "legal_provider_ids": sorted({row.provider_id for row in legal_entries}),
        "preferred_model_entries": preferred_model_entries,
        "preferred_provider_entries": preferred_provider_entries,
        "fallback_entries": fallback_entries,
    }


def _profile_coverage(profile: CapabilityProfileRecord, required_capabilities: list[str], task_type: str, risk_level: str) -> dict[str, Any]:
    matched_capabilities = len(set(required_capabilities).intersection(profile.capabilities))
    return {
        "matched_capabilities": matched_capabilities,
        "covers_task_type": task_type in profile.supported_task_types,
        "covers_risk": risk_level in profile.supported_risk_levels,
    }


def _choose_entry(
    *,
    task_id: str,
    normalized_request: str,
    required_capabilities: list[str],
    task_type: str,
    risk_level: str,
    priority: str,
    workload_type: str,
    allowed_families: list[str],
    preferred_family: str,
    runtime_route_policy: dict[str, Any],
    root: Path,
) -> tuple[ModelRegistryEntryRecord, CapabilityProfileRecord, list[str], dict[str, Any]]:
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
    authority_class = _infer_authority_class(task_type=task_type, risk_level=risk_level)
    if authority_class in {AuthorityClass.OBSERVE_ONLY.value, AuthorityClass.SUGGEST_ONLY.value}:
        minimum_tier = ModelTier.ROUTING.value
    elif authority_class == AuthorityClass.REVIEW_REQUIRED.value:
        minimum_tier = ModelTier.GENERAL.value
    else:
        minimum_tier = minimum_tier_by_authority_class(authority_class, root=root)
    latency_preference = _latency_preference(
        workload_type=workload_type,
        task_type=task_type,
        priority=priority,
        normalized_request=normalized_request,
    )
    context_estimate = _context_estimate(normalized_request)
    degradation_index = _active_degradation_index(root=root)

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

    candidate_rows: list[dict[str, Any]] = []
    for entry in filtered_entries:
        for profile_id in entry.capability_profile_ids:
            profile = profiles_by_id.get(profile_id)
            if profile is None:
                continue
            coverage = _profile_coverage(profile, required_capabilities, task_type, risk_level)
            inferred_tier = _infer_model_tier(entry, profile)
            legality_findings: list[str] = []
            if not _tier_meets_floor(inferred_tier, minimum_tier):
                legality_findings.append("below_minimum_tier_for_authority_class")
            if authority_class == AuthorityClass.APPROVAL_REQUIRED.value or task_type in {"deploy", "quant", "review"}:
                try:
                    assert_forbidden_downgrade(
                        task_class=task_type,
                        authority_class=authority_class,
                        candidate_tier=inferred_tier,
                        root=root,
                    )
                except ValueError as exc:
                    legality_findings.append("forbidden_downgrade")
                    legality_findings.append(str(exc))
            selected_backend = profile.preferred_execution_backend or entry.default_execution_backend
            node_signal = _node_runtime_signal(entry.host_name, root=root)
            backend_status = _backend_health_status(selected_backend, root=root)
            lease_signal = _lease_signal(
                task_id=task_id,
                entry=entry,
                backend_runtime=selected_backend,
                root=root,
            )
            degradation_reasons: list[str] = []
            if str(entry.host_role or NodeRole.PRIMARY.value) == NodeRole.BURST.value:
                if "burst_worker" in degradation_index["by_subsystem"] or "BURST_WORKER_OFFLINE" in degradation_index["by_mode"]:
                    degradation_reasons.append("burst_worker_degraded")
            if task_type == "research" and "research_backend" in degradation_index["by_subsystem"]:
                degradation_reasons.append("research_backend_degraded")
            if entry.provider_id == "nvidia" and "nvidia_lane" in degradation_index["by_subsystem"]:
                degradation_reasons.append("nvidia_lane_degraded")
            if node_signal["available_backends"] and selected_backend not in node_signal["available_backends"]:
                degradation_reasons.append("backend_not_available_on_node")
            preferred_family_bonus = 1 if entry.model_family == preferred_family else 0
            preferred_provider_bonus = 1 if preferred_provider and entry.provider_id == preferred_provider else 0
            preferred_model_bonus = 1 if preferred_model and entry.model_name == preferred_model else 0
            preferred_host_bonus = 1 if preferred_host_role and str(entry.host_role or "") == preferred_host_role else 0
            latency_fit = _candidate_latency_fit(tier=inferred_tier, latency_preference=latency_preference)
            context_fit = _candidate_context_fit(tier=inferred_tier, context_bucket=context_estimate["bucket"])
            current_task_count = (
                int(node_signal["current_task_count"])
                if isinstance(node_signal.get("current_task_count"), int)
                else 0
            )
            blocking_degradation_reasons = [
                reason for reason in degradation_reasons if reason != "research_backend_degraded"
            ]
            candidate_allowed = not legality_findings and lease_signal["lease_ready"] and not blocking_degradation_reasons
            candidate_rows.append(
                {
                    "entry": entry,
                    "profile": profile,
                    "coverage": coverage,
                    "tier": inferred_tier,
                    "authority_class": authority_class,
                    "minimum_tier": minimum_tier,
                    "backend_status": backend_status,
                    "node_signal": node_signal,
                    "lease_signal": lease_signal,
                    "degradation_reasons": degradation_reasons,
                    "legality_findings": legality_findings,
                    "candidate_allowed": candidate_allowed,
                    "rank": (
                        1 if candidate_allowed else 0,
                        _status_rank(backend_status) + _status_rank(node_signal["node_status"]),
                        lease_signal["lease_bonus"],
                        1 if coverage["covers_task_type"] else 0,
                        1 if coverage["covers_risk"] else 0,
                        preferred_model_bonus,
                        preferred_provider_bonus,
                        preferred_host_bonus,
                        latency_fit,
                        context_fit,
                        coverage["matched_capabilities"],
                        preferred_family_bonus,
                        -current_task_count,
                        entry.priority_rank,
                    ),
                }
            )
    if not candidate_rows:
        raise ValueError("No active routing candidates were available for the current routing policy.")
    if any(
        row["candidate_allowed"] and row["coverage"]["covers_task_type"] and row["coverage"]["covers_risk"]
        for row in candidate_rows
    ):
        candidate_rows = [
            row
            for row in candidate_rows
            if row["candidate_allowed"] and row["coverage"]["covers_task_type"] and row["coverage"]["covers_risk"]
        ]
    elif any(row["candidate_allowed"] for row in candidate_rows):
        candidate_rows = [row for row in candidate_rows if row["candidate_allowed"]]
    else:
        raise ValueError("No routing candidate survived policy, host-role, provider, backend, and capability legality filters.")
    candidate_rows.sort(key=lambda item: item["rank"], reverse=True)
    selected_row = candidate_rows[0]
    selected_entry, selected_profile = selected_row["entry"], selected_row["profile"]
    candidate_model_names = [item["entry"].model_name for item in candidate_rows]
    seen: list[str] = []
    for model_name in candidate_model_names:
        if model_name not in seen:
            seen.append(model_name)
    evaluation = {
        "authority_class": authority_class,
        "minimum_tier": minimum_tier,
        "context_estimate": context_estimate,
        "latency_preference": latency_preference,
        "active_degradation_modes": list(degradation_index["items"]),
        "active_lease_id": selected_row["lease_signal"]["active_lease_id"],
        "selected_candidate": {
            "model_name": selected_entry.model_name,
            "provider_id": selected_entry.provider_id,
            "execution_backend": selected_profile.preferred_execution_backend or selected_entry.default_execution_backend,
            "host_role": selected_entry.host_role,
            "host_name": selected_entry.host_name,
            "tier": selected_row["tier"],
            "backend_health_status": selected_row["backend_status"],
            "node_health_status": selected_row["node_signal"]["node_status"],
            "lease_reason": selected_row["lease_signal"]["lease_reason"],
            "rerouted_from_preferred_model": bool(preferred_model and selected_entry.model_name != preferred_model),
            "degradation_reasons": list(selected_row["degradation_reasons"]),
            "legality_findings": list(selected_row["legality_findings"]),
            "score": list(selected_row["rank"]),
        },
        "candidate_evaluations": [
            {
                "model_name": row["entry"].model_name,
                "provider_id": row["entry"].provider_id,
                "execution_backend": row["profile"].preferred_execution_backend or row["entry"].default_execution_backend,
                "host_role": row["entry"].host_role,
                "host_name": row["entry"].host_name,
                "tier": row["tier"],
                "allowed": row["candidate_allowed"],
                "backend_health_status": row["backend_status"],
                "node_health_status": row["node_signal"]["node_status"],
                "current_task_count": row["node_signal"]["current_task_count"],
                "lease_ready": row["lease_signal"]["lease_ready"],
                "lease_reason": row["lease_signal"]["lease_reason"],
                "degradation_reasons": list(row["degradation_reasons"]),
                "legality_findings": list(row["legality_findings"]),
                "covers_task_type": row["coverage"]["covers_task_type"],
                "covers_risk": row["coverage"]["covers_risk"],
                "matched_capabilities": row["coverage"]["matched_capabilities"],
                "score": list(row["rank"]),
            }
            for row in candidate_rows[:5]
        ],
    }
    return selected_entry, selected_profile, seen, evaluation


def _latest_runtime_route_resolution(decision: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not decision:
        return None
    constraints = dict(decision.get("policy_constraints") or {})
    selection_context = dict(constraints.get("selection_context") or {})
    selected_candidate = dict(selection_context.get("selected_candidate") or {})
    return {
        "updated_at": decision.get("updated_at"),
        "routing_decision_id": decision.get("routing_decision_id"),
        "selected_provider_id": decision.get("selected_provider_id"),
        "selected_model_name": decision.get("selected_model_name"),
        "selected_execution_backend": decision.get("selected_execution_backend"),
        "selected_node_role": decision.get("selected_node_role"),
        "selected_host_name": decision.get("selected_host_name"),
        "workload_type": constraints.get("workload_type"),
        "agent_id": constraints.get("agent_id"),
        "channel": constraints.get("channel"),
        "preferred_provider": constraints.get("preferred_provider"),
        "preferred_model": constraints.get("preferred_model"),
        "preferred_host_role": constraints.get("preferred_host_role"),
        "allowed_host_roles": list(constraints.get("allowed_host_roles") or []),
        "forbidden_host_roles": list(constraints.get("forbidden_host_roles") or []),
        "allowed_fallbacks": list(constraints.get("allowed_fallbacks") or []),
        "ignored_overrides": list(constraints.get("ignored_overrides") or []),
        "authority_class": constraints.get("authority_class"),
        "latency_preference": selection_context.get("latency_preference"),
        "context_estimate": selection_context.get("context_estimate"),
        "active_degradation_modes": list(selection_context.get("active_degradation_modes") or []),
        "active_lease_id": selection_context.get("active_lease_id"),
        "backend_health_status": selected_candidate.get("backend_health_status"),
        "node_health_status": selected_candidate.get("node_health_status"),
        "rerouted_from_preferred_model": bool(selected_candidate.get("rerouted_from_preferred_model", False)),
        "candidate_evaluations": list(selection_context.get("candidate_evaluations") or []),
        "route_legality_status": constraints.get("route_legality_status", "legal"),
        "route_resolution_state": constraints.get("route_resolution_state", "selected"),
        "fallback_attempted": bool(constraints.get("fallback_attempted", False)),
        "fallback_blocked_for_safety": bool(constraints.get("fallback_blocked_for_safety", False)),
        "blocked_route_reason": constraints.get("blocked_route_reason"),
        "selection_reason": decision.get("selection_reason", ""),
    }


def build_routing_failure_summary(request: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not request:
        return None
    constraints = dict(request.get("policy_constraints") or {})
    return {
        "routing_request_id": request.get("routing_request_id"),
        "task_id": request.get("task_id"),
        "updated_at": request.get("updated_at"),
        "lane": request.get("lane"),
        "channel": constraints.get("channel"),
        "workload_type": constraints.get("workload_type"),
        "task_type": request.get("task_type"),
        "risk_level": request.get("risk_level"),
        "preferred_provider": constraints.get("preferred_provider"),
        "preferred_model": constraints.get("preferred_model"),
        "preferred_host_role": constraints.get("preferred_host_role"),
        "allowed_host_roles": list(constraints.get("allowed_host_roles") or []),
        "forbidden_host_roles": list(constraints.get("forbidden_host_roles") or []),
        "allowed_fallbacks": list(constraints.get("allowed_fallbacks") or []),
        "eligible_provider_ids": list(constraints.get("eligible_provider_ids") or []),
        "authority_class": constraints.get("authority_class"),
        "latency_preference": constraints.get("latency_preference"),
        "context_estimate": constraints.get("context_estimate"),
        "active_degradation_modes": list(constraints.get("active_degradation_modes") or []),
        "active_lease_id": constraints.get("active_lease_id"),
        "required_capabilities": list(request.get("required_capabilities") or []),
        "failure_reason": constraints.get("failure_reason", ""),
        "failure_code": constraints.get("failure_code"),
        "route_legality_status": constraints.get("route_legality_status", "blocked"),
        "route_resolution_state": constraints.get("route_resolution_state", "blocked"),
        "fallback_blocked_for_safety": bool(constraints.get("fallback_blocked_for_safety", False)),
        "blocked_route_reason": constraints.get("blocked_route_reason") or constraints.get("failure_reason", ""),
        "status": request.get("status"),
    }


def score_candidate_route(candidate: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(candidate.get("score") or candidate.get("rank") or ())


def select_best_route(candidates: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not candidates:
        return None
    ranked = sorted(candidates, key=score_candidate_route, reverse=True)
    return ranked[0]


def collect_candidate_routes(
    *,
    task_id: str,
    normalized_request: str,
    required_capabilities: list[str],
    task_type: str,
    risk_level: str,
    priority: str,
    workload_type: str,
    allowed_families: list[str],
    preferred_family: str,
    runtime_route_policy: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    entry, profile, candidate_model_names, selection_context = _choose_entry(
        task_id=task_id,
        normalized_request=normalized_request,
        required_capabilities=required_capabilities,
        task_type=task_type,
        risk_level=risk_level,
        priority=priority,
        workload_type=workload_type,
        allowed_families=allowed_families,
        preferred_family=preferred_family,
        runtime_route_policy=runtime_route_policy,
        root=root,
    )
    candidates = list(selection_context.get("candidate_evaluations") or [])
    for row in candidates:
        row.setdefault("score", row.get("score") or [])
    return {
        "selected_entry": entry,
        "selected_profile": profile,
        "candidate_model_names": candidate_model_names,
        "selection_context": selection_context,
        "candidates": candidates,
        "best_candidate": select_best_route(candidates),
    }


def explain_routing_decision(decision: dict[str, Any]) -> Optional[dict[str, Any]]:
    return _latest_runtime_route_resolution(decision)


def persist_routing_decision(record: RoutingDecisionRecord, root: Optional[Path] = None) -> RoutingDecisionRecord:
    return save_routing_decision(record, root=root)


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
    authority_class = _infer_authority_class(task_type=task_type, risk_level=risk_level)
    context_estimate = _context_estimate(normalized_request)
    latency_preference = _latency_preference(
        workload_type=resolved_workload_type,
        task_type=task_type,
        priority=priority,
        normalized_request=normalized_request,
    )
    active_lease = get_active_lease(task_id, root=root_path)
    active_degradation_modes = list_active_degradation_modes(root=root_path)
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
        "authority_class": authority_class,
        "context_estimate": context_estimate,
        "latency_preference": latency_preference,
        "preferred_provider": runtime_route_policy.get("preferred_provider"),
        "preferred_model": runtime_route_policy.get("preferred_model"),
        "preferred_host_role": runtime_route_policy.get("preferred_host_role"),
        "allowed_host_roles": list(runtime_route_policy.get("allowed_host_roles") or []),
        "forbidden_host_roles": list(runtime_route_policy.get("forbidden_host_roles") or []),
        "burst_allowed": bool(runtime_route_policy.get("burst_allowed", False)),
        "local_only": bool(runtime_route_policy.get("local_only", False)),
        "allowed_fallbacks": list(runtime_route_policy.get("allowed_fallbacks") or []),
        "ignored_overrides": list((runtime_route_policy.get("policy_sources") or {}).get("ignored_overrides") or []),
        "active_degradation_modes": active_degradation_modes,
        "active_lease_id": active_lease.task_lease_id if active_lease else None,
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
            status="pending",
        ),
        root=root_path,
    )
    eligible_provider_ids = sorted({row.provider_id for row in _candidate_entry_pool(allowed_families=allowed_families, root=root_path)})
    try:
        route_selection = collect_candidate_routes(
            task_id=task_id,
            normalized_request=normalized_request,
            required_capabilities=required_capabilities,
            task_type=task_type,
            risk_level=risk_level,
            priority=priority,
            workload_type=resolved_workload_type,
            allowed_families=allowed_families,
            preferred_family=preferred_family,
            runtime_route_policy=runtime_route_policy,
            root=root_path,
        )
        entry = route_selection["selected_entry"]
        profile = route_selection["selected_profile"]
        candidate_model_names = route_selection["candidate_model_names"]
        selection_context = route_selection["selection_context"]
    except ValueError as exc:
        request.status = "failed"
        fallback_blocked_for_safety = bool(
            active_degradation_modes
            and (
                authority_class in {AuthorityClass.REVIEW_REQUIRED.value, AuthorityClass.APPROVAL_REQUIRED.value}
                or bool(runtime_route_policy.get("allowed_fallbacks"))
            )
        )
        request.policy_constraints = {
            **dict(request.policy_constraints or {}),
            "eligible_provider_ids": eligible_provider_ids,
            "failure_code": "no_legal_routing_candidate",
            "failure_reason": (
                "No routing candidate survived policy, host-role, provider, backend, and capability legality filters."
            ),
            "route_legality_status": "blocked",
            "route_resolution_state": "blocked",
            "fallback_blocked_for_safety": fallback_blocked_for_safety,
            "blocked_route_reason": str(exc),
        }
        save_routing_request(request, root=root_path)
        raise ValueError(
            f"{request.policy_constraints['failure_reason']} Original error: {exc}"
        ) from exc
    request.status = "completed"
    request.policy_constraints = {
        **dict(request.policy_constraints or {}),
        "eligible_provider_ids": eligible_provider_ids,
        "selection_context": selection_context,
        "route_legality_status": "legal",
        "route_resolution_state": (
            "rerouted"
            if bool((selection_context.get("selected_candidate") or {}).get("rerouted_from_preferred_model"))
            else "selected"
        ),
        "fallback_attempted": bool((selection_context.get("selected_candidate") or {}).get("rerouted_from_preferred_model")),
        "fallback_blocked_for_safety": False,
        "blocked_route_reason": "",
    }
    save_routing_request(request, root=root_path)
    decision = persist_routing_decision(
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
                f"using profile {profile.profile_name}; backend_health={selection_context['selected_candidate']['backend_health_status']} "
                f"node_health={selection_context['selected_candidate']['node_health_status']}."
            ),
            candidate_model_names=candidate_model_names,
            policy_constraints=dict(request.policy_constraints or {}),
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
                "policy_constraints": dict(request.policy_constraints or {}),
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


def route_task(**kwargs: Any) -> dict:
    return route_task_intent(**kwargs)


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
    requests = list_routing_requests(root_path)
    latest = decisions[0].to_dict() if decisions else None
    latest_failed_request = latest_failed_routing_request(root=root_path)
    runtime_policy = load_runtime_routing_policy(root=root_path)
    backend_assignment_summary = build_backend_assignment_summary(root=root_path)
    return {
        "provider_policy": "qwen_only" if allowed_families == ["qwen3.5"] else "policy_override",
        "architecture_mode": "provider_agnostic",
        "runtime_routing_policy_path": str(runtime_routing_policy_path(root=root_path)),
        "runtime_routing_policy_schema_version": runtime_policy.get("schema_version"),
        "routing_policy_id": policy.routing_policy_id,
        "default_family": preferred_family,
        "allowed_families": list(allowed_families),
        "lane_overrides": dict(policy.lane_overrides),
        "latest_override": latest_override.to_dict() if latest_override is not None else None,
        "active_override_count": len(active_overrides),
        "provider_ids": sorted({row.provider_id for row in entries}),
        "active_model_names": [row.model_name for row in sorted(entries, key=lambda row: row.priority_rank, reverse=True)],
        "active_model_count": len(entries),
        "failed_routing_request_count": sum(1 for row in requests if row.status == "failed"),
        "enabled_input_modalities": list(modality_summary.get("enabled_input_modalities", [])),
        "multimodal_runtime_enabled": False,
        "disabled_provider_ids": get_effective_control_state(root=root_path).get("disabled_provider_ids", []),
        "disabled_execution_backends": get_effective_control_state(root=root_path).get("disabled_execution_backends", []),
        "latest_routing_decision": latest,
        "latest_runtime_route_resolution": _latest_runtime_route_resolution(latest),
        "latest_failed_routing_request": build_routing_failure_summary(latest_failed_request.to_dict() if latest_failed_request else None),
        "backend_assignment_summary": backend_assignment_summary,
        "agent_roster_summary": build_agent_roster_summary(root=root_path),
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
