import json
import subprocess
import sys
from pathlib import Path

from runtime.core.approval_store import request_approval
from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import latest_review_for_task, record_review_verdict, request_review
from runtime.core.task_store import create_task
from runtime.integrations.hermes_adapter import execute_hermes_task
from scripts.operator_checkpoint_action_pack import with_action_pack_provenance


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


def _seed_review(root: Path, *, task_id: str) -> dict:
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
    return _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(root),
        ]
    )


def test_explain_identifies_policy_skip(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_explain_policy", approval_required=True)
    request_approval(
        task_id=task.task_id,
        approval_type=task.task_type,
        requested_by="tester",
        requested_reviewer="operator",
        lane="review",
        summary="Pending approval for explain policy",
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
    action_id = action_pack["pack"]["pending_approval_commands"][0]["action_ids"]["approve"]
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_queue_runner.py"),
            "--root",
            str(tmp_path),
            "--category",
            "pending_approval",
        ]
    )

    explained = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_explain.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_id,
        ]
    )

    assert explained["outcome"] == "policy_skip"


def test_explain_identifies_idempotency_skip(tmp_path: Path):
    action_pack = _seed_review(tmp_path, task_id="task_explain_idempotency")
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
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_queue_runner.py"),
            "--root",
            str(tmp_path),
            "--category",
            "artifact_followup",
        ]
    )

    explained = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_explain.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_id,
        ]
    )

    assert explained["outcome"] == "idempotency_skip"


def test_explain_identifies_stale_skip(tmp_path: Path):
    action_pack = _seed_review(tmp_path, task_id="task_explain_stale")
    action_id = action_pack["pack"]["pending_review_commands"][0]["action_ids"]["approve"]
    review = latest_review_for_task("task_explain_stale", root=tmp_path)
    assert review is not None
    record_review_verdict(
        review_id=review.review_id,
        verdict="approved",
        actor="operator",
        lane="review",
        reason="Make explain action stale",
        root=tmp_path,
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_queue_runner.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            "task_explain_stale",
            "--category",
            "pending_review",
        ]
    )

    explained = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_explain.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_id,
        ]
    )

    assert explained["outcome"] == "stale_action_skip"


def test_explain_identifies_pinned_pack_validation_failure(tmp_path: Path):
    action_pack = _seed_review(tmp_path, task_id="task_explain_pinned_failure")
    pack_path = Path(action_pack["json_path"])
    payload = json.loads(pack_path.read_text(encoding="utf-8"))
    payload["generated_at"] = "2000-01-01T00:00:00+00:00"
    payload["recommended_ttl_seconds"] = 1
    payload["expires_at"] = "2000-01-01T00:00:01+00:00"
    payload = with_action_pack_provenance(payload)
    pack_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    action_id = action_pack["pack"]["pending_review_commands"][0]["action_ids"]["approve"]
    failure = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_id,
            "--action-pack-path",
            str(pack_path),
        ],
        expect_ok=False,
    )

    explained = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_explain.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_id,
            "--execution-id",
            failure["execution_record"]["execution_id"],
        ]
    )

    assert explained["outcome"] == "expired_pack"
