import json
import shutil
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


def _seed_review_task(root: Path, *, task_id: str) -> TaskRecord:
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
    return task


def test_decision_inbox_emits_ranked_items_with_compact_reply_codes(tmp_path: Path):
    task = _seed_review_task(tmp_path, task_id="task_decision_inbox")

    payload = _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(tmp_path)])
    pack = payload["pack"]

    assert Path(payload["json_path"]).exists()
    assert Path(payload["markdown_path"]).exists()
    assert pack["items"]
    first = pack["items"][0]
    assert first["rank"] == 1
    assert first["task_id"] == task.task_id
    assert any(code.startswith("A1") or code == "A1" for code in first["allowed_reply_codes"])


def test_compare_inbox_detects_changed_items(tmp_path: Path):
    first_task = _seed_review_task(tmp_path, task_id="task_compare_inbox_first")
    first = _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(tmp_path)])
    first_copy = tmp_path / "inbox_first.json"
    shutil.copyfile(first["json_path"], first_copy)

    review = latest_review_for_task(first_task.task_id, root=tmp_path)
    assert review is not None
    record_review_verdict(
        review_id=review.review_id,
        verdict="approved",
        actor="tester",
        lane="review",
        reason="change inbox snapshot",
        root=tmp_path,
    )
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(tmp_path)])

    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_compare_inbox.py"),
            "--root",
            str(tmp_path),
            "--other-inbox-path",
            str(first_copy),
        ]
    )
    assert payload["items_removed"] or payload["became_stale_or_disappeared"]
