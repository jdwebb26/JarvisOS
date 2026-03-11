from pathlib import Path

from runtime.core.backend_assignments import list_backend_assignments
from runtime.core.intake import create_task_from_message
from runtime.core.routing import route_task_intent
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
