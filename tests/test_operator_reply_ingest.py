import json
import subprocess
import sys
from pathlib import Path

from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import latest_review_for_task, request_review
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


def _expire_or_mutate_pack(path: Path, *, expired: bool) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if expired:
        payload["generated_at"] = "2000-01-01T00:00:00+00:00"
        payload["recommended_ttl_seconds"] = 1
        payload["expires_at"] = "2000-01-01T00:00:01+00:00"
    else:
        payload["operator_focus"] = "mutated current pack for stale inbox test"
    payload = with_action_pack_provenance(payload)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_reply_ingest_ignores_non_reply_and_ledgers_it(tmp_path: Path):
    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_ingest.py"),
            "--root",
            str(tmp_path),
            "--reply",
            "hello operator",
            "--source-message-id",
            "msg_ignore_1",
        ]
    )

    assert payload["ok"] is True
    assert payload["result_kind"] == "ignored_non_reply"
    assert payload["ingress_record"]["ignored"] is True
    assert (tmp_path / "state" / "logs" / "operator_reply_ingress_latest.json").exists()


def test_reply_ingest_invalid_and_plan_apply_paths(tmp_path: Path):
    task = _seed_review_task(tmp_path, task_id="task_reply_ingest_paths")
    inbox = _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(tmp_path)])
    code = inbox["pack"]["items"][0]["default_reply_code"]

    invalid = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_ingest.py"),
            "--root",
            str(tmp_path),
            "--reply",
            "Z9",
            "--source-message-id",
            "msg_invalid_1",
        ],
        expect_ok=False,
    )
    planned = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_ingest.py"),
            "--root",
            str(tmp_path),
            "--reply",
            code,
            "--source-message-id",
            "msg_plan_1",
        ]
    )
    dry_run = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_ingest.py"),
            "--root",
            str(tmp_path),
            "--reply",
            code,
            "--source-message-id",
            "msg_dry_run_1",
            "--apply",
            "--dry-run",
        ]
    )
    review = latest_review_for_task(task.task_id, root=tmp_path)

    assert invalid["result_kind"] == "invalid_reply"
    assert invalid["result_record"]["payload"]["unknown_tokens"] == ["Z9"]
    assert planned["result_kind"] == "planned_only"
    assert planned["reply_plan"]["ok"] is True
    assert dry_run["result_kind"] == "applied"
    assert dry_run["apply_payload"]["succeeded_count"] == 1
    assert review is not None
    assert review.status == "pending"


def test_reply_ingest_apply_missing_and_stale_pack_and_duplicate_protection(tmp_path: Path):
    task = _seed_review_task(tmp_path, task_id="task_reply_ingest_apply")

    missing = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_ingest.py"),
            "--root",
            str(tmp_path),
            "--reply",
            "A1",
            "--source-message-id",
            "msg_missing_1",
        ],
        expect_ok=False,
    )
    inbox = _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(tmp_path)])
    code = inbox["pack"]["items"][0]["default_reply_code"]
    pack_path = tmp_path / "state" / "logs" / "operator_checkpoint_action_pack.json"
    _expire_or_mutate_pack(pack_path, expired=True)
    expired = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_ingest.py"),
            "--root",
            str(tmp_path),
            "--reply",
            code,
            "--source-message-id",
            "msg_expired_1",
        ],
        expect_ok=False,
    )

    _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(tmp_path)])
    inbox = _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(tmp_path)])
    code = inbox["pack"]["items"][0]["default_reply_code"]
    _expire_or_mutate_pack(pack_path, expired=False)
    stale = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_ingest.py"),
            "--root",
            str(tmp_path),
            "--reply",
            code,
            "--source-message-id",
            "msg_stale_1",
        ],
        expect_ok=False,
    )
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(tmp_path)])
    inbox = _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(tmp_path)])
    code = inbox["pack"]["items"][0]["default_reply_code"]
    apply_once = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_ingest.py"),
            "--root",
            str(tmp_path),
            "--reply",
            code,
            "--source-message-id",
            "msg_apply_once",
            "--apply",
        ]
    )
    duplicate = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_reply_ingest.py"),
            "--root",
            str(tmp_path),
            "--reply",
            code,
            "--source-message-id",
            "msg_apply_once",
            "--apply",
        ],
        expect_ok=False,
    )
    review = latest_review_for_task(task.task_id, root=tmp_path)

    assert missing["result_kind"] == "missing_inbox"
    assert expired["result_kind"] == "pack_refresh_required"
    assert stale["result_kind"] == "stale_inbox"
    assert apply_once["result_kind"] == "applied"
    assert duplicate["result_kind"] == "duplicate_message"
    assert review is not None
    assert review.status == "approved"

    status_payload = _run_json([sys.executable, str(ROOT / "runtime" / "core" / "status.py"), "--root", str(tmp_path)])
    export_payload = _run_json([sys.executable, str(ROOT / "runtime" / "dashboard" / "state_export.py"), "--root", str(tmp_path)])

    assert status_payload["operator_control_plane"]["reply_ingress_summary"]["duplicate_count"] >= 1
    assert export_payload["reply_summary"]["applied_ingress_count"] >= 1
