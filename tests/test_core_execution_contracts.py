from pathlib import Path

from runtime.core.artifact_store import promote_artifact, revoke_artifact, write_text_artifact
from runtime.core.execution_contracts import build_execution_contract_summary
from runtime.core.intake import create_task_from_message
from runtime.core.output_store import publish_artifact
from runtime.core.task_runtime import load_task, save_task
from runtime.core.task_store import recompute_task_readiness
from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.integrations.hermes_adapter import execute_hermes_task
from runtime.ralph.consolidator import execute_consolidation
from scripts.operator_handoff_pack import build_operator_handoff_pack


def test_backend_execution_contracts_emit_for_hermes(tmp_path: Path):
    created = create_task_from_message(
        text="task: write a general note",
        user="tester",
        lane="tests",
        channel="tests",
        message_id="msg_exec_contracts",
        root=tmp_path,
    )

    result = execute_hermes_task(
        task_id=created["task_id"],
        actor="tester",
        lane="tests",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "hermes_run_exec_1",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B",
            "title": "Hermes candidate",
            "summary": "candidate summary",
            "content": "candidate body",
        },
    )

    execution_summary = build_execution_contract_summary(root=tmp_path)
    latest_result = execution_summary["latest_backend_execution_result"]

    assert result["candidate_artifact_id"]
    assert execution_summary["backend_execution_request_count"] == 1
    assert execution_summary["backend_execution_result_count"] == 1
    assert latest_result["request_kind"] == "hermes_task"
    assert latest_result["status"] == "completed"
    assert latest_result["candidate_artifact_id"] == result["candidate_artifact_id"]


def test_ralph_execution_contracts_and_reporting_surface_cleanly(tmp_path: Path):
    created = create_task_from_message(
        text="task: summarize current task state",
        user="tester",
        lane="tests",
        channel="tests",
        message_id="msg_ralph_exec_contracts",
        root=tmp_path,
    )
    execute_consolidation(
        task_id=created["task_id"],
        actor="tester",
        lane="tests",
        root=tmp_path,
    )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]

    assert status["execution_contract_summary"]["backend_execution_result_count"] >= 1
    assert status["execution_contract_summary"]["latest_backend_execution_result"]["request_kind"] == "ralph_consolidation"
    assert status["routing_summary"]["enabled_input_modalities"] == ["text"]
    assert status["multimodal_summary"]["runtime_modality_mode"] == "text_only_qwen"
    assert snapshot["execution_contract_summary"]["backend_execution_result_count"] >= 1
    assert export_payload["counts"]["backend_execution_results"] >= 1
    assert handoff["execution_contract_summary"]["latest_backend_execution_result"]["request_kind"] == "ralph_consolidation"


def test_publish_readiness_recomputes_after_publish_and_revocation(tmp_path: Path):
    created = create_task_from_message(
        text="task: write a general note",
        user="tester",
        lane="tests",
        channel="tests",
        message_id="msg_recompute_readiness",
        root=tmp_path,
    )
    task_id = created["task_id"]
    artifact = write_text_artifact(
        task_id=task_id,
        artifact_type="report",
        title="Candidate artifact",
        summary="candidate summary",
        content="candidate body",
        actor="hermes",
        lane="tests",
        root=tmp_path,
        producer_kind="backend",
        execution_backend="qwen_executor",
    )
    promote_artifact(
        artifact_id=artifact["artifact_id"],
        actor="tester",
        lane="review",
        root=tmp_path,
    )

    task = load_task(tmp_path, task_id)
    task.final_outcome = "candidate_ready_for_live_apply"
    save_task(tmp_path, task)
    recompute_task_readiness(task_id=task_id, actor="tester", lane="tests", root=tmp_path, reason="arm ready state")
    task = load_task(tmp_path, task_id)
    assert task.publish_readiness_status == "ready"

    publish_artifact(
        task_id=task_id,
        artifact_id=artifact["artifact_id"],
        actor="tester",
        lane="outputs",
        root=tmp_path,
    )
    published_task = load_task(tmp_path, task_id)
    assert published_task.publish_readiness_status == "published"

    revoke_artifact(
        artifact_id=artifact["artifact_id"],
        actor="tester",
        lane="review",
        root=tmp_path,
        reason="upstream invalidated",
    )
    invalidated_task = load_task(tmp_path, task_id)
    assert invalidated_task.status == "blocked"
    assert invalidated_task.publish_readiness_status == "invalidated"
    assert invalidated_task.final_outcome == "candidate_invalidated"
    assert invalidated_task.blocked_dependency_refs
    assert any(ref.startswith("artifact:") or ref.startswith("output:") for ref in invalidated_task.blocked_dependency_refs)
