from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from runtime.core.models import CapabilityProfileRecord, ModelRegistryEntryRecord, RoutingPolicyRecord, now_iso
from runtime.core.degradation_policy import record_degradation_event
from runtime.core.node_registry import update_node_status
from runtime.core.routing import (
    explain_routing_decision,
    list_routing_requests,
    route_task,
    route_task_intent,
    save_capability_profile,
    save_model_registry_entry,
    save_routing_policy,
)
from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.runtime_5_2_prep import write_backend_health_snapshot
from runtime.dashboard.state_export import build_state_export


def _write_runtime_policy(root: Path, payload: dict) -> None:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "runtime_routing_policy.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_jarvis_resolves_to_9b_on_primary_not_burst(tmp_path: Path) -> None:
    result = route_task(
        task_id="task_jarvis_primary",
        normalized_request="write a short reply",
        task_type="general",
        risk_level="normal",
        priority="normal",
        actor="tester",
        lane="jarvis",
        agent_id="jarvis",
        channel="discord_jarvis",
        root=tmp_path,
    )

    assert result["decision"]["selected_provider_id"] == "qwen"
    assert result["decision"]["selected_model_name"] == "Qwen3.5-9B"
    assert result["decision"]["selected_node_role"] == "primary"
    assert result["decision"]["selected_host_name"] == "NIMO"
    assert result["decision"]["policy_constraints"]["burst_allowed"] is False
    assert "burst" in result["decision"]["policy_constraints"]["forbidden_host_roles"]
    explained = explain_routing_decision(result["decision"])
    assert explained["route_legality_status"] == "legal"
    assert explained["route_resolution_state"] == "selected"


def test_scout_resolves_to_nimo_preferred_route(tmp_path: Path) -> None:
    result = route_task_intent(
        task_id="task_scout_primary",
        normalized_request="research this market structure idea",
        task_type="research",
        risk_level="normal",
        priority="normal",
        actor="tester",
        lane="scout",
        agent_id="scout",
        channel="discord_scout",
        root=tmp_path,
    )

    assert result["decision"]["selected_provider_id"] == "qwen"
    assert result["decision"]["selected_model_name"] == "Qwen3.5-35B"
    assert result["decision"]["selected_node_role"] == "primary"
    assert result["decision"]["selected_host_name"] == "NIMO"


def test_jarvis_does_not_prefer_9b_when_profile_cannot_cover_code_risk(tmp_path: Path) -> None:
    result = route_task_intent(
        task_id="task_jarvis_code_risky",
        normalized_request="fix this python bug and patch the tests",
        task_type="code",
        risk_level="risky",
        priority="normal",
        actor="tester",
        lane="jarvis",
        agent_id="jarvis",
        channel="discord_jarvis",
        root=tmp_path,
    )

    assert result["decision"]["selected_model_name"] == "Qwen3.5-35B"
    assert result["decision"]["selected_execution_backend"] == "qwen_executor"


def test_embeddings_workloads_stay_local(tmp_path: Path) -> None:
    result = route_task_intent(
        task_id="task_local_embeddings",
        normalized_request="embed recent operator notes",
        task_type="general",
        workload_type="embeddings",
        risk_level="normal",
        priority="normal",
        actor="tester",
        lane="jarvis",
        agent_id="jarvis",
        channel="local_embeddings",
        root=tmp_path,
    )

    assert result["decision"]["selected_provider_id"] == "local"
    assert result["decision"]["selected_model_name"] == "Local-Embeddings"
    assert result["decision"]["selected_execution_backend"] == "memory_spine"
    assert result["decision"]["selected_node_role"] == "local"
    assert result["decision"]["selected_host_name"] == "LOCAL"
    assert result["decision"]["policy_constraints"]["local_only"] is True


