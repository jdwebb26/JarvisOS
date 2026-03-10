import json
import subprocess
import sys
from pathlib import Path

from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import latest_review_for_task, record_review_verdict, request_review
from runtime.core.task_store import create_task
from runtime.integrations.hermes_adapter import execute_hermes_task


ROOT = Path(__file__).resolve().parents[1]


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
            review_required=True,
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


def _seed_review_task(root: Path, *, task_id: str) -> tuple[TaskRecord, dict]:
    task = _make_task(root, task_id=task_id)
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
    pack = _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(root)])
    return task, pack


def test_task_intervention_dry_run_works(tmp_path: Path):
    task, _ = _seed_review_task(tmp_path, task_id="task_intervene_dry")

    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_task_intervene.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--dry-run",
        ]
    )

    assert payload["ok"] is True
    assert payload["intervention_record"]["dry_run"] is True
    assert payload["intervention_record"]["execution_record_id"]
    assert payload["suggested_action_ids"]


def test_task_intervention_real_execution_path_for_safe_review_action(tmp_path: Path):
    task, _ = _seed_review_task(tmp_path, task_id="task_intervene_real")

    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_task_intervene.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
        ]
    )
    review = latest_review_for_task(task.task_id, root=tmp_path)

    assert payload["ok"] is True
    assert payload["execution"]["stdout_payload"]["ack"]["kind"] == "review_recorded_ack"
    assert review is not None
    assert review.status == "approved"


def test_task_intervention_refuses_stale_or_missing_action(tmp_path: Path):
    task, pack = _seed_review_task(tmp_path, task_id="task_intervene_stale")
    review = latest_review_for_task(task.task_id, root=tmp_path)
    assert review is not None
    record_review_verdict(
        review_id=review.review_id,
        verdict="approved",
        actor="tester",
        lane="review",
        reason="make stale for intervention",
        root=tmp_path,
    )

    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_task_intervene.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--action-pack-path",
            pack["json_path"],
        ],
        expect_ok=False,
    )

    assert payload["ok"] is False
    assert payload["intervention_record"]["selected_action_id"]
    assert payload["blockers_preventing_safe_execution"]
    assert any("no longer pending" in blocker for blocker in payload["blockers_preventing_safe_execution"])
