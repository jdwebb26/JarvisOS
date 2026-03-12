from pathlib import Path

from runtime.core.heartbeat_reports import build_node_health_summary, write_node_heartbeat
from runtime.core.routing import route_task_intent
from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export


def test_primary_nimo_route_remains_default(tmp_path: Path) -> None:
    result = route_task_intent(
        task_id="task_topology_primary",
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

    assert result["decision"]["selected_model_name"] == "Qwen3.5-9B"
    assert result["decision"]["selected_node_role"] == "primary"
    assert result["decision"]["selected_host_name"] == "NIMO"


def test_burst_worker_absence_does_not_look_like_primary_outage(tmp_path: Path) -> None:
    write_node_heartbeat(
        node_name="NIMO",
        status="healthy",
        actor="tester",
        lane="tests",
        backend_summary=["qwen_executor", "qwen_planner", "operator"],
        model_family_summary=["qwen"],
        root=tmp_path,
    )
    write_node_heartbeat(
        node_name="LOCAL",
        status="healthy",
        actor="tester",
        lane="tests",
        backend_summary=["memory_spine", "evaluation_spine", "operator"],
        model_family_summary=["local"],
        root=tmp_path,
    )

    node_health = build_node_health_summary(root=tmp_path)
    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)

    assert node_health["primary_online_count"] == 1
    assert node_health["primary_outage_count"] == 0
    assert node_health["optional_burst_offline_count"] == 1
    assert node_health["topology_posture"] == "healthy_optional_burst_offline"
    assert "optional burst capacity is offline" in node_health["topology_notes"][0]

    assert status["heartbeat_summary"]["node_health_summary"]["topology_posture"] == "healthy_optional_burst_offline"
    assert snapshot["node_health_summary"]["optional_burst_offline_count"] == 1
    assert export_payload["heartbeat_summary"]["node_health_summary"]["primary_outage_count"] == 0

    active_nodes = {row["node_id"] for row in snapshot["active_nodes_summary"]["latest_nodes"]}
    assert "NIMO" in active_nodes
    assert "LOCAL" in active_nodes
    assert "Koolkidclub" not in active_nodes


def test_local_embeddings_lane_remains_distinct(tmp_path: Path) -> None:
    result = route_task_intent(
        task_id="task_topology_local_embeddings",
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
