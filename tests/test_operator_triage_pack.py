import json
import subprocess
import sys
from pathlib import Path

from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import latest_review_for_task, record_review_verdict, request_review
from runtime.core.task_store import create_task
from runtime.integrations.hermes_adapter import execute_hermes_task
from scripts.operator_checkpoint_action_pack import with_action_pack_provenance


ROOT = Path(__file__).resolve().parents[1]


def _make_task(root: Path, *, task_id: str, review_required: bool = False) -> TaskRecord:
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


def _seed_review_task(root: Path, *, task_id: str) -> tuple[TaskRecord, dict]:
    task = _make_task(root, task_id=task_id, review_required=True)
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
    pack = _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(root)]
    )
    return task, pack


def test_triage_pack_includes_blockers_and_recommendations(tmp_path: Path):
    task, _pack = _seed_review_task(tmp_path, task_id="task_triage_review")

    payload = _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_triage_pack.py"), "--root", str(tmp_path), "--limit", "5"]
    )

    pack = payload["pack"]
    assert Path(payload["json_path"]).exists()
    assert Path(payload["markdown_path"]).exists()
    assert pack["highest_priority_manual_blockers"]["pending_reviews"]
    assert any(row["task_id"] == task.task_id for row in pack["highest_priority_manual_blockers"]["pending_reviews"])
    assert pack["control_plane_health_summary"]["pending_review_count"] >= 1
    assert pack["recommended_operator_interventions"]
    assert any(row["category"] == "pending_review" for row in pack["recommended_operator_interventions"])


def test_triage_pack_detects_repeated_stale_idempotency_and_pinned_failures(tmp_path: Path):
    task, pack = _seed_review_task(tmp_path, task_id="task_triage_repeated")
    pack_path = Path(pack["json_path"])
    approve_action = pack["pack"]["pending_review_commands"][0]["action_ids"]["approve"]

    _run_json([sys.executable, str(ROOT / "scripts" / "operator_action_executor.py"), "--root", str(tmp_path), "--action-id", approve_action])
    _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_action_executor.py"), "--root", str(tmp_path), "--action-id", approve_action],
        expect_ok=False,
    )
    _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_action_executor.py"), "--root", str(tmp_path), "--action-id", approve_action],
        expect_ok=False,
    )

    second_task, second_pack = _seed_review_task(tmp_path, task_id="task_triage_stale")
    stale_pack_path = Path(second_pack["json_path"])
    stale_action = second_pack["pack"]["pending_review_commands"][-1]["action_ids"]["approve"]
    stale_review = latest_review_for_task(second_task.task_id, root=tmp_path)
    assert stale_review is not None
    record_review_verdict(
        review_id=stale_review.review_id,
        verdict="approved",
        actor="tester",
        lane="review",
        reason="make stale for triage",
        root=tmp_path,
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            stale_action,
            "--action-pack-path",
            str(stale_pack_path),
        ],
        expect_ok=False,
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            stale_action,
            "--action-pack-path",
            str(stale_pack_path),
        ],
        expect_ok=False,
    )

    broken_payload = json.loads(pack_path.read_text(encoding="utf-8"))
    broken_payload["operator_focus"] = "broken after pin"
    pack_path.write_text(json.dumps(broken_payload, indent=2) + "\n", encoding="utf-8")
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            approve_action,
            "--action-pack-path",
            str(pack_path),
        ],
        expect_ok=False,
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            approve_action,
            "--action-pack-path",
            str(pack_path),
        ],
        expect_ok=False,
    )

    triage = _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_triage_pack.py"), "--root", str(tmp_path), "--limit", "10"]
    )["pack"]

    repeated = triage["repeated_problem_detectors"]
    assert repeated["repeated_idempotency_skips"]
    assert repeated["repeated_stale_actions"]
    assert repeated["repeated_pinned_pack_validation_failures"]