def test_fallback_does_not_cross_forbidden_host_role_boundaries(tmp_path: Path) -> None:
    created_at = now_iso()
    save_routing_policy(
        RoutingPolicyRecord(
            routing_policy_id="routing_policy_local_test",
            created_at=created_at,
            updated_at=created_at,
            actor="tester",
            lane="tests",
            default_family="qwen3.5",
            allowed_families=["qwen3.5"],
            lane_overrides={},
        ),
        root=tmp_path,
    )
    save_capability_profile(
        CapabilityProfileRecord(
            capability_profile_id="cap_burst_qwen",
            created_at=created_at,
            updated_at=created_at,
            profile_name="burst_qwen",
            provider_id="qwen",
            model_family="qwen3.5",
            capabilities=["general_reasoning", "reviewable_candidate"],
            supported_task_types=["general"],
            supported_risk_levels=["normal"],
            preferred_execution_backend="qwen_executor",
        ),
        root=tmp_path,
    )
    save_model_registry_entry(
        ModelRegistryEntryRecord(
            model_registry_entry_id="model_burst_qwen",
            created_at=created_at,
            updated_at=created_at,
            provider_id="qwen",
            provider_kind="local_openai_compatible",
            model_family="qwen3.5",
            model_name="Burst-Qwen-35B",
            display_name="Burst-Qwen-35B",
            capability_profile_ids=["cap_burst_qwen"],
            policy_tags=["test_only"],
            priority_rank=1,
            default_execution_backend="qwen_executor",
            host_role="burst",
            host_name="Koolkidclub",
            active=True,
        ),
        root=tmp_path,
    )

    policy = {
        "defaults": {
            "preferred_provider": "qwen",
            "preferred_host_role": "primary",
            "allowed_host_roles": ["primary"],
            "forbidden_host_roles": ["burst"],
            "burst_allowed": False,
            "allowed_fallbacks": ["Burst-Qwen-35B"],
        },
        "workload_policies": {
            "general": {
                "preferred_model": "Missing-Primary-Qwen",
                "allowed_fallbacks": ["Burst-Qwen-35B"],
            }
        },
    }
    _write_runtime_policy(tmp_path, policy)

    try:
        route_task_intent(
            task_id="task_no_burst_fallback",
            normalized_request="write a short reply",
            task_type="general",
            risk_level="normal",
            priority="normal",
            actor="tester",
            lane="tests",
            channel="tests",
            root=tmp_path,
        )
    except ValueError as exc:
        assert "No routing candidate survived policy" in str(exc)
    else:  # pragma: no cover - script mode failure path
        raise AssertionError("Expected routing to refuse burst-only fallback across forbidden host-role boundaries.")

    requests = list_routing_requests(root=tmp_path)
    assert len(requests) == 1
    failed_request = requests[0]
    assert failed_request.status == "failed"
    assert failed_request.policy_constraints["failure_code"] == "no_legal_routing_candidate"
    assert failed_request.policy_constraints["failure_reason"] == (
        "No routing candidate survived policy, host-role, provider, backend, and capability legality filters."
    )
    assert failed_request.policy_constraints["workload_type"] == "general"
    assert failed_request.policy_constraints["preferred_provider"] == "qwen"
    assert failed_request.policy_constraints["preferred_host_role"] == "primary"
    assert failed_request.policy_constraints["allowed_host_roles"] == ["primary"]
    assert "burst" in failed_request.policy_constraints["forbidden_host_roles"]
    assert failed_request.policy_constraints["allowed_fallbacks"] == ["Burst-Qwen-35B"]
    assert failed_request.policy_constraints["eligible_provider_ids"] == ["qwen"]

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)

    expected = status["routing_summary"]["latest_failed_routing_request"]
    assert status["routing_summary"]["failed_routing_request_count"] == 1
    assert expected["lane"] == "tests"
    assert expected["channel"] == "tests"
    assert expected["workload_type"] == "general"
    assert expected["task_type"] == "general"
    assert expected["risk_level"] == "normal"
    assert expected["preferred_provider"] == "qwen"
    assert expected["preferred_model"] == "Missing-Primary-Qwen"
    assert expected["preferred_host_role"] == "primary"
    assert expected["allowed_host_roles"] == ["primary"]
    assert "burst" in expected["forbidden_host_roles"]
    assert expected["allowed_fallbacks"] == ["Burst-Qwen-35B"]
    assert expected["eligible_provider_ids"] == ["qwen"]
    assert expected["failure_code"] == "no_legal_routing_candidate"
    assert "No routing candidate survived policy" in expected["failure_reason"]
    assert snapshot["routing_summary"]["latest_failed_routing_request"]["failure_code"] == "no_legal_routing_candidate"
    assert export_payload["routing_summary"]["latest_failed_routing_request"]["preferred_host_role"] == "primary"


