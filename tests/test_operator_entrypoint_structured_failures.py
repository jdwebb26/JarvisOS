from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.intake import TaskCreationRefusalError, create_task_from_message, create_task_from_message_result
from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.output_store import publish_artifact, publish_artifact_result
from runtime.core.publish_complete import publish_and_complete
from runtime.core.promotion_governance import GovernanceBlockedError, latest_governance_block_for_task_action
from runtime.core.review_store import request_review
from runtime.core.approval_store import request_approval
from runtime.core.task_runtime import save_task
from runtime.core.task_store import create_task
from runtime.core.artifact_store import write_text_artifact, promote_artifact


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


def test_task_creation_entrypoint_returns_structured_routing_refusal(tmp_path: Path) -> None:
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
            message_id="msg_refusal",
            root=tmp_path,
        )
    except TaskCreationRefusalError as exc:
        refusal = dict(exc.refusal)
    else:
        raise AssertionError("Expected routing refusal.")

    result = create_task_from_message_result(
        text="task: write a short reply",
        user="tester",
        lane="tests",
        channel="tests",
        message_id="msg_refusal_result",
        root=tmp_path,
    )

    assert result["ok"] is False
    assert result["error_type"] == "routing_refused"
    for key in (
        "lane",
        "channel",
        "workload_type",
        "task_type",
        "risk_level",
        "preferred_provider",
        "preferred_model",
        "preferred_host_role",
        "allowed_host_roles",
        "forbidden_host_roles",
        "allowed_fallbacks",
        "eligible_provider_ids",
        "failure_code",
        "failure_reason",
        "status",
    ):
        assert result["refusal"][key] == refusal[key]


def test_publish_entrypoint_returns_structured_governance_block(tmp_path: Path) -> None:
    task = _make_task(tmp_path, task_id="task_publish_structured_block")
    task.approval_required = True
    save_task(tmp_path, task)
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Promoted output",
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
        blocked = dict(exc.blocked)
    else:
        raise AssertionError("Expected governance block.")

    result = publish_artifact_result(
        task_id=task.task_id,
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="outputs",
        root=tmp_path,
    )

    assert result["ok"] is False
    assert result["error_type"] == "governance_blocked"
    for key in ("action", "task_id", "provider_id", "subsystem", "reason", "metadata"):
        assert result["blocked"][key] == blocked[key]
    durable = latest_governance_block_for_task_action(
        task_id=task.task_id,
        action="publish_output",
        root=tmp_path,
    )
    assert durable is not None
    for key in ("action", "task_id", "provider_id", "subsystem", "reason", "metadata"):
        assert result["blocked"][key] == durable[key]


def test_publish_complete_returns_structured_governance_block(tmp_path: Path) -> None:
    task = _make_task(tmp_path, task_id="task_publish_complete_block")
    task.approval_required = True
    save_task(tmp_path, task)
    artifact = write_text_artifact(
        task_id=task.task_id,
        artifact_type="report",
        title="Promoted for publish complete",
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
    task.status = TaskStatus.RUNNING.value
    save_task(tmp_path, task)

    result = publish_and_complete(
        task_id=task.task_id,
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="outputs",
        final_outcome="",
        root=tmp_path,
    )

    assert result["ok"] is False
    assert result["error_type"] == "governance_blocked"
    assert result["blocked"]["action"] == "publish_output"
    assert result["blocked"]["metadata"]["policy_block_kind"] == "approval_gate_uncleared"
    durable = latest_governance_block_for_task_action(
        task_id=task.task_id,
        action="publish_output",
        root=tmp_path,
    )
    assert durable is not None
    for key in ("action", "task_id", "provider_id", "subsystem", "reason", "metadata"):
        assert result["blocked"][key] == durable[key]


def test_successful_operator_entrypoint_behavior_is_unchanged(tmp_path: Path) -> None:
    intake = create_task_from_message_result(
        text="task: write a short general note",
        user="tester",
        lane="jarvis",
        channel="jarvis",
        message_id="msg_success",
        root=tmp_path,
    )
    assert intake["ok"] is True
    task_id = intake["task_id"]

    task = _make_task(tmp_path, task_id=f"{task_id}_publish")
    request_review(
        task_id=task.task_id,
        reviewer_role="operator",
        requested_by="tester",
        lane="review",
        summary="approve review",
        root=tmp_path,
    )
    from runtime.core.review_store import latest_review_for_task, record_review_verdict

    review = latest_review_for_task(task.task_id, root=tmp_path)
    assert review is not None
    record_review_verdict(
        review_id=review.review_id,
        verdict="approved",
        actor="operator",
        lane="review",
        reason="approved",
        root=tmp_path,
    )
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
    promote_artifact(
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="review",
        root=tmp_path,
    )
    publish = publish_artifact_result(
        task_id=task.task_id,
        artifact_id=artifact["artifact_id"],
        actor="operator",
        lane="outputs",
        root=tmp_path,
    )
    assert publish["ok"] is True
    assert publish["artifact_id"] == artifact["artifact_id"]


def _run_as_script() -> int:
    with TemporaryDirectory() as tmp_one:
        test_task_creation_entrypoint_returns_structured_routing_refusal(Path(tmp_one))
    with TemporaryDirectory() as tmp_two:
        test_publish_entrypoint_returns_structured_governance_block(Path(tmp_two))
    with TemporaryDirectory() as tmp_three:
        test_publish_complete_returns_structured_governance_block(Path(tmp_three))
    with TemporaryDirectory() as tmp_four:
        test_successful_operator_entrypoint_behavior_is_unchanged(Path(tmp_four))
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_as_script())
