from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.artifact_store import promote_artifact, write_text_artifact
from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.output_store import publish_artifact
from runtime.core.promotion_governance import GovernanceBlockedError, latest_governance_block_for_task_action
from runtime.core.review_store import request_review
from runtime.core.approval_store import request_approval
from runtime.core.status import build_status
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.core.task_runtime import save_task
from runtime.core.task_store import create_task


def _make_task(root: Path, *, task_id: str) -> TaskRecord:
    return create_task(
        TaskRecord(
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            source_lane="tests",
            source_channel="tests",
            source_message_id=f"{task_id}_msg",
            source_user="tester",
            trigger_type="explicit_task_colon",
            raw_request=f"task: {task_id}",
            normalized_request=task_id,
            task_type="research",
            status=TaskStatus.RUNNING.value,
            execution_backend="qwen_executor",
        ),
        root=root,
    )


def test_promotion_blocked_by_pending_review_returns_structured_contract(tmp_path: Path) -> None:
    task = _make_task(tmp_path, task_id="task_promotion_blocked_review")
    task.review_required = True
    save_task(tmp_path, task)
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Candidate review gate",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
        execution_backend="qwen_executor",
    )
    request_review(
        task_id=task.task_id,
        reviewer_role="operator",
        requested_by="tester",
        lane="review",
        summary="pending review",
        root=tmp_path,
    )

    try:
        promote_artifact(
            artifact_id=artifact["artifact_id"],
            actor="operator",
            lane="review",
            root=tmp_path,
        )
    except GovernanceBlockedError as exc:
        blocked = exc.blocked
    else:
        raise AssertionError("Expected structured promotion governance block.")

    durable = latest_governance_block_for_task_action(
        task_id=task.task_id,
        action="promote_artifact",
        root=tmp_path,
    )
    assert durable is not None
    assert blocked == durable
    assert blocked["action"] == "promote_artifact"
    assert blocked["task_id"] == task.task_id
    assert blocked["subsystem"] == "qwen_executor"
    assert blocked["metadata"]["policy_block_kind"] == "review_gate_uncleared"
    assert blocked["metadata"]["latest_review_status"] == "pending"

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    assert status["control_state"]["latest_blocked_action"]["blocked_action_id"] == blocked["blocked_action_id"]
    assert snapshot["control_state"]["latest_blocked_action"]["blocked_action_id"] == blocked["blocked_action_id"]
    assert export_payload["promotion_governance_summary"]["latest_blocked_action"]["blocked_action_id"] == blocked["blocked_action_id"]


def test_publish_blocked_by_pending_approval_returns_structured_contract(tmp_path: Path) -> None:
    task = _make_task(tmp_path, task_id="task_publish_blocked_approval")
    task.approval_required = True
    save_task(tmp_path, task)
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Promoted approval gate",
        summary="promoted",
        content="body",
        actor="operator",
        lane="artifacts",
        root=tmp_path,
    )
    request_approval(
        task_id=task.task_id,
        approval_type="deploy",
        requested_by="tester",
        requested_reviewer="anton",
        lane="review",
        summary="pending approval",
        root=tmp_path,
    )

    try:
        publish_artifact(
            task_id=task.task_id,
            artifact_id=artifact["artifact_id"],
            actor="operator",
            lane="outputs",
            root=tmp_path,
        )
    except GovernanceBlockedError as exc:
        blocked = exc.blocked
    else:
        raise AssertionError("Expected structured publish governance block.")

    durable = latest_governance_block_for_task_action(
        task_id=task.task_id,
        action="publish_output",
        root=tmp_path,
    )
    assert durable is not None
    assert blocked == durable
    assert blocked["action"] == "publish_output"
    assert blocked["task_id"] == task.task_id
    assert blocked["metadata"]["policy_block_kind"] == "approval_gate_uncleared"
    assert blocked["metadata"]["latest_approval_status"] == "pending"


def test_successful_promotion_and_publish_behavior_is_unchanged(tmp_path: Path) -> None:
    task = _make_task(tmp_path, task_id="task_publish_success")
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Candidate success",
        summary="candidate",
        content="body",
        actor="hermes",
        lane="research",
        root=tmp_path,
        producer_kind="backend",
        execution_backend="qwen_executor",
    )

    promoted = promote_artifact(
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="review",
        root=tmp_path,
    )
    published = publish_artifact(
        task_id=task.task_id,
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="outputs",
        root=tmp_path,
    )

    assert promoted.lifecycle_state == "promoted"
    assert published["artifact_id"] == artifact["artifact_id"]
    assert latest_governance_block_for_task_action(
        task_id=task.task_id,
        action="publish_output",
        root=tmp_path,
    ) is None


def _run_as_script() -> int:
    with TemporaryDirectory() as tmp_one:
        test_promotion_blocked_by_pending_review_returns_structured_contract(Path(tmp_one))
    with TemporaryDirectory() as tmp_two:
        test_publish_blocked_by_pending_approval_returns_structured_contract(Path(tmp_two))
    with TemporaryDirectory() as tmp_three:
        test_successful_promotion_and_publish_behavior_is_unchanged(Path(tmp_three))
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_as_script())
