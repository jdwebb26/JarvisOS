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


def test_operator_reply_transport_cycle_runs_prompt_batch_and_ack(tmp_path: Path):
    _seed_review_task(tmp_path, task_id="task_transport_cycle")
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_enqueue_reply_message.py"),
            "--root",
            str(tmp_path),
            "--raw-text",
            "A1",
            "--source-message-id",
            "msg_cycle_1",
            "--apply",
            "--dry-run",
        ]
    )

    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_transport_cycle.py"),
            "--root",
            str(tmp_path),
            "--apply",
            "--dry-run",
            "--continue-on-failure",
        ]
    )

    cycle = payload["transport_cycle"]
    assert cycle["attempted_count"] == 1
    assert Path(payload["outbound_prompt"]["json_path"]).exists()
    assert Path(payload["reply_ack"]["json_path"]).exists()
    assert cycle["reply_ingress_run_id"]
    handoff = payload["handoff"]["pack"]
    assert handoff["reply_ingress_summary"]["pending_inbound_message_count"] == 0
    assert handoff["latest_reply_transport_cycle"] is not None