def test_channel_override_beats_defaults_when_allowed(tmp_path: Path) -> None:
    _write_runtime_policy(
        tmp_path,
        {
            "defaults": {"preferred_model": "Qwen3.5-35B"},
            "channel_overrides": {
                "discord_low_latency": {
                    "preferred_model": "Qwen3.5-9B",
                    "preferred_host_role": "primary",
                    "allowed_host_roles": ["primary"],
                }
            },
        },
    )

    result = route_task_intent(
        task_id="task_channel_override",
        normalized_request="write a short reply",
        task_type="general",
        risk_level="normal",
        priority="normal",
        actor="tester",
        lane="tests",
        channel="discord_low_latency",
        root=tmp_path,
    )

    assert result["decision"]["selected_model_name"] == "Qwen3.5-9B"
    assert result["decision"]["selected_node_role"] == "primary"


def test_forbidden_channel_override_is_ignored_with_explicit_reason(tmp_path: Path) -> None:
    _write_runtime_policy(
        tmp_path,
        {
            "channel_overrides": {
                "discord_burst_attempt": {
                    "preferred_host_role": "burst",
                    "allowed_host_roles": ["burst"],
                    "burst_allowed": True,
                }
            }
        },
    )

    result = route_task_intent(
        task_id="task_channel_override_forbidden",
        normalized_request="write a short reply",
        task_type="general",
        risk_level="normal",
        priority="normal",
        actor="tester",
        lane="jarvis",
        agent_id="jarvis",
        channel="discord_burst_attempt",
        root=tmp_path,
    )

    assert result["decision"]["selected_model_name"] == "Qwen3.5-9B"
    assert result["decision"]["selected_node_role"] == "primary"
    ignored = result["decision"]["policy_constraints"]["ignored_overrides"]
    assert ignored
    assert ignored[0]["reason"] == "channel_override_conflicts_with_agent_host_policy"

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)

    expected = status["routing_summary"]["latest_runtime_route_resolution"]
    assert expected["selected_provider_id"] == "qwen"
    assert expected["selected_model_name"] == "Qwen3.5-9B"
    assert expected["selected_node_role"] == "primary"
    assert expected["agent_id"] == "jarvis"
    assert expected["channel"] == "discord_burst_attempt"
    assert expected["ignored_overrides"][0]["reason"] == "channel_override_conflicts_with_agent_host_policy"
    assert snapshot["routing_summary"]["latest_runtime_route_resolution"]["ignored_overrides"][0]["reason"] == expected["ignored_overrides"][0]["reason"]
    assert export_payload["routing_summary"]["latest_runtime_route_resolution"]["selected_host_name"] == "NIMO"


def test_invalid_runtime_policy_shape_fails_explicitly(tmp_path: Path) -> None:
    _write_runtime_policy(
        tmp_path,
        {
            "defaults": {
                "preferred_host_role": "primary",
                "allowed_host_roles": ["primary", "not_a_real_role"],
            }
        },
    )

    try:
        route_task_intent(
            task_id="task_invalid_policy_shape",
            normalized_request="write a short reply",
            task_type="general",
            risk_level="normal",
            priority="normal",
            actor="tester",
            lane="jarvis",
            agent_id="jarvis",
            channel="discord_jarvis",
            root=tmp_path,
        )
    except ValueError as exc:
        assert "unknown host roles" in str(exc)
    else:  # pragma: no cover - script mode failure path
        raise AssertionError("Expected invalid runtime routing policy shape to fail explicitly.")


