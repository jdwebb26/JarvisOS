#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import (
    CapabilityProfileRecord,
    ModelRegistryEntryRecord,
    ProviderAdapterResultRecord,
    RoutingProvenanceRecord,
    RoutingDecisionRecord,
    RoutingRequestRecord,
    TaskPriority,
    TaskRiskLevel,
    new_id,
    now_iso,
)
from runtime.controls.control_store import assert_control_allows, get_effective_control_state
from runtime.core.provenance_store import save_routing_provenance
from runtime.core.modality_contracts import build_modality_summary, ensure_default_modality_contracts


ACTIVE_QWEN_MODELS = [
    {
        "model_registry_entry_id": "model_qwen3_5_9b",
        "model_name": "Qwen3.5-9B",
        "display_name": "Qwen3.5-9B",
        "priority_rank": 30,
        "default_execution_backend": "qwen_executor",
        "capability_profile_ids": ["cap_triage_qwen"],
    },
    {
        "model_registry_entry_id": "model_qwen3_5_35b",
        "model_name": "Qwen3.5-35B",
        "display_name": "Qwen3.5-35B",
        "priority_rank": 20,
        "default_execution_backend": "qwen_executor",
        "capability_profile_ids": ["cap_general_qwen"],
    },
    {
        "model_registry_entry_id": "model_qwen3_5_122b",
        "model_name": "Qwen3.5-122B",
        "display_name": "Qwen3.5-122B",
        "priority_rank": 10,
        "default_execution_backend": "qwen_planner",
        "capability_profile_ids": ["cap_highstakes_qwen"],
    },
]

