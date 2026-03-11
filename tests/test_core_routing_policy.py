from pathlib import Path

from runtime.core.models import (
    CapabilityProfileRecord,
    ModelRegistryEntryRecord,
    RoutingOverrideRecord,
    now_iso,
)
from runtime.core.routing import (
    build_model_registry_summary,
    route_task_intent,
    save_capability_profile,
    save_model_registry_entry,
    save_routing_override,
)
from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from scripts.operator_handoff_pack import build_operator_handoff_pack


def test_default_routing_policy_stays_qwen_only(tmp_path: Path):
    result = route_task_intent(
        task_id="task_route_default_policy",
        normalized_request="write a research note",
        task_type="research",
        risk_level="normal",
        priority="normal",
        actor="tester",
        lane="tests",
        root=tmp_path,
    )

    assert result["decision"]["selected_provider_id"] == "qwen"
    assert result["decision"]["selected_model_name"] == "Qwen3.5-35B"
    assert result["request"]["policy_constraints"]["default_family"] == "qwen3.5"
    assert result["request"]["policy_constraints"]["allowed_families"] == ["qwen3.5"]
    assert result["request"]["policy_constraints"]["latest_override_id"] is None


def test_global_routing_override_is_durable_and_provider_neutral(tmp_path: Path):
    created_at = now_iso()
    save_capability_profile(
        CapabilityProfileRecord(
            capability_profile_id="cap_kimi_general",
            created_at=created_at,
            updated_at=created_at,
            profile_name="kimi_general",
            provider_id="kimi",
            model_family="kimi2.5",
            capabilities=["general_reasoning", "reviewable_candidate", "research_synthesis"],
            supported_task_types=["general", "research"],
            supported_risk_levels=["normal", "risky"],
            preferred_execution_backend="worker_backend",
        ),
        root=tmp_path,
    )
    save_model_registry_entry(
        ModelRegistryEntryRecord(
            model_registry_entry_id="model_kimi_2_5_general",
            created_at=created_at,
            updated_at=created_at,
            provider_id="kimi",
            provider_kind="hosted",
            model_family="kimi2.5",
            model_name="kimi-2.5",
            display_name="kimi-2.5",
            capability_profile_ids=["cap_kimi_general"],
            policy_tags=["test_only"],
            priority_rank=5,
            default_execution_backend="worker_backend",
            active=True,
        ),
        root=tmp_path,
    )
    override = save_routing_override(
        RoutingOverrideRecord(
            routing_override_id="routing_override_global_kimi",
            created_at=created_at,
            updated_at=created_at,
            actor="tester",
            lane="tests",
            scope_type="global",
            scope_id="global",
            override_family="kimi2.5",
            allowed_families=["qwen3.5", "kimi2.5"],
            expires_at="2099-01-01T00:00:00+00:00",
            reason="provider switch drill",
            active=True,
        ),
        root=tmp_path,
    )

    result = route_task_intent(
        task_id="task_route_override_policy",
        normalized_request="write a research note",
        task_type="research",
        risk_level="normal",
        priority="normal",
        actor="tester",
        lane="tests",
        root=tmp_path,
    )

    assert result["decision"]["selected_provider_id"] == "kimi"
    assert result["decision"]["selected_model_name"] == "kimi-2.5"
    assert result["decision"]["selected_execution_backend"] == "worker_backend"
    assert result["request"]["policy_constraints"]["default_family"] == "kimi2.5"
    assert result["request"]["policy_constraints"]["latest_override_id"] == override.routing_override_id

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]
    summary = build_model_registry_summary(tmp_path)

    assert summary["architecture_mode"] == "provider_agnostic"
    assert summary["active_override_count"] == 1
    assert summary["latest_override"]["routing_override_id"] == override.routing_override_id
    assert status["routing_summary"]["latest_override"]["routing_override_id"] == override.routing_override_id
    assert snapshot["routing_summary"]["latest_override"]["routing_override_id"] == override.routing_override_id
    assert export_payload["counts"]["routing_policies"] >= 1
    assert export_payload["counts"]["routing_overrides"] == 1
    assert export_payload["routing_summary"]["latest_override"]["routing_override_id"] == override.routing_override_id
    assert handoff["model_registry_summary"]["latest_override"]["routing_override_id"] == override.routing_override_id
