import json
import subprocess
import sys
from pathlib import Path

from runtime.core.approval_store import request_approval
from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import request_review
from runtime.core.task_store import create_task
from runtime.integrations.hermes_adapter import execute_hermes_task


ROOT = Path(__file__).resolve().parents[1]


def _make_task(root: Path, *, task_id: str, review_required: bool = False, approval_required: bool = False) -> TaskRecord:
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
            review_required=review_required,
            approval_required=approval_required,
        ),
        root=root,
    )


def _run_json(cmd: list[str], *, expect_ok: bool = True) -> dict:
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if expect_ok and completed.returncode != 0:
        raise AssertionError(
            f"Command failed ({completed.returncode}): {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def test_action_list_filters_work(tmp_path: Path):
    review_task = _make_task(tmp_path, task_id="task_list_actions_review", review_required=True)
    execute_hermes_task(
        task_id=review_task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "list_actions_review_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "List actions review",
            "summary": "list actions review summary",
            "content": "candidate body",
        },
    )
    request_review(
        task_id=review_task.task_id,
        reviewer_role="operator",
        requested_by="tester",
        lane="review",
        summary="Pending review for list actions",
        root=tmp_path,
    )
    approval_task = _make_task(tmp_path, task_id="task_list_actions_approval", approval_required=True)
    request_approval(
        task_id=approval_task.task_id,
        approval_type=approval_task.task_type,
        requested_by="tester",
        requested_reviewer="operator",
        lane="review",
        summary="Pending approval for list actions",
        root=tmp_path,
    )
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(tmp_path)])

    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_list_actions.py"),
            "--root",
            str(tmp_path),
            "--category",
            "pending_review",
            "--only-safe",
        ]
    )
    assert payload["rows"]
    assert all(row["category"] == "pending_review" for row in payload["rows"])
    assert all(row["safe_to_run_now"] for row in payload["rows"])


def test_task_list_filters_work(tmp_path: Path):
    review_task = _make_task(tmp_path, task_id="task_list_tasks_review", review_required=True)
    execute_hermes_task(
        task_id=review_task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "list_tasks_review_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "List tasks review",
            "summary": "list tasks review summary",
            "content": "candidate body",
        },
    )
    request_review(
        task_id=review_task.task_id,
        reviewer_role="operator",
        requested_by="tester",
        lane="review",
        summary="Pending review for list tasks",
        root=tmp_path,
    )
    approval_task = _make_task(tmp_path, task_id="task_list_tasks_approval", approval_required=True)
    request_approval(
        task_id=approval_task.task_id,
        approval_type=approval_task.task_type,
        requested_by="tester",
        requested_reviewer="operator",
        lane="review",
        summary="Pending approval for list tasks",
        root=tmp_path,
    )

    review_payload = _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_list_tasks.py"), "--root", str(tmp_path), "--needs-review"]
    )
    approval_payload = _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_list_tasks.py"), "--root", str(tmp_path), "--needs-approval"]
    )
    assert any(row["task_id"] == review_task.task_id for row in review_payload["rows"])
    assert any(row["task_id"] == approval_task.task_id for row in approval_payload["rows"])


def test_run_list_filters_work(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_list_runs_review", review_required=True)
    execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "list_runs_review_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "List runs review",
            "summary": "list runs review summary",
            "content": "candidate body",
        },
    )
    request_review(
        task_id=task.task_id,
        reviewer_role="operator",
        requested_by="tester",
        lane="review",
        summary="Pending review for list runs",
        root=tmp_path,
    )
    pack = _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(tmp_path)])
    action_id = pack["pack"]["pending_review_commands"][0]["action_ids"]["approve"]
    _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_action_executor.py"), "--root", str(tmp_path), "--action-id", action_id, "--dry-run"]
    )

    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_list_runs.py"),
            "--root",
            str(tmp_path),
            "--kind",
            "execution",
            "--task-id",
            task.task_id,
        ]
    )
    assert payload["rows"]
    assert payload["rows"][0]["kind"] == "execution"
    assert payload["rows"][0]["task_id"] == task.task_id
