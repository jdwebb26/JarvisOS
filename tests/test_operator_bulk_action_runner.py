import json
import subprocess
import sys
from pathlib import Path

from runtime.core.approval_store import request_approval
from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import latest_review_for_task, request_review
from runtime.core.task_store import create_task
from runtime.integrations.hermes_adapter import execute_hermes_task


ROOT = Path(__file__).resolve().parents[1]


def _make_task(root: Path, *, task_id: str, review_required: bool = False) -> TaskRecord:
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
            f"Command failed ({completed.returncode}): {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def _latest_bulk_run(root: Path) -> dict:
    rows = sorted((root / "state" / "operator_bulk_runs").glob("*.json"))
    assert rows
    return json.loads(rows[-1].read_text(encoding="utf-8"))


def _seed_review_task(root: Path, *, task_id: str) -> TaskRecord:
    task = _make_task(root, task_id=task_id, review_required=True)
    execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=root,
        transport=lambda _request: {
            "run_id": f"{task_id}_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": f"{task_id} candidate",
            "summary": f"{task_id} summary",
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


def test_bulk_runner_dry_run(tmp_path: Path):
    task = _seed_review_task(tmp_path, task_id="task_bulk_dry_run")

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_bulk_action_runner.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--category",
            "pending_review",
            "--action-id-prefix",
            "review:approve",
            "--dry-run",
        ]
    )
    bulk_run = _latest_bulk_run(tmp_path)
    review = latest_review_for_task(task.task_id, root=tmp_path)

    assert result["ok"] is True
    assert result["attempted_count"] == 1
    assert result["executed_actions"][0]["dry_run"] is True
    assert bulk_run["pack_validation_status"] == "valid"
    assert review is not None
    assert review.status == "pending"


def test_bulk_runner_stop_on_failure(tmp_path: Path):
    task = _seed_review_task(tmp_path, task_id="task_bulk_stop_on_failure")
    action_pack = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    artifact_id = next(
        row["artifact_id"] for row in action_pack["pack"]["artifact_followup_commands"] if row["task_id"] == task.task_id
    )
    artifact_path = tmp_path / "state" / "artifacts" / f"{artifact_id}.json"
    artifact_path.unlink()

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_bulk_action_runner.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--category",
            "artifact_followup",
            "--action-id-prefix",
            "artifact:",
            "--limit",
            "2",
        ],
        expect_ok=False,
    )

    assert result["ok"] is False
    assert result["attempted_count"] == 1
    assert result["failed_count"] == 1
    assert result["stop_reason"].startswith("failed_action:")


def test_bulk_runner_continue_on_failure(tmp_path: Path):
    task = _seed_review_task(tmp_path, task_id="task_bulk_continue")
    second = _seed_review_task(tmp_path, task_id="task_bulk_continue_second")
    action_pack = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    artifact_id = next(
        row["artifact_id"] for row in action_pack["pack"]["artifact_followup_commands"] if row["task_id"] == task.task_id
    )
    artifact_path = tmp_path / "state" / "artifacts" / f"{artifact_id}.json"
    artifact_path.unlink()

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_bulk_action_runner.py"),
            "--root",
            str(tmp_path),
            "--action-id-prefix",
            "artifact:",
            "--continue-on-failure",
        ],
        expect_ok=False,
    )

    assert second.task_id
    assert result["ok"] is False
    assert result["attempted_count"] >= 2
    assert result["failed_count"] >= 1
    assert result["succeeded_count"] >= 1


def test_bulk_runner_force_with_prior_successful_action(tmp_path: Path):
    task = _seed_review_task(tmp_path, task_id="task_bulk_force")
    action_pack = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    inspect_action = action_pack["pack"]["artifact_followup_commands"][0]["action_ids"]["inspect_artifact_json"]
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            inspect_action,
        ]
    )

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_bulk_action_runner.py"),
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
    assert result["attempted_count"] >= 1
    assert result["failed_count"] == 0


def test_bulk_runner_policy_and_idempotency_skips_can_coexist(tmp_path: Path):
    review_task = _seed_review_task(tmp_path, task_id="task_bulk_policy_review")
    _seed_review_task(tmp_path, task_id="task_bulk_policy_second")
    approval_task = _make_task(tmp_path, task_id="task_bulk_policy_approval")
    request_approval(
        task_id=approval_task.task_id,
        approval_type=approval_task.task_type,
        requested_by="tester",
        requested_reviewer="operator",
        lane="review",
        summary="Pending approval for bulk policy test",
        root=tmp_path,
    )
    action_pack = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    inspect_action = next(
        row["action_ids"]["inspect_artifact_json"]
        for row in action_pack["pack"]["artifact_followup_commands"]
        if row["task_id"] == review_task.task_id
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            inspect_action,
        ]
    )

    result = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_bulk_action_runner.py"),
            "--root",
            str(tmp_path),
            "--action-id-prefix",
            "",
            "--limit",
            "10",
        ]
    )
    bulk_run = _latest_bulk_run(tmp_path)

    assert approval_task.task_id
    assert result["ok"] is True
    assert any(row.get("skip_kind") == "policy" for row in bulk_run["skipped_actions"])
    assert any(row.get("skip_kind") == "idempotency" for row in bulk_run["skipped_actions"])
