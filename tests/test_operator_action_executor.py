import json
import subprocess
import sys
from pathlib import Path

from runtime.core.approval_store import request_approval
from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import request_review
from runtime.core.review_store import latest_review_for_task
from runtime.core.task_store import create_task
from runtime.evals.trace_store import replay_trace_to_eval
from runtime.integrations.hermes_adapter import execute_hermes_task, load_hermes_result
from runtime.memory.governance import list_memory_candidates_for_task, load_memory_candidate
from runtime.ralph.consolidator import execute_consolidation


ROOT = Path(__file__).resolve().parents[1]


def _make_task(
    root: Path,
    *,
    task_id: str,
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
            f"Command failed ({completed.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def test_operator_action_executor_runs_review_action(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_action_executor_review", review_required=True)
    execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "review_executor_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Review executor candidate",
            "summary": "candidate for action executor",
            "content": "candidate body",
        },
    )
    request_review(
        task_id=task.task_id,
        reviewer_role="operator",
        requested_by="tester",
        lane="review",
        summary="Review pending for action executor",
        root=tmp_path,
    )
    review = latest_review_for_task(task.task_id, root=tmp_path)
    assert review is not None

    action_pack = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    action_id = action_pack["pack"]["pending_review_commands"][0]["action_ids"]["approve"]

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_id,
        ]
    )

    assert result["ok"] is True
    assert result["selected_action"]["action_id"] == action_id
    assert result["stdout_payload"]["ack"]["kind"] == "review_recorded_ack"


def test_operator_action_executor_runs_memory_action(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_action_executor_memory")
    hermes = execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "memory_executor_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Memory executor candidate",
            "summary": "candidate for memory action executor",
            "content": "candidate body",
        },
    )
    stored_result = load_hermes_result(hermes["result"]["result_id"], root=tmp_path)
    replay_trace_to_eval(
        trace_id=stored_result["trace_id"],
        actor="tester",
        lane="eval",
        evaluator_kind="replay_check",
        objective="Seed eval for memory executor",
        root=tmp_path,
    )
    execute_consolidation(task_id=task.task_id, actor="tester", lane="ralph", root=tmp_path)

    action_pack = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    action_id = action_pack["pack"]["memory_decision_commands"][0]["action_ids"]["promote"]

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_id,
        ]
    )

    promoted_id = result["stdout_payload"]["result"]["memory_candidate"]["memory_candidate_id"]
    promoted = load_memory_candidate(promoted_id, root=tmp_path)

    assert result["ok"] is True
    assert result["stdout_payload"]["ack"]["kind"] == "memory_decision_ack"
    assert promoted is not None
    assert promoted.decision_status == "promoted"


def test_operator_action_executor_reports_unknown_action_id(tmp_path: Path):
    _make_task(tmp_path, task_id="task_action_executor_unknown")
    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            "review:approve:missing",
        ],
        expect_ok=False,
    )

    assert result["ok"] is False
    assert "not found" in result["error"]
