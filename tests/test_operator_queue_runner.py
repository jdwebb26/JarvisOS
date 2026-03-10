import json
import subprocess
import sys
from pathlib import Path

from runtime.core.approval_store import request_approval
from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import latest_review_for_task, record_review_verdict, request_review
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


def _seed_approval_action(root: Path, *, task_id: str) -> TaskRecord:
    task = _make_task(root, task_id=task_id, approval_required=True)
    request_approval(
        task_id=task.task_id,
        approval_type=task.task_type,
        requested_by="tester",
        requested_reviewer="operator",
        lane="review",
        summary=f"Pending approval for {task_id}",
        root=root,
    )
    return task


def _seed_memory_action(root: Path, *, task_id: str, review_required: bool) -> TaskRecord:
    task = _make_task(root, task_id=task_id, review_required=review_required, approval_required=not review_required)
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


def test_queue_runner_default_policy_skips_disallowed_actions(tmp_path: Path):
    _seed_approval_action(tmp_path, task_id="task_queue_policy_approval")

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_queue_runner.py"),
            "--root",
            str(tmp_path),
            "--category",
            "pending_approval",
        ]
    )
    queue_run = _latest_queue_run(tmp_path)

    assert result["ok"] is True
    assert result["attempted_count"] == 0
    assert result["skipped_count"] == 1
    assert result["skipped_actions"][0]["allowed"] is False
    assert "blocked by default policy" in result["skipped_actions"][0]["policy_reason"]
    assert queue_run["policy_summary"]["allow_approval"] is False


def test_queue_runner_dry_run_executes_only_as_dry_run(tmp_path: Path):
    task = _seed_review_action(tmp_path, task_id="task_queue_policy_dry_run")

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

    assert result["ok"] is True
    assert result["attempted_count"] == 1
    assert result["executed_actions"][0]["dry_run"] is True
    assert queue_run["filters"]["dry_run"] is True
    assert review is not None
    assert review.status == "pending"


def test_queue_runner_allow_approval_enables_approval_actions(tmp_path: Path):
    task = _seed_approval_action(tmp_path, task_id="task_queue_policy_allow_approval")

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_queue_runner.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--category",
            "pending_approval",
            "--allow-approval",
        ]
    )

    assert result["ok"] is True
    assert result["attempted_count"] == 1
    assert result["succeeded_count"] == 1
    assert result["executed_actions"][0]["allowed"] is True
    assert "explicit policy" in result["executed_actions"][0]["policy_reason"]


def test_queue_runner_stop_on_failure(tmp_path: Path):
    _seed_review_action(tmp_path, task_id="task_queue_policy_stop_review")
    _seed_memory_action(tmp_path, task_id="task_queue_policy_stop_memory", review_required=False)

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_queue_runner.py"),
            "--root",
            str(tmp_path),
            "--allow-category",
            "memory_candidate",
        ],
        expect_ok=False,
    )

    assert result["ok"] is False
    assert result["attempted_count"] == 2
    assert result["succeeded_count"] == 1
    assert result["failed_count"] == 1
    assert result["stopped_on_action_id"]


def test_queue_runner_deny_overrides_allow(tmp_path: Path):
    task = _seed_review_action(tmp_path, task_id="task_queue_policy_deny")

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
            "--allow-category",
            "pending_review",
            "--deny-category",
            "pending_review",
        ]
    )
    review = latest_review_for_task(task.task_id, root=tmp_path)

    assert result["ok"] is True
    assert result["attempted_count"] == 0
    assert result["skipped_count"] == 1
    assert "denied by explicit policy" in result["skipped_actions"][0]["policy_reason"]
    assert review is not None
    assert review.status == "pending"


