import json
import subprocess
import sys
from pathlib import Path

from runtime.core.approval_store import request_approval
from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import request_review
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


def _expire_current_pack(root: Path) -> None:
    path = root / "state" / "logs" / "operator_checkpoint_action_pack.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["generated_at"] = "2000-01-01T00:00:00+00:00"
    payload["recommended_ttl_seconds"] = 1
    payload["expires_at"] = "2000-01-01T00:00:01+00:00"
    payload = with_action_pack_provenance(payload)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_safe_autofix_rebuilds_expired_current_pack(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_safe_autofix_review", review_required=True)
    execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "safe_autofix_review_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Safe autofix candidate",
            "summary": "safe autofix summary",
            "content": "candidate body",
        },
    )
    request_review(
        task_id=task.task_id,
        reviewer_role="operator",
        requested_by="tester",
        lane="review",
        summary="Pending review for safe autofix",
        root=tmp_path,
    )
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(tmp_path)])
    _expire_current_pack(tmp_path)

    payload = _run_json([sys.executable, str(ROOT / "scripts" / "operator_safe_autofix.py"), "--root", str(tmp_path)])

    assert payload["ok"] is True
    assert payload["rebuild_happened"] is True
    assert payload["autofix_record"]["current_pack_after"]["status"] == "valid"


def test_safe_autofix_does_not_approve_approvals_or_memory_or_shipping(tmp_path: Path):
    approval_task = _make_task(tmp_path, task_id="task_safe_autofix_approval", approval_required=True)
    request_approval(
        task_id=approval_task.task_id,
        approval_type=approval_task.task_type,
        requested_by="tester",
        requested_reviewer="operator",
        lane="review",
        summary="Pending approval for safe autofix",
        root=tmp_path,
    )
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(tmp_path)])

    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_safe_autofix.py"),
            "--root",
            str(tmp_path),
            "--execute-safe-review",
        ]
    )

    assert payload["ok"] is True
    assert payload["selected_safe_action_id"] is None
    assert payload["execution"] is None
