from pathlib import Path

from runtime.core.backend_assignments import list_backend_assignments
from runtime.core.intake import TaskCreationRefusalError, create_task_from_message
from runtime.core.task_store import load_task
from runtime.core.models import CapabilityProfileRecord, ModelRegistryEntryRecord, RoutingPolicyRecord, now_iso
from runtime.core.routing import (
    latest_failed_routing_request,
    route_task_intent,
    save_capability_profile,
    save_model_registry_entry,
    save_routing_policy,
)
from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from scripts.operator_handoff_pack import build_operator_handoff_pack


def test_route_task_intent_persists_backend_assignment(tmp_path: Path):
    route = route_task_intent(
        task_id="task_backend_assignment_route",
        normalized_request="write a general note",
        task_type="general",
        risk_level="normal",
        priority="normal",
        actor="tester",
        lane="tests",
        root=tmp_path,
    )

    assignments = list_backend_assignments(root=tmp_path)
    assert len(assignments) == 1
    assignment = assignments[0]
    assert route["backend_assignment"]["backend_assignment_id"] == assignment.backend_assignment_id
    assert assignment.task_id == "task_backend_assignment_route"
    assert assignment.routing_request_id == route["request"]["routing_request_id"]
    assert assignment.routing_decision_id == route["decision"]["routing_decision_id"]
    assert assignment.provider_adapter_result_id == route["provider_adapter_result"]["provider_adapter_result_id"]
    assert assignment.provider_id == "qwen"
    assert assignment.model_name == route["decision"]["selected_model_name"]
    assert assignment.execution_backend == route["decision"]["selected_execution_backend"]


def test_backend_assignment_surfaces_in_task_and_reporting(tmp_path: Path):
    created = create_task_from_message(
        text="task: write a general note",
        user="tester",
        lane="tests",
        channel="tests",
        message_id="msg_backend_assignment",
        root=tmp_path,
    )

    assignment = created["routing_contract"]["backend_assignment"]
    assert assignment["backend_assignment_id"]

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]

    assert status["queued_now"][0]["backend_assignment_id"] == assignment["backend_assignment_id"]
    assert status["backend_assignment_summary"]["backend_assignment_count"] == 1
    assert status["backend_assignment_summary"]["latest_backend_assignment"]["backend_assignment_id"] == assignment["backend_assignment_id"]
    assert snapshot["backend_assignment_summary"]["latest_backend_assignment"]["backend_assignment_id"] == assignment["backend_assignment_id"]
    assert export_payload["counts"]["backend_assignments"] == 1
    assert export_payload["backend_assignment_summary"]["latest_backend_assignment"]["backend_assignment_id"] == assignment["backend_assignment_id"]
    assert handoff["backend_assignment_summary"]["latest_backend_assignment"]["backend_assignment_id"] == assignment["backend_assignment_id"]


