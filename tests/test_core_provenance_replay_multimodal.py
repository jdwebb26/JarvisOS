from pathlib import Path

from runtime.core.intake import create_task_from_message
from runtime.core.artifact_store import promote_artifact, write_text_artifact
from runtime.core.output_store import publish_artifact
from runtime.core.provenance_store import build_provenance_summary, list_publish_provenance
from runtime.core.replay_store import (
    build_candidate_promotion_replay_plan,
    build_route_replay_plan,
    execute_replay_plan,
)
from runtime.core.rollback_store import execute_artifact_revocation, list_revocation_impacts
from runtime.core.review_store import request_review
from runtime.core.approval_store import request_approval
from runtime.core.models import MemoryCandidateRecord, new_id, now_iso
from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.memory.governance import register_memory_candidate
from runtime.core.modality_contracts import build_modality_summary
from scripts.operator_handoff_pack import build_operator_handoff_pack


def test_provenance_is_emitted_across_routing_candidate_promotion_and_publish(tmp_path: Path):
    created = create_task_from_message(
        text="task: write a general note",
        user="tester",
        lane="tests",
        channel="tests",
        message_id="msg_provenance",
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
        lane="research",
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
    publish_artifact(
        task_id=task_id,
        artifact_id=artifact["artifact_id"],
        actor="tester",
        lane="outputs",
        root=tmp_path,
    )

    provenance = build_provenance_summary(root=tmp_path)
    publish_rows = list_publish_provenance(root=tmp_path)

    assert provenance["task_provenance_count"] == 1
    assert provenance["routing_provenance_count"] == 1
    assert provenance["artifact_provenance_count"] >= 2
    assert provenance["decision_provenance_count"] >= 1
    assert provenance["publish_provenance_count"] == 1
    assert publish_rows[0].artifact_id == artifact["artifact_id"]
    assert publish_rows[0].replay_input["task_id"] == task_id


def test_replay_plan_and_execution_classify_match_and_drift(tmp_path: Path):
    created = create_task_from_message(
        text="task: write a general note",
        user="tester",
        lane="tests",
        channel="tests",
        message_id="msg_replay_route",
        root=tmp_path,
    )
    route_plan = build_route_replay_plan(
        routing_decision_id=created["routing_contract"]["decision"]["routing_decision_id"],
        actor="tester",
        lane="replay",
        root=tmp_path,
    )
    route_result = execute_replay_plan(
        replay_plan_id=route_plan.replay_plan_id,
        actor="tester",
        lane="replay",
        root=tmp_path,
    )
    assert route_result["replay_result"]["result_kind"] == "match"

    second = create_task_from_message(
        text="task: write another general note",
        user="tester",
        lane="tests",
        channel="tests",
        message_id="msg_replay_promotion",
        root=tmp_path,
    )
    artifact = write_text_artifact(
        task_id=second["task_id"],
        artifact_type="report",
        title="Unpromoted candidate",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
        execution_backend="qwen_executor",
    )
    promotion_plan = build_candidate_promotion_replay_plan(
        artifact_id=artifact["artifact_id"],
        actor="tester",
        lane="replay",
        root=tmp_path,
    )
    promotion_result = execute_replay_plan(
        replay_plan_id=promotion_plan.replay_plan_id,
        actor="tester",
        lane="replay",
        root=tmp_path,
    )
    assert promotion_result["replay_result"]["result_kind"] == "drift"


def test_revocation_propagation_records_downstream_impacts(tmp_path: Path):
    created = create_task_from_message(
        text="task: write a general note",
        user="tester",
        lane="tests",
        channel="tests",
        message_id="msg_revoke_propagation",
        root=tmp_path,
    )
    task_id = created["task_id"]
    artifact = write_text_artifact(
        task_id=task_id,
        artifact_type="report",
        title="Linked candidate",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
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
    publish_artifact(
        task_id=task_id,
        artifact_id=artifact["artifact_id"],
        actor="tester",
        lane="outputs",
        root=tmp_path,
    )
    request_review(
        task_id=task_id,
        reviewer_role="archimedes",
        requested_by="tester",
        lane="review",
        summary="pending review link",
        linked_artifact_ids=[artifact["artifact_id"]],
        root=tmp_path,
    )
    request_approval(
        task_id=task_id,
        approval_type="general",
        requested_by="tester",
        requested_reviewer="anton",
        lane="review",
        summary="pending approval link",
        linked_artifact_ids=[artifact["artifact_id"]],
        root=tmp_path,
    )
    register_memory_candidate(
        record=MemoryCandidateRecord(
            memory_candidate_id=new_id("memcand"),
            consolidation_run_id="manual",
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor="tester",
            lane="memory",
            candidate_kind="memory_candidate",
            memory_type="task_digest",
            title="Memory tied to artifact",
            summary="candidate memory",
            content="remember this",
            source_artifact_ids=[artifact["artifact_id"]],
            source_provenance_refs={"artifact_id": artifact["artifact_id"]},
            execution_backend="ralph_adapter",
        ),
        actor="tester",
        lane="memory",
        root=tmp_path,
    )

    execute_artifact_revocation(
        artifact_id=artifact["artifact_id"],
        task_id=task_id,
        actor="tester",
        lane="review",
        reason="upstream invalidated",
        root=tmp_path,
    )

    impact_kinds = {row.impact_kind for row in list_revocation_impacts(root=tmp_path)}
    assert "output_invalidated" in impact_kinds
    assert "memory_eligibility_invalidated" in impact_kinds
    assert "approval_in_flight_impacted" in impact_kinds
    assert "review_linked_candidate_impacted" in impact_kinds
    assert "candidate_lifecycle_impacted" in impact_kinds
    assert "task_publish_readiness_invalidated" in impact_kinds


def test_multimodal_and_replay_summaries_surface_in_reporting(tmp_path: Path):
    created = create_task_from_message(
        text="task: write a general note",
        user="tester",
        lane="tests",
        channel="tests",
        message_id="msg_reporting_multimodal",
        root=tmp_path,
    )
    route_plan = build_route_replay_plan(
        routing_decision_id=created["routing_contract"]["decision"]["routing_decision_id"],
        actor="tester",
        lane="replay",
        root=tmp_path,
    )
    execute_replay_plan(
        replay_plan_id=route_plan.replay_plan_id,
        actor="tester",
        lane="replay",
        root=tmp_path,
    )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]
    modality_summary = build_modality_summary(tmp_path)

    assert status["provenance_summary"]["task_provenance_count"] >= 1
    assert status["replay_summary"]["replay_execution_count"] >= 1
    assert status["multimodal_summary"]["modality_contract_count"] >= 1
    assert snapshot["replay_summary"]["latest_replay_result"]["result_kind"] == "match"
    assert export_payload["counts"]["replay_results"] >= 1
    assert export_payload["counts"]["modality_contracts"] >= 1
    assert handoff["replay_summary"]["latest_replay_result"]["result_kind"] == "match"
    assert handoff["multimodal_summary"]["modality_contract_count"] == modality_summary["modality_contract_count"]
