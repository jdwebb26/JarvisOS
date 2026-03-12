from pathlib import Path

from runtime.core.artifact_store import promote_artifact, write_text_artifact
from runtime.core.execution_contracts import record_backend_execution_request, record_backend_execution_result
from runtime.core.degradation_policy import record_degradation_event
from runtime.core.intake import create_task_from_message, create_task_from_message_result
from runtime.core.output_store import publish_artifact_result
from runtime.core.task_store import load_task, save_task
from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export


def _latest_discord_row(payload: dict) -> dict:
    rows = payload["discord_live_ops_summary"]["recent_discord_tasks"]
    assert rows
    return rows[0]


def test_discord_origin_task_surfaces_route_metadata_in_live_ops_summary(tmp_path: Path):
    created = create_task_from_message(
        text="task: write a short operator reply",
        user="tester",
        lane="jarvis",
        channel="discord_jarvis",
        message_id="discord_msg_success",
        root=tmp_path,
    )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)

    status_row = _latest_discord_row(status)
    snapshot_row = _latest_discord_row(snapshot)
    export_row = _latest_discord_row(export_payload)

    assert created["task_id"]
    assert status_row["source_front_door"] == "discord"
    assert status_row["source_lane"] == "jarvis"
    assert status_row["source_channel"] == "discord_jarvis"
    assert status_row["provider_id"] == "qwen"
    assert status_row["selected_model_name"] == "Qwen3.5-9B"
    assert status_row["selected_node_role"] == "primary"
    assert status_row["selected_host_name"] == "NIMO"
    assert status_row["workload_type"] == "general"
    assert status_row["routing_decision_id"]
    assert snapshot_row["selected_host_name"] == "NIMO"
    assert export_row["selected_model_name"] == "Qwen3.5-9B"


def test_discord_live_ops_summary_preserves_timeout_and_degraded_context(tmp_path: Path):
    created = create_task_from_message(
        text="task: investigate this failing model run",
        user="tester",
        lane="jarvis",
        channel="discord_jarvis",
        message_id="discord_msg_timeout",
        root=tmp_path,
    )
    task = load_task(created["task_id"], root=tmp_path)
    assert task is not None
    routing = (task.backend_metadata or {}).get("routing") or {}

    request = record_backend_execution_request(
        task_id=task.task_id,
        actor="tester",
        lane="discord",
        request_kind="discord_generation",
        execution_backend=task.execution_backend,
        provider_id=str(routing.get("provider_id") or "qwen"),
        model_name=task.assigned_model,
        routing_decision_id=routing.get("routing_decision_id"),
        provider_adapter_result_id=routing.get("provider_adapter_result_id"),
        input_summary="discord task execution",
        source_refs={"source_channel": task.source_channel},
        status="failed",
        root=tmp_path,
    )
    record_backend_execution_result(
        backend_execution_request_id=request.backend_execution_request_id,
        task_id=task.task_id,
        actor="tester",
        lane="discord",
        request_kind="discord_generation",
        execution_backend=task.execution_backend,
        provider_id=str(routing.get("provider_id") or "qwen"),
        model_name=task.assigned_model,
        status="failed",
        error="model timeout while waiting for reply",
        outcome_summary="generation timed out",
        source_refs={"source_channel": task.source_channel},
        metadata={"failure_category": "model_timeout"},
        root=tmp_path,
    )
    record_degradation_event(
        subsystem=task.execution_backend,
        actor="tester",
        lane="discord",
        failure_category="backend_timeout",
        reason="Degraded fallback blocked by policy",
        task_id=task.task_id,
        source_refs={
            "fallback_allowed": False,
            "fallback_legality_reasons": ["policy_blocked"],
            "authority_class": "review_required",
        },
        status="applied",
        root=tmp_path,
    )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)

    status_row = _latest_discord_row(status)
    snapshot_row = _latest_discord_row(snapshot)
    export_row = _latest_discord_row(export_payload)

    assert status_row["backend_failure_category"] == "model_timeout"
    assert status_row["degraded_fallback_blocked"] is True
    assert status_row["degraded_fallback_legality_reasons"] == ["policy_blocked"]
    assert status_row["degraded_failure_category"] == "backend_timeout"
    assert status_row["last_failure_reason"] == "Degraded fallback blocked by policy"
    assert snapshot_row["degraded_fallback_blocked"] is True
    assert export_row["backend_failure_category"] == "model_timeout"


def test_discord_live_ops_summary_surfaces_governance_blocked_publish(tmp_path: Path):
    created = create_task_from_message(
        text="task: prepare a publishable operator note",
        user="tester",
        lane="jarvis",
        channel="discord_jarvis",
        message_id="discord_msg_publish_block",
        root=tmp_path,
    )
    task = load_task(created["task_id"], root=tmp_path)
    assert task is not None

    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Discord operator note",
        summary="summary",
        content="content",
        actor="tester",
        lane="artifacts",
        root=tmp_path,
    )
    promote_artifact(
        artifact_id=artifact["artifact_id"],
        actor="tester",
        lane="review",
        root=tmp_path,
    )

    task.review_required = True
    save_task(task, root=tmp_path)

    result = publish_artifact_result(
        task_id=task.task_id,
        artifact_id=artifact["artifact_id"],
        actor="tester",
        lane="outputs",
        root=tmp_path,
    )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)

    status_row = _latest_discord_row(status)
    snapshot_row = _latest_discord_row(snapshot)
    export_row = _latest_discord_row(export_payload)

    assert result["ok"] is False
    assert result["error_type"] == "governance_blocked"
    assert status_row["last_failure_category"] == "governance_blocked"
    assert "reviewer lane is unavailable or uncleared" in str(status_row["governance_block_reason"])
    assert snapshot_row["governance_blocked_action_id"] == result["blocked"]["blocked_action_id"]
    assert export_row["governance_block_reason"] == result["blocked"]["reason"]


def test_discord_routing_refusal_surfaces_in_live_ops_summary(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "runtime_routing_policy.json").write_text(
        """{
  "defaults": {
    "preferred_provider": "qwen",
    "preferred_host_role": "primary",
    "allowed_host_roles": ["primary"],
    "forbidden_host_roles": ["burst"],
    "burst_allowed": false
  },
  "agent_policies": {
    "jarvis": {
      "preferred_host_role": "burst",
      "allowed_host_roles": ["burst"],
      "forbidden_host_roles": [],
      "burst_allowed": true,
      "allowed_fallbacks": []
    }
  }
}
""",
        encoding="utf-8",
    )

    result = create_task_from_message_result(
        text="task: write a short reply",
        user="tester",
        lane="jarvis",
        channel="discord_jarvis",
        message_id="discord_msg_routing_refusal",
        root=tmp_path,
    )
    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)

    assert result["ok"] is False
    assert result["error_type"] == "routing_refused"
    assert status["discord_live_ops_summary"]["latest_discord_routing_refusal"]["failure_code"] == "no_legal_routing_candidate"
    assert status["discord_live_ops_summary"]["latest_discord_routing_refusal"]["channel"] == "discord_jarvis"
    assert snapshot["discord_live_ops_summary"]["latest_discord_routing_refusal"]["preferred_host_role"] == "burst"
    assert export_payload["discord_live_ops_summary"]["latest_discord_routing_refusal"]["allowed_host_roles"] == ["burst"]
