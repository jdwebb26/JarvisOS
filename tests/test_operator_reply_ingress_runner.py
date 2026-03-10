import json
import subprocess
import sys
from pathlib import Path

from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import request_review
from runtime.core.task_store import create_task
from runtime.integrations.hermes_adapter import execute_hermes_task


ROOT = Path(__file__).resolve().parents[1]


def _run_json(cmd: list[str], *, expect_ok: bool = True) -> dict:
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if expect_ok and completed.returncode != 0:
        raise AssertionError(
            f"Command failed ({completed.returncode}): {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def _seed_review_task(root: Path, *, task_id: str) -> None:
    task = create_task(
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


def test_reply_ingress_runner_processes_mixed_batch(tmp_path: Path):
    _seed_review_task(tmp_path, task_id="task_reply_batch")
    inbox = _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(tmp_path)])
    code = inbox["pack"]["items"][0]["default_reply_code"]
    inbound = tmp_path / "state" / "operator_reply_messages"
    inbound.mkdir(parents=True, exist_ok=True)

    rows = [
        {"source_message_id": "msg_batch_ignore", "raw_text": "hello there", "source_kind": "file", "source_user": "operator"},
        {"source_message_id": "msg_batch_invalid", "raw_text": "Z9", "source_kind": "file", "source_user": "operator"},
        {"source_message_id": "msg_batch_apply", "raw_text": code, "source_kind": "file", "source_user": "operator", "apply": True, "dry_run": True},
        {"source_message_id": "msg_batch_apply", "raw_text": code, "source_kind": "file", "source_user": "operator", "apply": True, "dry_run": True},
    ]
    for index, row in enumerate(rows, start=1):
        (inbound / f"msg_{index:02d}.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")

    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_ingress_runner.py"),
            "--root",
            str(tmp_path),
            "--apply",
            "--dry-run",
            "--continue-on-failure",
        ],
        expect_ok=False,
    )

    run = payload["run"]
    processed_rows = sorted(inbound.glob("*.json"))
    assert run["attempted_count"] == 4
    assert run["ignored_count"] == 1
    assert run["invalid_count"] == 1
    assert run["applied_count"] == 1
    assert run["blocked_count"] >= 1
    assert run["processed_ingress_ids"]
    assert all(json.loads(path.read_text(encoding="utf-8")).get("processed_at") for path in processed_rows)
