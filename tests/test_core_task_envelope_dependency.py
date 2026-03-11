from pathlib import Path

import pytest

from runtime.core.approval_store import request_approval
from runtime.core.artifact_store import promote_artifact, write_text_artifact
from runtime.core.models import TaskRecord, now_iso
from runtime.core.status import build_status
from runtime.core.task_store import create_task, load_task, transition_task
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from scripts.operator_handoff_pack import build_operator_handoff_pack


def _task(
    task_id: str,
    *,
    parent_task_id: str | None = None,
    speculative_downstream: bool = False,
    autonomy_mode: str = "step_mode",
    task_envelope: dict | None = None,
) -> TaskRecord:
    created_at = now_iso()
    return TaskRecord(
        task_id=task_id,
        created_at=created_at,
        updated_at=created_at,
        source_lane="tests",
        source_channel="tests",
        source_message_id=f"msg_{task_id}",
        source_user="tester",
        trigger_type="explicit_task_colon",
        raw_request=f"task: {task_id}",
        normalized_request=f"{task_id} work",
        task_type="general",
        priority="normal",
        risk_level="normal",
        review_required=False,
        approval_required=False,
        parent_task_id=parent_task_id,
        speculative_downstream=speculative_downstream,
        autonomy_mode=autonomy_mode,
        task_envelope=dict(task_envelope or {}),
    )


def test_task_envelope_and_autonomy_mode_surface_in_reporting(tmp_path: Path):
    task = _task(
        "task_envelope_visibility",
        autonomy_mode="bounded_autonomous",
        task_envelope={
            "allowed_paths": ["/workspace/out"],
            "max_runtime_minutes": 15,
            "requires_checkpoints": True,
            "forbidden_actions": ["publish_without_review"],
        },
    )
    create_task(task, root=tmp_path)

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]

    assert status["queued_now"][0]["autonomy_mode"] == "bounded_autonomous"
    assert status["queued_now"][0]["task_envelope"]["max_runtime_minutes"] == 15
    assert status["task_envelope_summary"]["task_envelope_task_count"] == 1
    assert snapshot["task_envelope_summary"]["autonomy_mode_counts"]["bounded_autonomous"] == 1
    assert export_payload["task_envelope_summary"]["task_envelope_task_count"] == 1
    assert handoff["task_envelope_summary"]["autonomy_mode_counts"]["bounded_autonomous"] == 1


def test_parent_approval_blocks_non_speculative_dependent_task(tmp_path: Path):
    parent = _task("task_parent_approval")
    create_task(parent, root=tmp_path)
    request_approval(
        task_id=parent.task_id,
        approval_type="general",
        requested_by="tester",
        requested_reviewer="operator",
        lane="tests",
        summary="need approval",
        root=tmp_path,
    )

    child = _task("task_child_blocked", parent_task_id=parent.task_id)
    create_task(child, root=tmp_path)
    child_after = load_task(child.task_id, root=tmp_path)

    assert child_after is not None
    assert child_after.status == "blocked"
    assert child_after.publish_readiness_status == "blocked_dependency"
    assert any(ref.startswith("parent_approval_blocked:") for ref in child_after.blocked_dependency_refs)
    assert "blocked on approval" in child_after.dependency_block_reason

    with pytest.raises(ValueError, match="blocked on approval"):
        transition_task(
            task_id=child.task_id,
            to_status="running",
            actor="tester",
            lane="tests",
            root=tmp_path,
            summary="try progress blocked child",
        )


def test_speculative_downstream_can_stay_candidate_only_but_cannot_promote(tmp_path: Path):
    parent = _task("task_parent_speculative")
    create_task(parent, root=tmp_path)
    request_approval(
        task_id=parent.task_id,
        approval_type="general",
        requested_by="tester",
        requested_reviewer="operator",
        lane="tests",
        summary="need approval",
        root=tmp_path,
    )

    child = _task(
        "task_child_speculative",
        parent_task_id=parent.task_id,
        speculative_downstream=True,
        autonomy_mode="bounded_autonomous",
    )
    create_task(child, root=tmp_path)
    artifact = write_text_artifact(
        task_id=child.task_id,
        artifact_type="report",
        title="speculative candidate",
        summary="candidate summary",
        content="candidate body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
        execution_backend="qwen_executor",
    )

    child_after = load_task(child.task_id, root=tmp_path)
    assert child_after is not None
    assert child_after.status == "queued"
    assert child_after.publish_readiness_status == "candidate_only"
    assert any(ref.startswith("speculative_parent_approval:") for ref in child_after.blocked_dependency_refs)

    with pytest.raises(ValueError, match="candidate-only work may proceed but promotion/publish remains blocked"):
        promote_artifact(
            artifact_id=artifact["artifact_id"],
            actor="tester",
            lane="tests",
            root=tmp_path,
        )
