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


def test_reply_plan_parses_compact_strings_and_preview_classifies_steps(tmp_path: Path):
    _seed_review_task(tmp_path, task_id="task_reply_plan")
    inbox = _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(tmp_path)])
    code = inbox["pack"]["items"][0]["default_reply_code"]

    plan = _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_reply_plan.py"), "--root", str(tmp_path), "--reply", f"{code} X1"]
    )
    preview = _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_reply_preview.py"), "--root", str(tmp_path), "--reply", f"{code} X1"]
    )

    assert plan["normalized_tokens"] == [code, "X1"]
    assert len(plan["steps"]) == 2
    assert preview["steps"][0]["operation_kind"] == "execute_action"
    assert preview["steps"][1]["operation_kind"] == "explain"


def test_unknown_reply_tokens_fail_cleanly(tmp_path: Path):
    _seed_review_task(tmp_path, task_id="task_reply_unknown")

    payload = _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_reply_plan.py"), "--root", str(tmp_path), "--reply", "Z9"],
        expect_ok=False,
    )

    assert payload["ok"] is False
    assert payload["unknown_tokens"] == ["Z9"]


def test_apply_reply_can_dry_run_and_execute_safe_review_action(tmp_path: Path):
    task = _seed_review_task(tmp_path, task_id="task_reply_apply_safe")
    inbox = _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(tmp_path)])
    code = inbox["pack"]["items"][0]["default_reply_code"]

    dry_run = _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_apply_reply.py"), "--root", str(tmp_path), "--reply", code, "--dry-run"]
    )
    execute = _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_apply_reply.py"), "--root", str(tmp_path), "--reply", code]
    )
    review = latest_review_for_task(task.task_id, root=tmp_path)

    assert dry_run["succeeded_count"] == 1
    assert execute["succeeded_count"] == 1
    assert review is not None
    assert review.status == "approved"


def test_apply_reply_refuses_stale_items_cleanly_and_shortlist_is_file_backed(tmp_path: Path):
    task = _seed_review_task(tmp_path, task_id="task_reply_stale")
    inbox = _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(tmp_path)])
    code = inbox["pack"]["items"][0]["default_reply_code"]
    review = latest_review_for_task(task.task_id, root=tmp_path)
    assert review is not None
    record_review_verdict(
        review_id=review.review_id,
        verdict="approved",
        actor="tester",
        lane="review",
        reason="make stale for reply apply",
        root=tmp_path,
    )

    payload = _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_apply_reply.py"), "--root", str(tmp_path), "--reply", code],
        expect_ok=False,
    )
    shortlist = _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_shortlist.py"), "--root", str(tmp_path)])

    assert payload["ok"] is False
    assert payload["per_step_results"][0]["status"] in {"skipped_stale", "plan_blocked", "failed_execution"}
    assert Path(shortlist["json_path"]).exists()
    assert Path(shortlist["markdown_path"]).exists()
