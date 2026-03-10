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


def test_publish_outbound_packet_and_list_view(tmp_path: Path):
    _seed_review_task(tmp_path, task_id="task_bridge_outbound")
    published = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_publish_outbound_packet.py"),
            "--root",
            str(tmp_path),
        ]
    )
    listed = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_list_outbound_packets.py"),
            "--root",
            str(tmp_path),
        ]
    )

    packet = published["packet"]
    assert Path(published["json_path"]).exists()
    assert Path(published["markdown_path"]).exists()
    assert packet["reply_ready"] in {True, False}
    assert listed["count"] >= 1
    assert listed["rows"][0]["outbound_packet_id"] == packet["outbound_packet_id"]


def test_import_reply_message_classifies_and_enqueues(tmp_path: Path):
    _seed_review_task(tmp_path, task_id="task_bridge_import")
    valid = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_import_reply_message.py"),
            "--root",
            str(tmp_path),
            "--raw-text",
            "A1",
            "--source-message-id",
            "msg_import_valid",
            "--apply",
            "--dry-run",
        ]
    )
    ignored = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_import_reply_message.py"),
            "--root",
            str(tmp_path),
            "--raw-text",
            "hello there",
            "--source-message-id",
            "msg_import_ignored",
        ]
    )
    invalid = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_import_reply_message.py"),
            "--root",
            str(tmp_path),
            "--raw-text",
            "Z9",
            "--source-message-id",
            "msg_import_invalid",
        ]
    )
    listed = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_list_imported_reply_messages.py"),
            "--root",
            str(tmp_path),
        ]
    )

    assert valid["classification"] == "importable_compact_reply"
    assert valid["imported"] is True
    assert Path(valid["reply_message_path"]).exists()
    assert ignored["classification"] == "ignored_non_reply"
    assert ignored["imported"] is False
    assert invalid["classification"] == "invalid_reply"
    assert invalid["imported"] is False
    assert listed["count"] >= 3


def test_bridge_cycle_imports_folder_rows_and_updates_reporting(tmp_path: Path):
    _seed_review_task(tmp_path, task_id="task_bridge_cycle")
    inbound_dir = tmp_path / "state" / "operator_gateway_inbound_messages"
    inbound_dir.mkdir(parents=True, exist_ok=True)
    (inbound_dir / "msg_bridge_01.json").write_text(
        json.dumps(
            {
                "source_kind": "gateway",
                "source_lane": "operator",
                "source_channel": "phone",
                "source_message_id": "msg_bridge_01",
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

    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_bridge_cycle.py"),
            "--root",
            str(tmp_path),
            "--import-from-folder",
            "--apply",
            "--dry-run",
            "--continue-on-failure",
        ]
    )
    handoff = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_handoff_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )["pack"]
    status_payload = _run_json([sys.executable, str(ROOT / "runtime" / "core" / "status.py"), "--root", str(tmp_path)])
    export_payload = _run_json([sys.executable, str(ROOT / "runtime" / "dashboard" / "state_export.py"), "--root", str(tmp_path)])

    assert payload["bridge_cycle"]["imported_count"] == 1
    assert payload["bridge_cycle"]["reply_transport_cycle_id"]
    assert handoff["gateway_bridge_summary"]["bridge_ready"] in {True, False}
    assert handoff["latest_outbound_packet"] is not None
    assert handoff["latest_imported_reply_message"] is not None
    assert handoff["latest_bridge_cycle"] is not None
    assert status_payload["operator_control_plane"]["gateway_bridge_summary"]["latest_import_classification"] == "importable_compact_reply"
    assert export_payload["counts"]["operator_bridge_cycles"] >= 1
