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


def _prepare_reply_ready(root: Path, *, task_id: str) -> None:
    _seed_review_task(root, task_id=task_id)
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(root)])
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(root)])


def _prepare_stale_inbox(root: Path, *, task_id: str) -> None:
    _prepare_reply_ready(root, task_id=task_id)
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(root)])


def test_recovery_cycle_dry_run_happy_path(tmp_path: Path):
    _prepare_stale_inbox(tmp_path, task_id="task_recovery_dry")

    payload = _run_json([sys.executable, str(ROOT / "scripts" / "operator_recovery_cycle.py"), "--root", str(tmp_path)])
    listed = _run_json([sys.executable, str(ROOT / "scripts" / "operator_list_recovery_cycles.py"), "--root", str(tmp_path)])
    explained = _run_json([sys.executable, str(ROOT / "scripts" / "operator_explain_recovery_cycle.py"), "--root", str(tmp_path)])
    handoff = _run_json([sys.executable, str(ROOT / "scripts" / "operator_handoff_pack.py"), "--root", str(tmp_path)])["pack"]
    status_payload = _run_json([sys.executable, str(ROOT / "runtime" / "core" / "status.py"), "--root", str(tmp_path)])
    export_payload = _run_json([sys.executable, str(ROOT / "runtime" / "dashboard" / "state_export.py"), "--root", str(tmp_path)])

    assert payload["ok"] is True
    assert payload["recovery_cycle"]["dry_run"] is True
    assert payload["recovery_cycle"]["remediation_plan_id"] is not None
    assert payload["recovery_cycle"]["remediation_run_id"] is not None
    assert listed["count"] >= 1
    assert explained["recovery_cycle"]["recovery_cycle_id"] == payload["recovery_cycle"]["recovery_cycle_id"]
    assert handoff["latest_recovery_cycle"] is not None
    assert "latest_recovery_cycle_id" in handoff["recovery_cycle_summary"]
    assert status_payload["operator_control_plane"]["latest_recovery_cycle"] is not None
    assert export_payload["counts"]["operator_recovery_cycles"] >= 1


def test_recovery_cycle_live_execution_reduces_issues(tmp_path: Path):
    _prepare_stale_inbox(tmp_path, task_id="task_recovery_live")

    payload = _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_recovery_cycle.py"), "--root", str(tmp_path), "--live"]
    )

    assert payload["ok"] is True
    assert payload["recovery_cycle"]["dry_run"] is False
    assert payload["recovery_cycle"]["remediation_run_id"] is not None
    assert payload["recovery_cycle"]["active_issue_count_after"] <= payload["recovery_cycle"]["active_issue_count_before"]


def test_recovery_cycle_healthy_noop_path(tmp_path: Path):
    _prepare_reply_ready(tmp_path, task_id="task_recovery_healthy")

    payload = _run_json([sys.executable, str(ROOT / "scripts" / "operator_recovery_cycle.py"), "--root", str(tmp_path)])

    assert payload["ok"] is True
    assert payload["recovery_cycle"]["health_status_before"] == "healthy"
    assert payload["recovery_cycle"]["active_issue_count_before"] == 0
    assert payload["recovery_cycle"]["remediation_run_id"] is None


def test_recovery_cycle_explain_and_single_step_reporting(tmp_path: Path):
    _prepare_stale_inbox(tmp_path, task_id="task_recovery_explain")
    payload = _run_json([sys.executable, str(ROOT / "scripts" / "operator_recovery_cycle.py"), "--root", str(tmp_path), "--live"])

    explain = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_explain_recovery_cycle.py"),
            "--root",
            str(tmp_path),
            "--recovery-cycle-id",
            payload["recovery_cycle"]["recovery_cycle_id"],
        ]
    )

    assert explain["ok"] is True
    assert explain["recovery_cycle"]["remediation_run_id"] == payload["recovery_cycle"]["remediation_run_id"]
    assert explain["doctor_report"]["doctor_report_id"] == payload["recovery_cycle"]["doctor_report_id"]
