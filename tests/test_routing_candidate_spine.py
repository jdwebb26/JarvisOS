from pathlib import Path

from runtime.core.artifact_store import promote_artifact, write_text_artifact
from runtime.core.candidate_store import (
    build_candidate_summary,
    list_candidates,
    list_promotion_decisions,
    list_rejection_decisions,
    list_validations,
    record_candidate_validation,
)
from runtime.core.intake import create_task_from_message
from runtime.core.review_store import request_review, record_review_verdict
from runtime.core.routing import build_model_registry_summary, route_task_intent
from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from scripts.operator_handoff_pack import build_operator_handoff_pack


def test_qwen_only_routing_contracts_are_deterministic(tmp_path: Path):
    general = route_task_intent(
        task_id="task_route_general",
        normalized_request="write a general note",
        task_type="general",
        risk_level="normal",
        priority="normal",
        actor="tester",
        lane="tests",
        root=tmp_path,
    )
    repeated = route_task_intent(
        task_id="task_route_general_repeat",
        normalized_request="write a general note",
        task_type="general",
        risk_level="normal",
        priority="normal",
        actor="tester",
        lane="tests",
        root=tmp_path,
    )
    high_stakes = route_task_intent(
        task_id="task_route_deploy",
        normalized_request="deploy the live service",
        task_type="deploy",
        risk_level="high_stakes",
        priority="high",
        actor="tester",
        lane="tests",
        root=tmp_path,
    )

    assert general["active_registry"]["active_model_names"] == [
        "Qwen3.5-9B",
        "Qwen3.5-35B",
        "Qwen3.5-122B",
    ]
    assert general["decision"]["selected_model_name"] == "Qwen3.5-35B"
    assert general["decision"]["selected_execution_backend"] == "qwen_executor"
    assert repeated["decision"]["selected_model_name"] == general["decision"]["selected_model_name"]
    assert repeated["decision"]["selected_execution_backend"] == general["decision"]["selected_execution_backend"]
    assert high_stakes["decision"]["selected_model_name"] == "Qwen3.5-122B"
    assert high_stakes["decision"]["selected_execution_backend"] == "qwen_planner"


def test_candidate_creation_validation_and_promotion_scaffolding(tmp_path: Path):
    created = create_task_from_message(
        text="task: write a general note",
        user="tester",
        lane="tests",
        channel="tests",
        message_id="msg_candidate_create",
        root=tmp_path,
    )
    task_id = created["task_id"]

    artifact = write_text_artifact(
        task_id=task_id,
        artifact_type="report",
        title="Backend candidate",
        summary="candidate summary",
        content="candidate body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
        execution_backend="qwen_executor",
    )

    candidates = list_candidates(root=tmp_path)
    validations = list_validations(root=tmp_path)
    assert len(candidates) == 1
    assert len(validations) == 1
    assert candidates[0].artifact_id == artifact["artifact_id"]
    assert candidates[0].model_name == "Qwen3.5-35B"
    assert candidates[0].provider_id == "qwen"
    assert validations[0].validator_kind == "candidate_registration"
    assert validations[0].status == "passed"

    manual_validation = record_candidate_validation(
        candidate_id=candidates[0].candidate_id,
        task_id=task_id,
        actor="tester",
        lane="validation",
        validator_kind="artifact_quality_gate",
        status="passed",
        summary="passed quality gate",
        details="scaffolding validation recorded",
        evidence_refs={"artifact_id": artifact["artifact_id"]},
        root=tmp_path,
    )
    promoted = promote_artifact(
        artifact_id=artifact["artifact_id"],
        actor="tester",
        lane="review",
        root=tmp_path,
        provenance_ref="manual:test",
    )

    summary = build_candidate_summary(root=tmp_path)
    assert manual_validation.validation_id == summary["latest_validation"]["validation_id"]
    assert promoted.artifact_id == artifact["artifact_id"]
    assert summary["latest_candidate"]["lifecycle_state"] == "promoted"
    assert summary["latest_event"]["event_kind"] == "promotion"
    assert list_promotion_decisions(root=tmp_path)[0].artifact_id == artifact["artifact_id"]


def test_explicit_rejection_scaffolding_tracks_review_rejection(tmp_path: Path):
    created = create_task_from_message(
        text="task: fix python bug",
        user="tester",
        lane="tests",
        channel="tests",
        message_id="msg_candidate_reject",
        root=tmp_path,
    )
    task_id = created["task_id"]
    artifact = write_text_artifact(
        task_id=task_id,
        artifact_type="report",
        title="Reject me",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
        execution_backend="qwen_executor",
    )

    review = request_review(
        task_id=task_id,
        reviewer_role="archimedes",
        requested_by="tester",
        lane="review",
        summary="review candidate",
        root=tmp_path,
    )
    record_review_verdict(
        review_id=review.review_id,
        verdict="changes_requested",
        actor="archimedes",
        lane="review",
        reason="not ready",
        root=tmp_path,
    )

    rejections = list_rejection_decisions(root=tmp_path)
    candidates = list_candidates(root=tmp_path)
    assert len(rejections) == 1
    assert rejections[0].artifact_id == artifact["artifact_id"]
    assert rejections[0].trigger_event == f"review:{review.review_id}"
    assert candidates[0].lifecycle_state == "demoted"


def test_routing_and_candidate_reporting_surfaces_latest_records(tmp_path: Path):
    created = create_task_from_message(
        text="task: write a general note",
        user="tester",
        lane="tests",
        channel="tests",
        message_id="msg_reporting",
        root=tmp_path,
    )
    write_text_artifact(
        task_id=created["task_id"],
        artifact_type="report",
        title="Reportable candidate",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
        execution_backend="qwen_executor",
    )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]
    registry_summary = build_model_registry_summary(tmp_path)

    assert registry_summary["active_model_count"] == 3
    assert status["routing_summary"]["latest_routing_decision"]["selected_model_name"] == "Qwen3.5-35B"
    assert status["candidate_promotion_summary"]["latest_candidate"]["lifecycle_state"] == "candidate"
    assert snapshot["routing_summary"]["active_model_count"] == 3
    assert snapshot["candidate_promotion_summary"]["validation_count"] >= 1
    assert export_payload["counts"]["routing_decisions"] >= 1
    assert export_payload["counts"]["candidate_records"] >= 1
    assert handoff["model_registry_summary"]["active_model_count"] == 3
    assert handoff["candidate_promotion_summary"]["latest_validation"]["status"] == "passed"