def test_degraded_backend_reroutes_to_healthy_legal_candidate(tmp_path: Path) -> None:
    created_at = now_iso()
    save_capability_profile(
        CapabilityProfileRecord(
            capability_profile_id="cap_qwen_general_planner",
            created_at=created_at,
            updated_at=created_at,
            profile_name="qwen_general_planner",
            provider_id="qwen",
            model_family="qwen3.5",
            capabilities=["general_reasoning", "reviewable_candidate"],
            supported_task_types=["general", "docs"],
            supported_risk_levels=["normal"],
            preferred_execution_backend="qwen_planner",
        ),
        root=tmp_path,
    )
    save_model_registry_entry(
        ModelRegistryEntryRecord(
            model_registry_entry_id="model_qwen3_5_35b_planner",
            created_at=created_at,
            updated_at=created_at,
            provider_id="qwen",
            provider_kind="local_openai_compatible",
            model_family="qwen3.5",
            model_name="Qwen3.5-35B-Planner",
            display_name="Qwen3.5-35B-Planner",
            capability_profile_ids=["cap_qwen_general_planner"],
            policy_tags=["test_only"],
            priority_rank=25,
            default_execution_backend="qwen_planner",
            host_role="primary",
            host_name="NIMO",
            active=True,
        ),
        root=tmp_path,
    )
    write_backend_health_snapshot(
        {
            "snapshot_id": "backend_health_test",
            "generated_at": "2099-01-01T00:00:00+00:00",
            "nodes": [{"node_id": "NIMO", "label": "NIMO", "status": "healthy", "active": True}],
            "lanes": [
                {"lane": "general", "backend": "qwen_executor", "status": "unhealthy", "node_id": "NIMO"},
                {"lane": "general_alt", "backend": "qwen_planner", "status": "healthy", "node_id": "NIMO"},
            ],
        },
        root=tmp_path,
        filename="backend_health_test.json",
    )

    result = route_task_intent(
        task_id="task_degraded_backend_reroute",
        normalized_request="write a short reply",
        task_type="general",
        risk_level="normal",
        priority="normal",
        actor="tester",
        lane="tests",
        root=tmp_path,
    )

    assert result["decision"]["selected_model_name"] == "Qwen3.5-35B-Planner"
    resolution = build_status(tmp_path)["routing_summary"]["latest_runtime_route_resolution"]
    assert resolution["backend_health_status"] == "healthy"
    assert resolution["rerouted_from_preferred_model"] is True
    assert resolution["candidate_evaluations"]