def test_queue_runner_ledger_tracks_skipped_and_executed_actions(tmp_path: Path):
    review_task = _seed_review_action(tmp_path, task_id="task_queue_policy_review")
    _seed_memory_action(tmp_path, task_id="task_queue_policy_memory", review_required=False)

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_queue_runner.py"),
            "--root",
            str(tmp_path),
            "--continue-on-failure",
            "--allow-category",
            "memory_candidate",
        ],
        expect_ok=False,
    )
    queue_run = _latest_queue_run(tmp_path)
    handoff = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_handoff_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    review = latest_review_for_task(review_task.task_id, root=tmp_path)

    assert result["attempted_count"] >= 2
    assert result["succeeded_count"] >= 1
    assert result["failed_count"] >= 1
    assert queue_run["executed_actions"]
    assert queue_run["policy_summary"]["effective_allow_categories"]
    assert all("allowed" in row for row in queue_run["executed_actions"])
    assert queue_run["skipped_actions"]
    assert all(row["allowed"] is False for row in queue_run["skipped_actions"])
    assert all(row["skip_kind"] == "policy" for row in queue_run["skipped_actions"])
    assert handoff["pack"]["recent_operator_queue_runs"]
    assert handoff["pack"]["recent_operator_queue_runs"][0]["policy_summary"]
    assert review is not None
    assert review.status == "approved"


def test_queue_runner_skips_already_successful_action_ids_by_default(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_queue_idempotency_default")
    execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "queue_idempotency_default_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Queue idempotency default candidate",
            "summary": "queue idempotency default summary",
            "content": "candidate body",
        },
    )
    action_pack = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    action_id = action_pack["pack"]["artifact_followup_commands"][0]["action_ids"]["inspect_artifact_json"]
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_id,
        ]
    )

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_queue_runner.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--category",
            "artifact_followup",
        ]
    )
    queue_run = _latest_queue_run(tmp_path)
    handoff = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_handoff_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )

    assert result["ok"] is True
    assert result["attempted_count"] == 0
    assert result["succeeded_count"] == 0
    assert result["skipped_count"] == 1
    assert result["skipped_actions"][0]["skip_kind"] == "idempotency"
    assert result["skipped_actions"][0]["action_id"] == action_id
    assert queue_run["skipped_actions"][0]["skip_kind"] == "idempotency"
    assert handoff["pack"]["recent_operator_queue_runs"][0]["idempotency_skipped_count"] >= 1


def test_queue_runner_force_allows_rerun_of_successful_action_ids(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_queue_idempotency_force")
    execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "queue_idempotency_force_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Queue idempotency force candidate",
            "summary": "queue idempotency force summary",
            "content": "candidate body",
        },
    )
    action_pack = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    action_id = action_pack["pack"]["artifact_followup_commands"][0]["action_ids"]["inspect_artifact_json"]
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_id,
        ]
    )

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_queue_runner.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--category",
            "artifact_followup",
            "--force",
        ]
    )

    assert result["ok"] is True
    assert result["attempted_count"] == 1
    assert result["succeeded_count"] == 1
    assert result["skipped_count"] == 0
    assert result["executed_actions"][0]["action_id"] == action_id


def test_queue_runner_records_stale_skips_separately(tmp_path: Path):
    task = _seed_review_action(tmp_path, task_id="task_queue_stale_review")
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    review = latest_review_for_task(task.task_id, root=tmp_path)
    assert review is not None
    record_review_verdict(
        review_id=review.review_id,
        verdict="approved",
        actor="operator",
        lane="review",
        reason="Make queued review action stale before queue run",
        root=tmp_path,
    )

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
        ]
    )
    queue_run = _latest_queue_run(tmp_path)
    handoff = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_handoff_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )

    assert result["ok"] is True
    assert result["attempted_count"] == 0
    assert result["failed_count"] == 0
    assert result["skipped_count"] == 1
    assert result["skipped_actions"][0]["skip_kind"] == "stale_action"
    assert "no longer pending" in result["skipped_actions"][0]["skip_reason"]
    assert queue_run["skipped_actions"][0]["skip_kind"] == "stale_action"
    assert handoff["pack"]["recent_operator_queue_runs"][0]["stale_skipped_count"] >= 1
