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


def _write_gateway_message(root: Path, *, name: str, raw_text: str, apply: bool = True, dry_run: bool = True) -> None:
    folder = root / "state" / "operator_gateway_inbound_messages"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(
        json.dumps(
            {
                "source_kind": "gateway",
                "source_lane": "operator",
                "source_channel": "phone",
                "source_message_id": name,
                "source_user": "operator",
                "raw_text": raw_text,
                "apply": apply,
                "dry_run": dry_run,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _make_bridge_cycle(root: Path, *, name: str, raw_text: str = "A1", apply: bool = True, dry_run: bool = True) -> dict:
    _seed_review_task(root, task_id=f"task_{name}")
    _write_gateway_message(root, name=name, raw_text=raw_text, apply=apply, dry_run=dry_run)
    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_bridge_cycle.py"),
            "--root",
            str(root),
            "--import-from-folder",
            *(["--apply"] if apply else []),
            *(["--dry-run"] if dry_run else []),
            "--continue-on-failure",
        ],
        expect_ok=True,
    )
    return payload["bridge_cycle"]


def test_list_explain_compare_and_replay_bridge_cycles(tmp_path: Path):
    cycle_one = _make_bridge_cycle(tmp_path, name="msg_bridge_a", raw_text="A1", apply=True, dry_run=True)
    cycle_two = _make_bridge_cycle(tmp_path, name="msg_bridge_b", raw_text="A1", apply=False, dry_run=False)

    listed = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_list_bridge_cycles.py"),
            "--root",
            str(tmp_path),
            "--limit",
            "5",
        ]
    )
    explained = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_explain_bridge_cycle.py"),
            "--root",
            str(tmp_path),
            "--cycle-id",
            cycle_two["bridge_cycle_id"],
        ]
    )
    compared = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_compare_bridge_cycles.py"),
            "--root",
            str(tmp_path),
            "--cycle-id",
            cycle_two["bridge_cycle_id"],
            "--other-cycle-id",
            cycle_one["bridge_cycle_id"],
        ]
    )
    replay_plan = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_replay_bridge_cycle.py"),
            "--root",
            str(tmp_path),
            "--cycle-id",
            cycle_one["bridge_cycle_id"],
            "--plan-only",
        ]
    )
    replay_dry_run = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_replay_bridge_cycle.py"),
            "--root",
            str(tmp_path),
            "--cycle-id",
            cycle_one["bridge_cycle_id"],
        ]
    )

    assert listed["count"] >= 2
    assert explained["cycle"]["bridge_cycle_id"] == cycle_two["bridge_cycle_id"]
    assert explained["replay_safety"]["replay_allowed"] is True
    assert compared["mode_changed"] is True
    assert Path(tmp_path / "state" / "logs" / "operator_compare_bridge_cycles_latest.json").exists()
    assert replay_plan["bridge_replay_plan"]["replay_safety"]["replay_mode"] == "apply_dry_run"
    assert replay_dry_run["bridge_replay"]["ok"] is True
    assert replay_dry_run["bridge_cycle"]["bridge_cycle"]["bridge_cycle_id"]

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
    assert handoff["latest_bridge_replay"] is not None
    assert "replay_allowed" in handoff["bridge_replay_summary"]
    assert handoff["latest_compare_bridge_cycles"] is not None
    assert status_payload["operator_control_plane"]["latest_bridge_replay"] is not None
    assert export_payload["reply_transport_summary"]["latest_bridge_replay_ok"] in {True, False, None}


def test_bridge_replay_blocks_when_pack_is_stale_or_cycle_has_no_importable_rows(tmp_path: Path):
    valid_cycle = _make_bridge_cycle(tmp_path, name="msg_bridge_valid", raw_text="A1", apply=True, dry_run=True)
    _expire_current_pack(tmp_path)
    stale_block = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_replay_bridge_cycle.py"),
            "--root",
            str(tmp_path),
            "--cycle-id",
            valid_cycle["bridge_cycle_id"],
            "--plan-only",
        ],
        expect_ok=False,
    )

    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    ignored_cycle = _make_bridge_cycle(tmp_path, name="msg_bridge_ignored", raw_text="hello there", apply=False, dry_run=False)
    blocked = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_replay_bridge_cycle.py"),
            "--root",
            str(tmp_path),
            "--cycle-id",
            ignored_cycle["bridge_cycle_id"],
            "--plan-only",
        ],
        expect_ok=False,
    )

    assert stale_block["bridge_replay"]["ok"] is False
    assert "pack" in stale_block["bridge_replay_plan"]["replay_safety"]["reason"].lower() or "ready" in stale_block["bridge_replay_plan"]["replay_safety"]["reason"].lower()
    assert blocked["bridge_replay"]["ok"] is False
    assert blocked["bridge_replay_plan"]["replay_safety"]["replay_allowed"] is False
