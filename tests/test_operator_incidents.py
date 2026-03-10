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


def test_operator_incident_healthy_path(tmp_path: Path):
    _prepare_reply_ready(tmp_path, task_id="task_incident_healthy")
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_doctor.py"), "--root", str(tmp_path)])
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_control_plane.py"), "--root", str(tmp_path)])

    detected = _run_json([sys.executable, str(ROOT / "scripts" / "operator_detect_incidents.py"), "--root", str(tmp_path)])
    listed = _run_json([sys.executable, str(ROOT / "scripts" / "operator_list_incident_reports.py"), "--root", str(tmp_path)])
    explained = _run_json([sys.executable, str(ROOT / "scripts" / "operator_explain_incident_report.py"), "--root", str(tmp_path)])

    assert Path(detected["report_path"]).exists()
    assert Path(detected["snapshot_path"]).exists()
    assert detected["report"]["incident_code"] == "control_plane_healthy"
    assert listed["count"] >= 1
    assert explained["incident_report"]["incident_report_id"] == detected["report"]["incident_report_id"]
    assert explained["incident_snapshot"]["latest_checkpoint_id"] is not None


def test_operator_incident_detects_worsened_checkpoint_state(tmp_path: Path):
    _prepare_reply_ready(tmp_path, task_id="task_incident_worse")
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_doctor.py"), "--root", str(tmp_path)])
    first = _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_control_plane.py"), "--root", str(tmp_path)])

    _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(tmp_path)])
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_doctor.py"), "--root", str(tmp_path)])
    second = _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_control_plane.py"), "--root", str(tmp_path)])
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_compare_control_plane_checkpoints.py"),
            "--root",
            str(tmp_path),
            "--checkpoint-id",
            second["checkpoint"]["control_plane_checkpoint_id"],
            "--other-checkpoint-id",
            first["checkpoint"]["control_plane_checkpoint_id"],
        ]
    )

    detected = _run_json([sys.executable, str(ROOT / "scripts" / "operator_detect_incidents.py"), "--root", str(tmp_path)])

    assert detected["report"]["incident_code"] in {"checkpoint_worsened", "blocked_health_regression", "repeated_degraded_state"}
    assert detected["report"]["severity"] in {"medium", "high"}
    assert detected["snapshot"]["checkpoint_compare"]["active_issue_count_delta"] >= 1


def test_operator_incident_reporting_exposure(tmp_path: Path):
    _prepare_reply_ready(tmp_path, task_id="task_incident_reporting")
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_doctor.py"), "--root", str(tmp_path)])
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_control_plane.py"), "--root", str(tmp_path)])
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_detect_incidents.py"), "--root", str(tmp_path)])

    handoff = _run_json([sys.executable, str(ROOT / "scripts" / "operator_handoff_pack.py"), "--root", str(tmp_path)])["pack"]
    status_payload = _run_json([sys.executable, str(ROOT / "runtime" / "core" / "status.py"), "--root", str(tmp_path)])
    export_payload = _run_json([sys.executable, str(ROOT / "runtime" / "dashboard" / "state_export.py"), "--root", str(tmp_path)])
    snapshot_payload = _run_json([sys.executable, str(ROOT / "runtime" / "dashboard" / "operator_snapshot.py"), "--root", str(tmp_path)])

    assert handoff["latest_incident_report"] is not None
    assert handoff["incident_summary"]["operator_incident_report_count"] >= 1
    assert status_payload["operator_control_plane"]["latest_incident_report"] is not None
    assert status_payload["operator_control_plane"]["incident_summary"]["latest_incident_code"] is not None
    assert export_payload["counts"]["operator_incident_reports"] >= 1
    assert export_payload["incident_summary"]["operator_incident_report_count"] >= 1
    assert snapshot_payload["latest_incident_report"] is not None
    assert snapshot_payload["incident_summary"]["operator_incident_report_count"] >= 1