CAPABILITY_PROFILES = [
    {
        "capability_profile_id": "cap_triage_qwen",
        "profile_name": "qwen_triage",
        "capabilities": ["triage", "classification", "shortform"],
        "supported_task_types": ["general", "docs"],
        "supported_risk_levels": [TaskRiskLevel.NORMAL.value],
        "preferred_execution_backend": "qwen_executor",
    },
    {
        "capability_profile_id": "cap_general_qwen",
        "profile_name": "qwen_general",
        "capabilities": ["general_reasoning", "code_generation", "research_synthesis", "reviewable_candidate"],
        "supported_task_types": ["general", "docs", "code", "research", "review", "approval", "flowstate", "output"],
        "supported_risk_levels": [TaskRiskLevel.NORMAL.value, TaskRiskLevel.RISKY.value],
        "preferred_execution_backend": "qwen_executor",
    },
    {
        "capability_profile_id": "cap_highstakes_qwen",
        "profile_name": "qwen_highstakes",
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
]


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    base = Path(root or ROOT).resolve()
    path = base / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_registry_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("model_registry_entries", root=root)


def capability_profiles_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("capability_profiles", root=root)


def routing_requests_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("routing_requests", root=root)


def routing_decisions_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("routing_decisions", root=root)


def provider_adapter_results_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("provider_adapter_results", root=root)


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


def latest_routing_decision(root: Optional[Path] = None) -> Optional[RoutingDecisionRecord]:
    rows = list_routing_decisions(root=root)
    return rows[0] if rows else None


def ensure_default_routing_contracts(root: Optional[Path] = None) -> dict[str, list[dict]]:
    root_path = Path(root or ROOT).resolve()
    for profile in CAPABILITY_PROFILES:
        path = _record_path(capability_profiles_dir(root_path), profile["capability_profile_id"])
        if not path.exists():
            save_capability_profile(
                CapabilityProfileRecord(
                    capability_profile_id=profile["capability_profile_id"],
                    created_at=now_iso(),
                    updated_at=now_iso(),
                    profile_name=profile["profile_name"],
                    provider_id="qwen",
                    model_family="qwen3.5",
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
                    provider_id="qwen",
                    provider_kind="local_openai_compatible",
                    model_family="qwen3.5",
                    model_name=model["model_name"],
                    display_name=model["display_name"],
                    capability_profile_ids=list(model["capability_profile_ids"]),
                    policy_tags=["qwen_only", "approved"],
                    priority_rank=model["priority_rank"],
                    default_execution_backend=model["default_execution_backend"],
                    active=True,
                ),
                root=root_path,
            )
    return {
        "model_registry_entries": [row.to_dict() for row in list_model_registry_entries(root_path)],
        "capability_profiles": [row.to_dict() for row in list_capability_profiles(root_path)],
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
    allowed_models: list[str],
    root: Path,
) -> tuple[ModelRegistryEntryRecord, CapabilityProfileRecord, list[str]]:
    effective_controls = get_effective_control_state(root=root)
    disabled_providers = set(effective_controls.get("disabled_provider_ids", []))
    disabled_backends = set(effective_controls.get("disabled_execution_backends", []))
    entries = [
        row
        for row in list_model_registry_entries(root)
        if row.active
        and row.model_name in allowed_models
        and row.provider_id not in disabled_providers
        and row.default_execution_backend not in disabled_backends
    ]
    profiles_by_id = {row.capability_profile_id: row for row in list_capability_profiles(root) if row.active}
    ranked: list[tuple[tuple[int, int, int, int], ModelRegistryEntryRecord, CapabilityProfileRecord]] = []
    for entry in entries:
        for profile_id in entry.capability_profile_ids:
            profile = profiles_by_id.get(profile_id)
            if profile is None:
                continue
            score = _profile_score(profile, required_capabilities, task_type, risk_level)
            ranked.append(((*score, -entry.priority_rank), entry, profile))
    if not ranked:
        raise ValueError("No active routing candidates were available for the current Qwen-only policy.")
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
    root: Optional[Path] = None,
) -> dict:
    root_path = Path(root or ROOT).resolve()
    ensure_default_routing_contracts(root_path)
    modality_summary = build_modality_summary(root_path)
    allowed_models = [row["model_name"] for row in ACTIVE_QWEN_MODELS]
    assert_control_allows(
        action="route_selection",
        root=root_path,
        task_id=task_id,
        actor=actor,
        lane=lane,
    )
    effective_controls = get_effective_control_state(root=root_path)
    policy_constraints = {
        "qwen_only": True,
        "allowed_models": allowed_models,
        "provider_lock": "qwen",
        "enabled_input_modalities": list(modality_summary.get("enabled_input_modalities", [])),
        "multimodal_runtime_enabled": False,
        "disabled_provider_ids": list(effective_controls.get("disabled_provider_ids", [])),
        "disabled_execution_backends": list(effective_controls.get("disabled_execution_backends", [])),
    }
    required_capabilities = infer_required_capabilities(
        task_type=task_type,
        risk_level=risk_level,
        priority=priority,
        normalized_request=normalized_request,
    )
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
        allowed_models=allowed_models,
        root=root_path,
    )
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
            selection_reason=(
                f"Matched capabilities {required_capabilities} under qwen_only policy using profile {profile.profile_name}."
            ),
            candidate_model_names=candidate_model_names,
            policy_constraints=policy_constraints,
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
            source_refs={
                "provider_adapter_result_id": adapter_result.provider_adapter_result_id,
                "model_registry_entry_id": entry.model_registry_entry_id,
                "capability_profile_id": profile.capability_profile_id,
            },
            replay_input={
                "task_type": task_type,
                "risk_level": risk_level,
                "priority": priority,
                "normalized_request": normalized_request,
                "required_capabilities": list(required_capabilities),
                "policy_constraints": dict(policy_constraints),
            },
        ),
        root=root_path,
    )
    return {
        "request": request.to_dict(),
        "decision": decision.to_dict(),
        "provider_adapter_result": adapter_result.to_dict(),
        "provenance": provenance.to_dict(),
        "active_registry": {
            "provider_policy": "qwen_only",
            "active_model_names": allowed_models,
            "active_model_count": len(allowed_models),
            "enabled_input_modalities": list(modality_summary.get("enabled_input_modalities", [])),
            "disabled_provider_ids": list(effective_controls.get("disabled_provider_ids", [])),
            "disabled_execution_backends": list(effective_controls.get("disabled_execution_backends", [])),
        },
    }


def build_model_registry_summary(root: Optional[Path] = None) -> dict:
    root_path = Path(root or ROOT).resolve()
    modality_summary = build_modality_summary(root_path)
    effective_controls = get_effective_control_state(root=root_path)
    disabled_providers = set(effective_controls.get("disabled_provider_ids", []))
    disabled_backends = set(effective_controls.get("disabled_execution_backends", []))
    entries = [
        row
        for row in list_model_registry_entries(root_path)
        if row.active and row.provider_id not in disabled_providers and row.default_execution_backend not in disabled_backends
    ]
    decisions = list_routing_decisions(root_path)
    latest = decisions[0].to_dict() if decisions else None
    return {
        "provider_policy": "qwen_only",
        "provider_ids": sorted({row.provider_id for row in entries}),
        "active_model_names": [row.model_name for row in sorted(entries, key=lambda row: row.priority_rank)],
        "active_model_count": len(entries),
        "enabled_input_modalities": list(modality_summary.get("enabled_input_modalities", [])),
        "multimodal_runtime_enabled": False,
        "disabled_provider_ids": get_effective_control_state(root=root_path).get("disabled_provider_ids", []),
        "disabled_execution_backends": get_effective_control_state(root=root_path).get("disabled_execution_backends", []),
        "latest_routing_decision": latest,
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