def test_create_task_from_message_preserves_runtime_route_metadata_for_primary_and_local_paths(tmp_path: Path):
    jarvis = create_task_from_message(
        text="task: write a short reply",
        user="tester",
        lane="jarvis",
        channel="discord_jarvis",
        message_id="msg_jarvis_route",
        root=tmp_path / "jarvis",
    )
    scout = create_task_from_message(
        text="task: research this market structure idea",
        user="tester",
        lane="scout",
        channel="discord_scout",
        message_id="msg_scout_route",
        root=tmp_path / "scout",
    )
    embeddings = create_task_from_message(
        text="task: embed recent operator notes",
        user="tester",
        lane="jarvis",
        channel="local_embeddings",
        message_id="msg_embeddings_route",
        root=tmp_path / "embeddings",
    )
    scout_explicit_general = create_task_from_message(
        text="task: write a short reply",
        user="tester",
        lane="scout",
        channel="discord_scout",
        message_id="msg_scout_explicit_general",
        workload_type="general",
        root=tmp_path / "scout_explicit_general",
    )

    jarvis_task = load_task(jarvis["task_id"], root=tmp_path / "jarvis")
    scout_task = load_task(scout["task_id"], root=tmp_path / "scout")
    embeddings_task = load_task(embeddings["task_id"], root=tmp_path / "embeddings")
    scout_explicit_general_task = load_task(scout_explicit_general["task_id"], root=tmp_path / "scout_explicit_general")

    assert jarvis_task is not None
    assert scout_task is not None
    assert embeddings_task is not None
    assert scout_explicit_general_task is not None

    jarvis_routing = (jarvis_task.backend_metadata or {}).get("routing") or {}
    scout_routing = (scout_task.backend_metadata or {}).get("routing") or {}
    embeddings_routing = (embeddings_task.backend_metadata or {}).get("routing") or {}
    scout_explicit_general_routing = (scout_explicit_general_task.backend_metadata or {}).get("routing") or {}

    assert jarvis_task.assigned_model == "Qwen3.5-9B"
    assert jarvis_task.execution_backend == "qwen_executor"
    assert jarvis_routing["provider_id"] == "qwen"
    assert jarvis_routing["selected_node_role"] == "primary"
    assert jarvis_routing["selected_host_name"] == "NIMO"
    assert jarvis_routing["workload_type"] == "general"
    assert jarvis_routing["routing_decision_id"]

    assert scout_task.assigned_model == "Qwen3.5-35B"
    assert scout_task.execution_backend == "qwen_executor"
    assert scout_routing["provider_id"] == "qwen"
    assert scout_routing["selected_node_role"] == "primary"
    assert scout_routing["selected_host_name"] == "NIMO"
    assert scout_routing["workload_type"] == "research"
    assert scout_routing["routing_decision_id"]

    assert embeddings_task.assigned_model == "Local-Embeddings"
    assert embeddings_task.execution_backend == "memory_spine"
    assert embeddings_routing["provider_id"] == "local"
    assert embeddings_routing["selected_node_role"] == "local"
    assert embeddings_routing["selected_host_name"] == "LOCAL"
    assert embeddings_routing["workload_type"] == "embeddings"
    assert embeddings_routing["routing_decision_id"]

    assert scout_explicit_general_task.assigned_model == "Qwen3.5-35B"
    assert scout_explicit_general_task.execution_backend == "qwen_executor"
    assert scout_explicit_general_routing["provider_id"] == "qwen"
    assert scout_explicit_general_routing["selected_node_role"] == "primary"
    assert scout_explicit_general_routing["selected_host_name"] == "NIMO"
    assert scout_explicit_general_routing["workload_type"] == "general"
    assert scout_explicit_general_routing["routing_decision_id"]


def test_create_task_from_message_raises_structured_refusal_on_routing_failure(tmp_path: Path):
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

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "runtime_routing_policy.json").write_text(
        """{
  "defaults": {
    "preferred_provider": "qwen",
    "preferred_host_role": "primary",
    "allowed_host_roles": ["primary"],
    "forbidden_host_roles": ["burst"],
    "burst_allowed": false,
    "allowed_fallbacks": ["Burst-Qwen-35B"]
  },
  "workload_policies": {
    "general": {
      "preferred_model": "Missing-Primary-Qwen",
      "allowed_fallbacks": ["Burst-Qwen-35B"]
    }
  }
}
""",
        encoding="utf-8",
    )

    try:
        create_task_from_message(
            text="task: write a short reply",
            user="tester",
            lane="tests",
            channel="tests",
            message_id="msg_no_legal_route",
            root=tmp_path,
        )
    except TaskCreationRefusalError as exc:
        refusal = exc.refusal
    else:  # pragma: no cover - script mode failure path
        raise AssertionError("Expected structured intake refusal when routing has no legal candidate.")

    assert refusal["lane"] == "tests"
    assert refusal["channel"] == "tests"
    assert refusal["workload_type"] == "general"
    assert refusal["task_type"] == "general"
    assert refusal["risk_level"] == "normal"
    assert refusal["preferred_provider"] == "qwen"
    assert refusal["preferred_model"] == "Missing-Primary-Qwen"
    assert refusal["preferred_host_role"] == "primary"
    assert refusal["allowed_host_roles"] == ["primary"]
    assert "burst" in refusal["forbidden_host_roles"]
    assert refusal["allowed_fallbacks"] == ["Burst-Qwen-35B"]
    assert refusal["eligible_provider_ids"] == ["qwen"]
    assert refusal["failure_code"] == "no_legal_routing_candidate"
    assert "No routing candidate survived policy" in refusal["failure_reason"]
    assert refusal["routing_request_id"]

    failed_request = latest_failed_routing_request(root=tmp_path)
    assert failed_request is not None
    assert refusal["routing_request_id"] == failed_request.routing_request_id
    assert refusal["task_id"] == failed_request.task_id
