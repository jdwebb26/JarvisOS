import json
import subprocess
import sys
from pathlib import Path

from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import request_review
from runtime.core.task_store import create_task
from runtime.integrations.hermes_adapter import execute_hermes_task
from scripts.operator_checkpoint_action_pack import with_action_pack_provenance


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


def _expire_current_pack(root: Path) -> None:
    path = root / "state" / "logs" / "operator_checkpoint_action_pack.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["generated_at"] = "2000-01-01T00:00:00+00:00"
    payload["recommended_ttl_seconds"] = 1
    payload["expires_at"] = "2000-01-01T00:00:01+00:00"
    payload = with_action_pack_provenance(payload)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _prepare_reply_ready(root: Path, *, task_id: str) -> None:
    _seed_review_task(root, task_id=task_id)
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(root)])
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(root)])


def _make_transport_cycle(root: Path, *, source_message_id: str) -> None:
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_enqueue_reply_message.py"),
            "--root",
            str(root),
            "--raw-text",
            "A1",
            "--source-message-id",
            source_message_id,
            "--apply",
            "--dry-run",
        ]
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_transport_cycle.py"),
            "--root",
            str(root),
            "--apply",
            "--dry-run",
            "--continue-on-failure",
        ]
    )


def _make_bridge_cycle(root: Path, *, source_message_id: str) -> None:
    inbound_dir = root / "state" / "operator_gateway_inbound_messages"
    inbound_dir.mkdir(parents=True, exist_ok=True)
    (inbound_dir / f"{source_message_id}.json").write_text(
        json.dumps(
            {
                "source_kind": "gateway",
                "source_lane": "operator",
                "source_channel": "phone",
                "source_message_id": source_message_id,
                "source_user": "operator",
                "raw_text": "A1",
                "apply": True,
                "dry_run": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_bridge_cycle.py"),
            "--root",
            str(root),
            "--import-from-folder",
            "--apply",
            "--dry-run",
            "--continue-on-failure",
        ]
    )


def test_operator_doctor_healthy_and_list_reports(tmp_path: Path):
    _prepare_reply_ready(tmp_path, task_id="task_doctor_healthy")
    doctor = _run_json([sys.executable, str(ROOT / "scripts" / "operator_doctor.py"), "--root", str(tmp_path)])
    listed = _run_json([sys.executable, str(ROOT / "scripts" / "operator_list_doctor_reports.py"), "--root", str(tmp_path)])

    assert doctor["report"]["health_status"] == "healthy"
    assert doctor["report"]["issues"][0]["issue_code"] == "healthy"
    assert Path(doctor["json_path"]).exists()
    assert Path(doctor["markdown_path"]).exists()
    assert listed["count"] >= 1


def test_operator_doctor_detects_pack_expired_and_stale_inbox(tmp_path: Path):
    _prepare_reply_ready(tmp_path, task_id="task_doctor_pack")
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(tmp_path)])
    stale_inbox = _run_json([sys.executable, str(ROOT / "scripts" / "operator_doctor.py"), "--root", str(tmp_path)])
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_explain_doctor_issue.py"), "--root", str(tmp_path), "--issue-code", "inbox_stale"])

    _expire_current_pack(tmp_path)
    expired = _run_json([sys.executable, str(ROOT / "scripts" / "operator_doctor.py"), "--root", str(tmp_path)])
    plan = _run_json([sys.executable, str(ROOT / "scripts" / "operator_plan_remediation.py"), "--root", str(tmp_path)])

    stale_codes = {row["issue_code"] for row in stale_inbox["report"]["issues"]}
    expired_codes = {row["issue_code"] for row in expired["report"]["issues"]}
    assert "inbox_stale" in stale_codes
    assert "pack_expired" in expired_codes
    assert plan["plan"]["steps"]


def test_operator_doctor_detects_pending_inbound_and_gateway_imports(tmp_path: Path):
    _prepare_reply_ready(tmp_path, task_id="task_doctor_pending")
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_enqueue_reply_message.py"),
            "--root",
            str(tmp_path),
            "--raw-text",
            "A1",
            "--source-message-id",
            "doctor_pending_reply",
            "--apply",
            "--dry-run",
        ]
    )
    inbound_dir = tmp_path / "state" / "operator_gateway_inbound_messages"
    inbound_dir.mkdir(parents=True, exist_ok=True)
    (inbound_dir / "doctor_gateway_pending.json").write_text(
        json.dumps(
            {
                "source_kind": "gateway",
                "source_lane": "operator",
                "source_channel": "phone",
                "source_message_id": "doctor_gateway_pending",
                "source_user": "operator",
                "raw_text": "A1",
                "apply": True,
                "dry_run": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    doctor = _run_json([sys.executable, str(ROOT / "scripts" / "operator_doctor.py"), "--root", str(tmp_path)])
    codes = {row["issue_code"] for row in doctor["report"]["issues"]}
    assert "pending_inbound_replies" in codes
    assert "pending_gateway_imports" in codes


def test_operator_doctor_detects_replay_and_bridge_replay_blocked_and_reporting(tmp_path: Path):
    _prepare_reply_ready(tmp_path, task_id="task_doctor_replay")
    _make_transport_cycle(tmp_path, source_message_id="doctor_transport_cycle")
    _make_bridge_cycle(tmp_path, source_message_id="doctor_bridge_cycle")
    _expire_current_pack(tmp_path)

    doctor = _run_json([sys.executable, str(ROOT / "scripts" / "operator_doctor.py"), "--root", str(tmp_path)])
    codes = {row["issue_code"] for row in doctor["report"]["issues"]}
    assert "replay_blocked" in codes
    assert "bridge_replay_blocked" in codes

    _run_json([sys.executable, str(ROOT / "scripts" / "operator_plan_remediation.py"), "--root", str(tmp_path)])
    handoff = _run_json([sys.executable, str(ROOT / "scripts" / "operator_handoff_pack.py"), "--root", str(tmp_path)])["pack"]
    status_payload = _run_json([sys.executable, str(ROOT / "runtime" / "core" / "status.py"), "--root", str(tmp_path)])
    export_payload = _run_json([sys.executable, str(ROOT / "runtime" / "dashboard" / "state_export.py"), "--root", str(tmp_path)])

    assert handoff["latest_doctor_report"] is not None
    assert handoff["doctor_summary"]["active_issue_count"] >= 1
    assert handoff["latest_remediation_plan"] is not None
    assert status_payload["operator_control_plane"]["doctor_summary"]["health_status"] in {"healthy", "degraded", "blocked", "unknown"}
    assert export_payload["doctor_summary"]["latest_doctor_report_id"] is not None
