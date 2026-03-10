import json
import subprocess
import sys
from pathlib import Path

from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import latest_review_for_task, request_review
from runtime.core.task_store import create_task
from runtime.evals.trace_store import replay_trace_to_eval
from runtime.integrations.hermes_adapter import execute_hermes_task, load_hermes_result
from runtime.ralph.consolidator import execute_consolidation


ROOT = Path(__file__).resolve().parents[1]


def _make_task(
    root: Path,
    *,
    task_id: str,
    review_required: bool = False,
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


def _latest_queue_run(root: Path) -> dict:
    rows = sorted((root / "state" / "operator_queue_runs").glob("*.json"))
    assert rows
    return json.loads(rows[-1].read_text(encoding="utf-8"))


def _seed_review_action(root: Path, *, task_id: str) -> TaskRecord:
    task = _make_task(root, task_id=task_id, review_required=True)
    execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=root,
        transport=lambda _request: {
            "run_id": f"{task_id}_review_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": f"{task_id} review candidate",
            "summary": f"{task_id} review summary",
            "content": "candidate body",
        },
    )
    request_review(
        task_id=task.task_id,
        reviewer_role="operator",
        requested_by="tester",
        lane="review",
        summary=f"Pending review for {task_id}",
        root=root,
    )
    return task


def _seed_failing_memory_action(root: Path, *, task_id: str) -> TaskRecord:
    task = _make_task(root, task_id=task_id, review_required=True)
    hermes = execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=root,
        transport=lambda _request: {
            "run_id": f"{task_id}_memory_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": f"{task_id} memory candidate",
            "summary": f"{task_id} memory summary",
            "content": "candidate body",
        },
    )
    stored_result = load_hermes_result(hermes["result"]["result_id"], root=root)
    replay_trace_to_eval(
        trace_id=stored_result["trace_id"],
        actor="tester",
        lane="eval",
        evaluator_kind="replay_check",
        objective="Seed eval",
        root=root,
    )
    execute_consolidation(task_id=task.task_id, actor="tester", lane="ralph", root=root)
    return task


def test_queue_runner_dry_run(tmp_path: Path):
    task = _seed_review_action(tmp_path, task_id="task_queue_dry")

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_queue_runner.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--category",
            "pending_review",
            "--dry-run",
        ]
    )
    queue_run = _latest_queue_run(tmp_path)
    review = latest_review_for_task(task.task_id, root=tmp_path)
    handoff = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_handoff_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )

    assert result["ok"] is True
    assert result["attempted_count"] == 1
    assert result["succeeded_count"] == 1
    assert result["failed_count"] == 0
    assert queue_run["filters"]["dry_run"] is True
    assert review is not None
    assert review.status == "pending"
    assert handoff["pack"]["recent_operator_queue_runs"]


def test_queue_runner_stops_on_failure(tmp_path: Path):
    _seed_failing_memory_action(tmp_path, task_id="task_queue_fail_a")
    _seed_failing_memory_action(tmp_path, task_id="task_queue_fail_b")

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_queue_runner.py"),
            "--root",
            str(tmp_path),
            "--category",
            "memory_candidate",
            "--max-actions",
            "2",
        ],
        expect_ok=False,
    )

    assert result["ok"] is False
    assert result["attempted_count"] == 1
    assert result["failed_count"] == 1
    assert result["stopped_on_action_id"]


def test_queue_runner_continue_on_failure(tmp_path: Path):
    _seed_failing_memory_action(tmp_path, task_id="task_queue_continue_a")
    _seed_failing_memory_action(tmp_path, task_id="task_queue_continue_b")

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_queue_runner.py"),
            "--root",
            str(tmp_path),
            "--category",
            "memory_candidate",
            "--max-actions",
            "2",
            "--continue-on-failure",
        ],
        expect_ok=False,
    )

    assert result["ok"] is False
    assert result["attempted_count"] == 2
    assert result["failed_count"] == 2


def test_queue_runner_filters_by_task_and_category(tmp_path: Path):
    task_a = _seed_review_action(tmp_path, task_id="task_queue_filter_a")
    task_b = _seed_review_action(tmp_path, task_id="task_queue_filter_b")

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_queue_runner.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task_a.task_id,
            "--category",
            "pending_review",
        ]
    )
    review_a = latest_review_for_task(task_a.task_id, root=tmp_path)
    review_b = latest_review_for_task(task_b.task_id, root=tmp_path)

    assert result["ok"] is True
    assert result["attempted_count"] == 1
    assert len(result["executed_actions"]) == 1
    assert result["executed_actions"][0]["task_id"] == task_a.task_id
    assert review_a is not None
    assert review_a.status == "approved"
    assert review_b is not None
    assert review_b.status == "pending"
