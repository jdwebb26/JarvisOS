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


def test_control_plane_checkpoint_create_list_and_explain(tmp_path: Path):
    _prepare_reply_ready(tmp_path, task_id="task_control_checkpoint")

    created = _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_control_plane.py"), "--root", str(tmp_path)])
    listed = _run_json([sys.executable, str(ROOT / "scripts" / "operator_list_control_plane_checkpoints.py"), "--root", str(tmp_path)])
    explained = _run_json([sys.executable, str(ROOT / "scripts" / "operator_explain_control_plane_checkpoint.py"), "--root", str(tmp_path)])

    assert Path(created["path"]).exists()
    assert created["checkpoint"]["control_plane_checkpoint_id"]
    assert listed["count"] >= 1
    assert explained["checkpoint"]["control_plane_checkpoint_id"] == created["checkpoint"]["control_plane_checkpoint_id"]
    assert explained["details"]["current_action_pack"]["status"] == "valid"


def test_control_plane_checkpoint_compare_detects_meaningful_deltas(tmp_path: Path):
    _prepare_reply_ready(tmp_path, task_id="task_control_compare")
    first = _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_control_plane.py"), "--root", str(tmp_path)])

    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_enqueue_reply_message.py"),
            "--root",
            str(tmp_path),
            "--raw-text",
            "A1",
            "--source-message-id",
            "control_checkpoint_pending",
            "--apply",
            "--dry-run",
        ]
    )
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(tmp_path)])
    second = _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_control_plane.py"), "--root", str(tmp_path)])
    compared = _run_json(
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

    assert compared["current_checkpoint_id"] == second["checkpoint"]["control_plane_checkpoint_id"]
    assert compared["other_checkpoint_id"] == first["checkpoint"]["control_plane_checkpoint_id"]
    assert compared["pending_inbound_reply_count_delta"] == 1
    assert compared["pack_id_before"] != compared["pack_id_after"]
    assert Path(tmp_path / "state" / "logs" / "operator_compare_control_plane_checkpoints_latest.json").exists()


def test_control_plane_checkpoint_reporting_and_recovery_summary_fix(tmp_path: Path):
    _prepare_stale_inbox(tmp_path, task_id="task_control_reporting")
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_recovery_cycle.py"), "--root", str(tmp_path), "--live"])
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_control_plane.py"), "--root", str(tmp_path)])
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_compare_control_plane_checkpoints.py"), "--root", str(tmp_path)])

    handoff = _run_json([sys.executable, str(ROOT / "scripts" / "operator_handoff_pack.py"), "--root", str(tmp_path)])["pack"]
    status_payload = _run_json([sys.executable, str(ROOT / "runtime" / "core" / "status.py"), "--root", str(tmp_path)])
    export_payload = _run_json([sys.executable, str(ROOT / "runtime" / "dashboard" / "state_export.py"), "--root", str(tmp_path)])
    snapshot_payload = _run_json([sys.executable, str(ROOT / "runtime" / "dashboard" / "operator_snapshot.py"), "--root", str(tmp_path)])

    assert handoff["latest_control_plane_checkpoint"] is not None
    assert handoff["latest_compare_control_plane_checkpoints"] is not None
    assert handoff["control_plane_checkpoint_summary"]["control_plane_checkpoint_count"] >= 1
    assert handoff["recovery_cycle_summary"]["latest_recovery_cycle_active_issue_count_before"] is not None
    assert status_payload["operator_control_plane"]["latest_control_plane_checkpoint"] is not None
    assert status_payload["operator_control_plane"]["latest_compare_control_plane_checkpoints"] is not None
    assert status_payload["operator_control_plane"]["recovery_cycle_summary"]["latest_recovery_cycle_active_issue_count_before"] is not None
    assert export_payload["counts"]["operator_control_plane_checkpoints"] >= 1
    assert export_payload["control_plane_checkpoint_summary"]["control_plane_checkpoint_count"] >= 1
    assert export_payload["recovery_cycle_summary"]["latest_recovery_cycle_active_issue_count_before"] is not None
    assert snapshot_payload["latest_control_plane_checkpoint"] is not None
    assert snapshot_payload["control_plane_checkpoint_summary"]["control_plane_checkpoint_count"] >= 1
