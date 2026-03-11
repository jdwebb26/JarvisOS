from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.controls.control_store import apply_control_action
from runtime.core.approval_store import load_approval_checkpoint, load_approval, request_approval
from runtime.core.artifact_store import load_artifact
from runtime.core.models import ControlScopeType, RecordLifecycleState, TaskRecord, TaskStatus, now_iso
from runtime.core.status import build_status
from runtime.core.review_store import load_review, request_review
from runtime.core.task_store import create_task, load_task
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.integrations.hermes_adapter import (
    HERMES_BACKEND_ID,
    execute_hermes_task,
    load_hermes_request,
    load_hermes_result,
)
from scripts.operator_handoff_pack import build_operator_handoff_pack


class raises:
    def __init__(self, exc_type, match: str = ""):
        self.exc_type = exc_type
        self.match = match
        self.caught = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, _tb):
        if exc is None:
            raise AssertionError(f"Expected {self.exc_type.__name__} to be raised.")
        if not isinstance(exc, self.exc_type):
            return False
        self.caught = exc
        if self.match and not re.search(self.match, str(exc)):
            raise AssertionError(f"Exception {exc!r} did not match /{self.match}/.")
        return True


def _make_task(
    root: Path,
    *,
    task_id: str,
    status: str,
    review_required: bool = False,
    approval_required: bool = False,
) -> TaskRecord:
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
            status=status,
            execution_backend="qwen_executor",
            review_required=review_required,
            approval_required=approval_required,
        ),
        root=root,
    )


def _success_transport(_request):
    return {
        "run_id": "hermes_run_123",
        "family": "qwen3.5",
        "model_name": "Qwen3.5-35B-A3B",
        "title": "Hermes candidate",
        "summary": "Thin adapter candidate artifact",
        "content": "bounded backend output",
    }


def test_hermes_success_updates_pending_review_and_writes_candidate(tmp_path: Path):
    task = _make_task(
        tmp_path,
        task_id="task_hermes_review",
        status=TaskStatus.WAITING_REVIEW.value,
        review_required=True,
    )
    review = request_review(
        task_id=task.task_id,
        reviewer_role="anton",
        requested_by="tester",
        lane="review",
        summary="review pending",
        root=tmp_path,
    )
    assert review.linked_artifact_ids == []

    result = execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=_success_transport,
    )

    stored_task = load_task(task.task_id, root=tmp_path)
    stored_review = load_review(review.review_id, root=tmp_path)
    stored_artifact = load_artifact(result["candidate_artifact_id"], root=tmp_path)
    stored_request = load_hermes_request(result["request"]["request_id"], root=tmp_path)
    stored_result = load_hermes_result(result["result"]["result_id"], root=tmp_path)

    assert stored_task is not None
    assert stored_task.execution_backend == HERMES_BACKEND_ID
    assert stored_task.status == TaskStatus.WAITING_REVIEW.value
    assert stored_task.backend_metadata["hermes"]["candidate_artifact_id"] == result["candidate_artifact_id"]
    assert stored_review is not None
    assert stored_review.linked_artifact_ids == [result["candidate_artifact_id"]]
    assert stored_artifact.lifecycle_state == RecordLifecycleState.CANDIDATE.value
    assert stored_artifact.execution_backend == HERMES_BACKEND_ID
    assert stored_request["objective"] == task.normalized_request
    assert stored_request["allowed_tools"] == ["candidate_artifact_write", "bounded_research_synthesis"]
    assert stored_request["return_format"] == "candidate_artifact"
    assert stored_request["capability_declaration"]["task_type"] == task.task_type
    assert stored_result["status"] == "completed"
    assert stored_result["checkpoint_summary"] == f"Hermes candidate stored: {result['candidate_artifact_id']}"
    assert stored_result["artifacts"][0]["artifact_id"] == result["candidate_artifact_id"]
    assert stored_result["error_summary"] == ""
    assert stored_result["failure_category"] == ""


