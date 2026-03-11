from pathlib import Path

from runtime.core.approval_store import request_approval
from runtime.core.artifact_store import promote_artifact, write_text_artifact
from runtime.core.intake import create_task_from_message
from runtime.core.provenance_store import build_provenance_summary, list_promotion_provenance
from runtime.core.review_store import record_review_verdict, request_review
from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from scripts.operator_handoff_pack import build_operator_handoff_pack


def test_promotion_provenance_is_persisted_for_promoted_artifacts(tmp_path: Path):
    created = create_task_from_message(
        text="task: write a promotion provenance test artifact",
        user="tester",
        lane="tests",
        channel="tests",
        message_id="msg_promotion_provenance",
        root=tmp_path,
    )
    task_id = created["task_id"]
    review = request_review(
        task_id=task_id,
        reviewer_role="archimedes",
        requested_by="tester",
        lane="review",
        summary="review for promotion provenance",
        root=tmp_path,
    )
    record_review_verdict(
        review_id=review.review_id,
        verdict="approved",
        actor="archimedes",
        lane="review",
        reason="approved for promotion lineage",
        root=tmp_path,
    )
    request_approval(
        task_id=task_id,
        approval_type="general",
        requested_by="tester",
        requested_reviewer="operator",
        lane="review",
        summary="approval linkage only",
        root=tmp_path,
    )
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
        backend_run_id="run_prom_1",
    )

    promote_artifact(
        artifact_id=artifact["artifact_id"],
        actor="tester",
        lane="review",
        root=tmp_path,
    )

    rows = list_promotion_provenance(root=tmp_path)
    provenance_summary = build_provenance_summary(root=tmp_path)
    status = build_status(tmp_path)
    export = build_state_export(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)
    handoff_pack = handoff["pack"]

    assert len(rows) == 1
    row = rows[0]
    assert row.artifact_id == artifact["artifact_id"]
    assert row.source_task_id == task_id
    assert row.source_backend == "qwen_executor"
    assert row.promoter == "tester"
    assert row.promoted_at is not None
    assert row.build_or_run_ref == "run_prom_1"
    assert row.input_refs["routing_decision_id"] == created["routing_contract"]["decision"]["routing_decision_id"]
    assert row.input_refs["backend_assignment_id"] == created["routing_contract"]["backend_assignment"]["backend_assignment_id"]
    assert row.reviewer == "archimedes"

    assert provenance_summary["promotion_provenance_count"] == 1
    assert provenance_summary["latest_promotion_provenance"]["artifact_id"] == artifact["artifact_id"]
    assert export["counts"]["promotion_provenance"] == 1
    assert status["provenance_summary"]["promotion_provenance_count"] == 1
    assert snapshot["provenance_summary"]["promotion_provenance_count"] == 1
    assert handoff_pack["provenance_summary"]["promotion_provenance_count"] == 1
