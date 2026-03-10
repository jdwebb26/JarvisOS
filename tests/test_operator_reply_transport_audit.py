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


def _make_cycle(root: Path, *, source_message_id: str, raw_text: str = "A1", apply: bool = True, preview: bool = False, dry_run: bool = True) -> dict:
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_enqueue_reply_message.py"),
            "--root",
            str(root),
            "--raw-text",
            raw_text,
            "--source-message-id",
            source_message_id,
            *(["--apply"] if apply else []),
            *(["--preview"] if preview else []),
            *(["--dry-run"] if dry_run else []),
        ]
    )
    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_transport_cycle.py"),
            "--root",
            str(root),
            *(["--apply"] if apply else []),
            *(["--preview"] if preview else []),
            *(["--dry-run"] if dry_run else []),
            "--continue-on-failure",
        ],
        expect_ok=raw_text != "Z9",
    )
    return payload["transport_cycle"]


def test_list_explain_compare_and_replay_reply_transport_cycles(tmp_path: Path):
    _seed_review_task(tmp_path, task_id="task_reply_transport_audit")
    cycle_one = _make_cycle(tmp_path, source_message_id="msg_cycle_a", apply=True, dry_run=True)
    cycle_two = _make_cycle(tmp_path, source_message_id="msg_cycle_b", apply=False, preview=True, dry_run=False)

    listed = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_list_reply_transport_cycles.py"),
            "--root",
            str(tmp_path),
            "--limit",
            "5",
        ]
    )
    explained = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_explain_reply_transport_cycle.py"),
            "--root",
            str(tmp_path),
            "--cycle-id",
            cycle_two["transport_cycle_id"],
        ]
    )
    compared = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_compare_reply_transport_cycles.py"),
            "--root",
            str(tmp_path),
            "--cycle-id",
            cycle_two["transport_cycle_id"],
            "--other-cycle-id",
            cycle_one["transport_cycle_id"],
        ]
    )
    replay_plan = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_replay_transport_cycle.py"),
            "--root",
            str(tmp_path),
            "--cycle-id",
            cycle_one["transport_cycle_id"],
            "--plan-only",
        ]
    )
    replay_dry_run = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_replay_transport_cycle.py"),
            "--root",
            str(tmp_path),
            "--cycle-id",
            cycle_one["transport_cycle_id"],
        ]
    )

    assert listed["count"] >= 2
    assert explained["cycle"]["transport_cycle_id"] == cycle_two["transport_cycle_id"]
    assert explained["replay_safety"]["replay_allowed"] is True
    assert compared["mode_changed"] is True
    assert Path(tmp_path / "state" / "logs" / "operator_compare_reply_transport_cycles_latest.json").exists()
    assert replay_plan["replay_plan"]["replay_safety"]["replay_mode"] == "apply_dry_run"
    assert replay_dry_run["replay"]["ok"] is True
    assert replay_dry_run["transport_cycle"]["transport_cycle"]["transport_cycle_id"]

    status_payload = _run_json([sys.executable, str(ROOT / "runtime" / "core" / "status.py"), "--root", str(tmp_path)])
    export_payload = _run_json([sys.executable, str(ROOT / "runtime" / "dashboard" / "state_export.py"), "--root", str(tmp_path)])
    assert status_payload["operator_control_plane"]["latest_reply_transport_replay"] is not None
    assert export_payload["reply_transport_summary"]["latest_reply_transport_replay_ok"] in {True, False, None}


def test_replay_blocks_when_current_pack_is_stale_or_original_cycle_is_invalid(tmp_path: Path):
    _seed_review_task(tmp_path, task_id="task_reply_transport_blocked")
    valid_cycle = _make_cycle(tmp_path, source_message_id="msg_cycle_valid", apply=True, dry_run=True)
    _expire_current_pack(tmp_path)
    stale_block = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_replay_transport_cycle.py"),
            "--root",
            str(tmp_path),
            "--cycle-id",
            valid_cycle["transport_cycle_id"],
            "--plan-only",
        ],
        expect_ok=False,
    )

    _seed_review_task(tmp_path, task_id="task_reply_transport_invalid")
    invalid_cycle = _make_cycle(tmp_path, source_message_id="msg_cycle_invalid", raw_text="Z9", apply=True, dry_run=True)
    invalid_block = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_replay_transport_cycle.py"),
            "--root",
            str(tmp_path),
            "--cycle-id",
            invalid_cycle["transport_cycle_id"],
            "--plan-only",
        ],
        expect_ok=False,
    )

    assert stale_block["replay"]["ok"] is False
    assert "status" in stale_block["replay_plan"]["replay_safety"]["reason"] or "pack" in stale_block["replay_plan"]["replay_safety"]["reason"].lower()
    assert invalid_block["replay"]["ok"] is False
    assert invalid_block["replay_plan"]["replay_safety"]["replay_allowed"] is False