def test_hermes_success_updates_pending_approval_checkpoint(tmp_path: Path):
    task = _make_task(
        tmp_path,
        task_id="task_hermes_approval",
        status=TaskStatus.WAITING_APPROVAL.value,
        approval_required=True,
    )
    approval = request_approval(
        task_id=task.task_id,
        approval_type="deploy",
        requested_by="tester",
        requested_reviewer="anton",
        lane="review",
        summary="approval pending",
        root=tmp_path,
    )
    assert approval.linked_artifact_ids == []

    result = execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=_success_transport,
    )

    stored_approval = load_approval(approval.approval_id, root=tmp_path)
    checkpoint = load_approval_checkpoint(approval.resumable_checkpoint_id, root=tmp_path)

    assert stored_approval is not None
    assert stored_approval.linked_artifact_ids == [result["candidate_artifact_id"]]
    assert checkpoint is not None
    assert checkpoint.linked_artifact_ids == [result["candidate_artifact_id"]]


def test_hermes_malformed_response_blocks_task(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_hermes_malformed", status=TaskStatus.RUNNING.value)

    result = execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {"summary": "missing title and content"},
    )

    stored_task = load_task(task.task_id, root=tmp_path)
    assert stored_task is not None
    assert stored_task.status == TaskStatus.BLOCKED.value
    assert result["candidate_artifact_id"] is None
    assert result["result"]["status"] == "malformed"
    assert result["result"]["error_summary"]
    assert result["result"]["failure_category"] == "malformed_response"


def test_hermes_invalid_request_contract_blocks_before_dispatch(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_hermes_invalid_request", status=TaskStatus.RUNNING.value)

    result = execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        timeout_seconds=0,
        transport=_success_transport,
    )

    stored_task = load_task(task.task_id, root=tmp_path)
    assert stored_task is not None
    assert stored_task.status == TaskStatus.BLOCKED.value
    assert result["result"]["status"] == "invalid_request"
    assert result["result"]["failure_category"] == "invalid_request_contract"
    assert "invalid_timeout_seconds" in result["request_validation"]["findings"]


def test_hermes_summary_surfaces_contract_fields(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_hermes_summary", status=TaskStatus.RUNNING.value)

    execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "hermes_summary_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Hermes summary candidate",
            "summary": "candidate summary",
            "content": "candidate body",
            "citations": [{"kind": "web", "ref": "doc:123"}],
            "proposed_next_actions": [{"kind": "review", "label": "Request review"}],
            "token_usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        },
    )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    export_payload = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]

    assert status["hermes_summary"]["hermes_request_count"] == 1
    assert status["hermes_summary"]["hermes_failure_category_counts"] == {}
    assert status["hermes_summary"]["latest_hermes_result"]["citations"][0]["kind"] == "web"
    assert snapshot["hermes_summary"]["latest_hermes_result"]["proposed_next_actions"][0]["kind"] == "review"
    assert export_payload["hermes_summary"]["latest_hermes_request"]["return_format"] == "candidate_artifact"
    assert handoff["hermes_summary"]["latest_hermes_result"]["token_usage"]["total_tokens"] == 30


def test_hermes_respects_control_state(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_hermes_control", status=TaskStatus.RUNNING.value)
    apply_control_action(
        action="pause",
        actor="operator",
        lane="controls",
        scope_type=ControlScopeType.GLOBAL.value,
        scope_id="global",
        reason="operator pause",
        root=tmp_path,
    )

    with raises(ValueError, match="Control state forbids task progress"):
        execute_hermes_task(
            task_id=task.task_id,
            actor="tester",
            lane="hermes",
            root=tmp_path,
            transport=_success_transport,
        )


if __name__ == "__main__":
    def _run_tmp(test_fn, name: str) -> None:
        path = Path(name)
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
        try:
            test_fn(path)
        finally:
            shutil.rmtree(path, ignore_errors=True)

    _run_tmp(test_hermes_success_updates_pending_review_and_writes_candidate, "tmp_test_hermes_review")
    _run_tmp(test_hermes_success_updates_pending_approval_checkpoint, "tmp_test_hermes_approval")
    _run_tmp(test_hermes_malformed_response_blocks_task, "tmp_test_hermes_malformed")
    _run_tmp(test_hermes_invalid_request_contract_blocks_before_dispatch, "tmp_test_hermes_invalid_request")
    _run_tmp(test_hermes_summary_surfaces_contract_fields, "tmp_test_hermes_summary")
    _run_tmp(test_hermes_respects_control_state, "tmp_test_hermes_control")