def test_burst_worker_unavailable_refuses_when_burst_only_policy_is_requested(tmp_path: Path) -> None:
    created_at = now_iso()
    save_capability_profile(
        CapabilityProfileRecord(
            capability_profile_id="cap_burst_general",
            created_at=created_at,
            updated_at=created_at,
            profile_name="burst_general",
            provider_id="qwen",
            model_family="qwen3.5",
            capabilities=["general_reasoning", "reviewable_candidate"],
            supported_task_types=["general"],
            supported_risk_levels=["normal"],
            preferred_execution_backend="qwen_executor",
        ),
        root=tmp_path,
    )
    save_model_registry_entry(
        ModelRegistryEntryRecord(
            model_registry_entry_id="model_burst_only",
            created_at=created_at,
            updated_at=created_at,
            provider_id="qwen",
            provider_kind="local_openai_compatible",
            model_family="qwen3.5",
            model_name="Burst-Qwen-Only",
            display_name="Burst-Qwen-Only",
            capability_profile_ids=["cap_burst_general"],
            policy_tags=["test_only"],
            priority_rank=50,
            default_execution_backend="qwen_executor",
            host_role="burst",
            host_name="Koolkidclub",
            active=True,
        ),
        root=tmp_path,
    )
    update_node_status("Koolkidclub", status="healthy", root=tmp_path)
    record_degradation_event(
        subsystem="burst_worker",
        actor="tester",
        lane="tests",
        failure_category="offline",
        reason="burst worker unavailable",
        status="applied",
        root=tmp_path,
    )
    _write_runtime_policy(
        tmp_path,
        {
            "defaults": {
                "preferred_provider": "qwen",
                "preferred_host_role": "burst",
                "allowed_host_roles": ["burst"],
                "forbidden_host_roles": [],
                "burst_allowed": True,
            },
            "workload_policies": {
                "general": {
                    "preferred_model": "Burst-Qwen-Only",
                }
            },
        },
    )

    try:
        route_task_intent(
            task_id="task_burst_unavailable",
            normalized_request="write a short reply",
            task_type="general",
            risk_level="normal",
            priority="normal",
            actor="tester",
            lane="tests",
            root=tmp_path,
        )
    except ValueError as exc:
        assert "No routing candidate survived policy" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected burst-only routing to refuse when the burst worker is degraded.")

    failed = build_status(tmp_path)["routing_summary"]["latest_failed_routing_request"]
    assert failed["failure_code"] == "no_legal_routing_candidate"
    assert failed["active_degradation_modes"]
    truth = build_status(tmp_path)["routing_control_plane_summary"]
    assert truth["latest_route_state"] == "blocked"
    assert truth["latest_route_legality"] == "blocked"


def test_forbidden_downgrade_is_rejected_when_only_9b_remains(tmp_path: Path) -> None:
    route_task_intent(
        task_id="task_seed_defaults",
        normalized_request="seed defaults",
        task_type="general",
        risk_level="normal",
        priority="normal",
        actor="tester",
        lane="tests",
        root=tmp_path,
    )
    created_at = now_iso()
    save_model_registry_entry(
        ModelRegistryEntryRecord(
            model_registry_entry_id="model_qwen3_5_35b",
            created_at=created_at,
            updated_at=created_at,
            provider_id="qwen",
            provider_kind="local_openai_compatible",
            model_family="qwen3.5",
            model_name="Qwen3.5-35B",
            display_name="Qwen3.5-35B",
            capability_profile_ids=["cap_general_qwen"],
            policy_tags=["qwen_only", "approved"],
            priority_rank=20,
            default_execution_backend="qwen_executor",
            host_role="primary",
            host_name="NIMO",
            active=False,
        ),
        root=tmp_path,
    )
    save_model_registry_entry(
        ModelRegistryEntryRecord(
            model_registry_entry_id="model_qwen3_5_122b",
            created_at=created_at,
            updated_at=created_at,
            provider_id="qwen",
            provider_kind="local_openai_compatible",
            model_family="qwen3.5",
            model_name="Qwen3.5-122B",
            display_name="Qwen3.5-122B",
            capability_profile_ids=["cap_highstakes_qwen"],
            policy_tags=["qwen_only", "approved"],
            priority_rank=10,
            default_execution_backend="qwen_planner",
            host_role="primary",
            host_name="NIMO",
            active=False,
        ),
        root=tmp_path,
    )

    try:
        route_task_intent(
            task_id="task_forbidden_downgrade",
            normalized_request="deploy the live service",
            task_type="deploy",
            risk_level="high_stakes",
            priority="high",
            actor="tester",
            lane="jarvis",
            agent_id="jarvis",
            channel="discord_jarvis",
            root=tmp_path,
        )
    except ValueError as exc:
        assert "No routing candidate survived policy" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected deploy/high-stakes routing to refuse when only the 9B candidate remains.")

    failed = build_status(tmp_path)["routing_summary"]["latest_failed_routing_request"]
    assert failed["authority_class"] == "approval_required"
    assert failed["failure_code"] == "no_legal_routing_candidate"


