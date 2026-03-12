from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from runtime.core.models import CapabilityProfileRecord, ModelRegistryEntryRecord, RoutingPolicyRecord, now_iso
from runtime.core.routing import route_task_intent, save_capability_profile, save_model_registry_entry, save_routing_policy


def _write_runtime_policy(root: Path, payload: dict) -> None:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "runtime_routing_policy.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_jarvis_resolves_to_9b_on_primary_not_burst(tmp_path: Path) -> None:
    result = route_task_intent(
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
        assert "allowed provider/host-role policy" in str(exc)
    else:  # pragma: no cover - script mode failure path
        raise AssertionError("Expected routing to refuse burst-only fallback across forbidden host-role boundaries.")


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


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="runtime_route_resolution_")).resolve()
    try:
        test_jarvis_resolves_to_9b_on_primary_not_burst(temp_root / "jarvis")
        test_scout_resolves_to_nimo_preferred_route(temp_root / "scout")
        test_embeddings_workloads_stay_local(temp_root / "embeddings")
        test_fallback_does_not_cross_forbidden_host_role_boundaries(temp_root / "fallback")
        test_channel_override_beats_defaults_when_allowed(temp_root / "channel_ok")
        test_forbidden_channel_override_is_ignored_with_explicit_reason(temp_root / "channel_forbidden")
    except AssertionError as exc:
        print(f"runtime route resolution test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
