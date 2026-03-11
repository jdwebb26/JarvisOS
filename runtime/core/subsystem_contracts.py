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

from runtime.core.models import SubsystemContractRecord, now_iso


DEFAULT_CONTRACTS = [
    {
        "subsystem_contract_id": "subsys_planner_v1",
        "subsystem_kind": "planner",
        "contract_name": "planner_task_contract",
        "version_tag": "v1",
        "input_contract": {"task_fields": ["task_id", "task_type", "priority", "risk_level"], "requires": ["routing_decision"]},
        "output_contract": {"emits": ["candidate_artifact", "task_event", "backend_metadata"], "forbids": ["direct_promotion"]},
        "state_refs": ["state/tasks", "state/routing_decisions", "state/candidate_records"],
    },
    {
        "subsystem_contract_id": "subsys_executor_v1",
        "subsystem_kind": "executor",
        "contract_name": "executor_candidate_contract",
        "version_tag": "v1",
        "input_contract": {"requires": ["task_id", "execution_backend", "candidate_policy"], "accepts": ["routing_decision"]},
        "output_contract": {"emits": ["artifact_candidate", "provider_adapter_result"], "forbids": ["direct_publish"]},
        "state_refs": ["state/artifacts", "state/candidate_records", "state/provider_adapter_results"],
    },
    {
        "subsystem_contract_id": "subsys_reviewer_v1",
        "subsystem_kind": "reviewer",
        "contract_name": "reviewer_verdict_contract",
        "version_tag": "v1",
        "input_contract": {"requires": ["review_id", "linked_artifact_ids"], "accepts": ["candidate_validation"]},
        "output_contract": {"emits": ["review_verdict", "rejection_decision", "followup_approval_request"], "forbids": ["silent_promotion"]},
        "state_refs": ["state/reviews", "state/candidate_validations", "state/rejection_decisions"],
    },
    {
        "subsystem_contract_id": "subsys_memory_v1",
        "subsystem_kind": "memory",
        "contract_name": "memory_candidate_contract",
        "version_tag": "v1",
        "input_contract": {"requires": ["consolidation_run_id", "source_refs"], "accepts": ["candidate_only"]},
        "output_contract": {"emits": ["memory_candidate", "memory_retrieval"], "forbids": ["direct_memory_truth_write"]},
        "state_refs": ["state/memory_candidates", "state/memory_retrievals"],
    },
    {
        "subsystem_contract_id": "subsys_routing_v1",
        "subsystem_kind": "routing",
        "contract_name": "provider_agnostic_routing_contract",
        "version_tag": "v1",
        "input_contract": {"requires": ["task_intent", "policy_constraints", "capability_profiles"]},
        "output_contract": {"emits": ["routing_request", "routing_decision"], "forbids": ["silent_model_switch"]},
        "state_refs": ["state/model_registry_entries", "state/capability_profiles", "state/routing_decisions"],
    },
    {
        "subsystem_contract_id": "subsys_provider_adapter_v1",
        "subsystem_kind": "provider_adapter",
        "contract_name": "provider_adapter_binding_contract",
        "version_tag": "v1",
        "input_contract": {"requires": ["routing_decision", "approved_registry_entry"], "active_policy": "qwen_only"},
        "output_contract": {"emits": ["provider_adapter_result", "candidate_artifact"], "forbids": ["provider_as_system_of_record"]},
        "state_refs": ["state/provider_adapter_results", "state/candidate_records", "state/candidate_validations"],
    },
]


def contracts_dir(root: Optional[Path] = None) -> Path:
    root_path = Path(root or ROOT).resolve()
    path = root_path / "state" / "subsystem_contracts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(contract_id: str, root: Optional[Path] = None) -> Path:
    return contracts_dir(root) / f"{contract_id}.json"


def save_subsystem_contract(record: SubsystemContractRecord, root: Optional[Path] = None) -> SubsystemContractRecord:
    record.updated_at = now_iso()
    _path(record.subsystem_contract_id, root).write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return record


def list_subsystem_contracts(root: Optional[Path] = None) -> list[SubsystemContractRecord]:
    rows: list[SubsystemContractRecord] = []
    for path in sorted(contracts_dir(root).glob("*.json")):
        try:
            rows.append(SubsystemContractRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def ensure_default_subsystem_contracts(root: Optional[Path] = None) -> list[SubsystemContractRecord]:
    root_path = Path(root or ROOT).resolve()
    for payload in DEFAULT_CONTRACTS:
        path = _path(payload["subsystem_contract_id"], root_path)
        if path.exists():
            continue
        save_subsystem_contract(
            SubsystemContractRecord(
                subsystem_contract_id=payload["subsystem_contract_id"],
                subsystem_kind=payload["subsystem_kind"],
                contract_name=payload["contract_name"],
                created_at=now_iso(),
                updated_at=now_iso(),
                version_tag=payload["version_tag"],
                input_contract=dict(payload["input_contract"]),
                output_contract=dict(payload["output_contract"]),
                state_refs=list(payload["state_refs"]),
            ),
            root=root_path,
        )
    return list_subsystem_contracts(root_path)


def build_subsystem_contract_summary(root: Optional[Path] = None) -> dict:
    contracts = list_subsystem_contracts(root)
    return {
        "contract_count": len(contracts),
        "active_contract_count": sum(1 for row in contracts if row.active),
        "subsystem_kinds": sorted({row.subsystem_kind for row in contracts}),
        "latest_contract": contracts[0].to_dict() if contracts else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show subsystem contract scaffolding.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    ensure_default_subsystem_contracts(Path(args.root).resolve())
    print(json.dumps(build_subsystem_contract_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