def test_durable_routing_explanation_record_contains_live_selection_context(tmp_path: Path) -> None:
    result = route_task_intent(
        task_id="task_routing_explanation",
        normalized_request="write a short reply",
        task_type="general",
        risk_level="normal",
        priority="normal",
        actor="tester",
        lane="jarvis",
        agent_id="jarvis",
        channel="discord_jarvis",
        root=tmp_path,
    )

    constraints = result["decision"]["policy_constraints"]
    selection_context = constraints["selection_context"]
    assert constraints["authority_class"] == "suggest_only"
    assert selection_context["latency_preference"] == "low_latency"
    assert selection_context["selected_candidate"]["model_name"] == "Qwen3.5-9B"
    assert "backend_health_status" in selection_context["selected_candidate"]
    assert selection_context["candidate_evaluations"]

    resolution = build_state_export(tmp_path)["routing_summary"]["latest_runtime_route_resolution"]
    assert resolution["selected_model_name"] == "Qwen3.5-9B"
    assert resolution["latency_preference"] == "low_latency"
    assert resolution["candidate_evaluations"]
    assert resolution["route_legality_status"] == "legal"


def test_primary_runtime_unavailable_is_visible_as_primary_outage_and_blocks_general_route(tmp_path: Path) -> None:
    update_node_status("NIMO", status="stopped", root=tmp_path)
    record_degradation_event(
        subsystem="primary_runtime",
        actor="tester",
        lane="tests",
        failure_category="unavailable",
        reason="primary runtime unavailable",
        status="applied",
        root=tmp_path,
    )

    try:
        route_task_intent(
            task_id="task_primary_runtime_unavailable",
            normalized_request="write a short reply",
            task_type="general",
            risk_level="normal",
            priority="normal",
            actor="tester",
            lane="tests",
            root=tmp_path,
        )
    except ValueError as exc:
        assert "No routing candidate survived policy" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected general routing to refuse when the primary runtime is unavailable.")

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    truth = status["routing_control_plane_summary"]
    assert truth["latest_route_state"] == "blocked"
    assert truth["primary_runtime_posture"] == "primary_outage"
    assert truth["latest_degradation_event"]["degradation_mode"] == "PRIMARY_RUNTIME_UNAVAILABLE"
    assert truth["latest_failed_route"]["failure_code"] == "no_legal_routing_candidate"
    assert snapshot["routing_control_plane_summary"]["primary_runtime_posture"] == "primary_outage"
    assert export_payload["routing_control_plane_summary"]["latest_route_legality"] == "blocked"


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="runtime_route_resolution_")).resolve()
    try:
        test_jarvis_resolves_to_9b_on_primary_not_burst(temp_root / "jarvis")
        test_scout_resolves_to_nimo_preferred_route(temp_root / "scout")
        test_jarvis_does_not_prefer_9b_when_profile_cannot_cover_code_risk(temp_root / "jarvis_code")
        test_embeddings_workloads_stay_local(temp_root / "embeddings")
        test_fallback_does_not_cross_forbidden_host_role_boundaries(temp_root / "fallback")
        test_channel_override_beats_defaults_when_allowed(temp_root / "channel_ok")
        test_forbidden_channel_override_is_ignored_with_explicit_reason(temp_root / "channel_forbidden")
        test_invalid_runtime_policy_shape_fails_explicitly(temp_root / "invalid_shape")
        test_degraded_backend_reroutes_to_healthy_legal_candidate(temp_root / "degraded_backend")
        test_burst_worker_unavailable_refuses_when_burst_only_policy_is_requested(temp_root / "burst_unavailable")
        test_forbidden_downgrade_is_rejected_when_only_9b_remains(temp_root / "downgrade_rejected")
        test_durable_routing_explanation_record_contains_live_selection_context(temp_root / "explanation")
        test_primary_runtime_unavailable_is_visible_as_primary_outage_and_blocks_general_route(temp_root / "primary_unavailable")
    except AssertionError as exc:
        print(f"runtime route resolution test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
