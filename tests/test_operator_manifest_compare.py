import json
import shutil
import subprocess
import sys
from pathlib import Path

from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import latest_review_for_task, record_review_verdict, request_review
from runtime.core.task_store import create_task
from runtime.integrations.hermes_adapter import execute_hermes_task


ROOT = Path(__file__).resolve().parents[1]


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


def _run_json(cmd: list[str], *, expect_ok: bool = True) -> dict:
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if expect_ok and completed.returncode != 0:
        raise AssertionError(
            f"Command failed ({completed.returncode}): {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def _seed_review_task(root: Path, *, task_id: str) -> tuple[TaskRecord, dict]:
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
    pack = _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(root)])
    return task, pack


def test_decision_manifest_includes_do_not_run_and_force_pinned_sections(tmp_path: Path):
    task, pack = _seed_review_task(tmp_path, task_id="task_manifest_sections")
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

    second_task, second_pack = _seed_review_task(tmp_path, task_id="task_manifest_stale")
    stale_pack_path = Path(second_pack["json_path"])
    stale_action = second_pack["pack"]["pending_review_commands"][-1]["action_ids"]["approve"]
    review = latest_review_for_task(second_task.task_id, root=tmp_path)
    assert review is not None
    record_review_verdict(
        review_id=review.review_id,
        verdict="approved",
        actor="tester",
        lane="review",
        reason="make stale for manifest",
        root=tmp_path,
    )
    _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_action_executor.py"), "--root", str(tmp_path), "--action-id", stale_action, "--action-pack-path", str(stale_pack_path)],
        expect_ok=False,
    )
    _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_action_executor.py"), "--root", str(tmp_path), "--action-id", stale_action, "--action-pack-path", str(stale_pack_path)],
        expect_ok=False,
    )

    broken_payload = json.loads(pack_path.read_text(encoding="utf-8"))
    broken_payload["operator_focus"] = "broken after pin"
    pack_path.write_text(json.dumps(broken_payload, indent=2) + "\n", encoding="utf-8")
    _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_action_executor.py"), "--root", str(tmp_path), "--action-id", approve_action, "--action-pack-path", str(pack_path)],
        expect_ok=False,
    )
    _run_json(
        [sys.executable, str(ROOT / "scripts" / "operator_action_executor.py"), "--root", str(tmp_path), "--action-id", approve_action, "--action-pack-path", str(pack_path)],
        expect_ok=False,
    )

    payload = _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_manifest.py"), "--root", str(tmp_path)])
    manifest = payload["pack"]
    assert manifest["do_not_run_items"]
    assert manifest["actions_requiring_force"]
    assert manifest["actions_requiring_pinned_pack"]


def test_pack_comparison_detects_added_and_removed_action_ids(tmp_path: Path):
    task, old_pack = _seed_review_task(tmp_path, task_id="task_compare_old")
    old_pack_copy = tmp_path / "old_pack.json"
    shutil.copyfile(old_pack["json_path"], old_pack_copy)
    review = latest_review_for_task(task.task_id, root=tmp_path)
    assert review is not None
    record_review_verdict(
        review_id=review.review_id,
        verdict="approved",
        actor="tester",
        lane="review",
        reason="remove old review action",
        root=tmp_path,
    )
    _seed_review_task(tmp_path, task_id="task_compare_new")

    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_compare_packs.py"),
            "--root",
            str(tmp_path),
            "--other-pack-path",
            str(old_pack_copy),
        ]
    )
    assert payload["action_ids_added"]
    assert payload["action_ids_removed"]


def test_triage_comparison_detects_blocker_and_recommendation_deltas(tmp_path: Path):
    _seed_review_task(tmp_path, task_id="task_compare_triage_first")
    first = _run_json([sys.executable, str(ROOT / "scripts" / "operator_triage_pack.py"), "--root", str(tmp_path)])
    first_copy = tmp_path / "triage_first.json"
    shutil.copyfile(first["json_path"], first_copy)

    second_task, _ = _seed_review_task(tmp_path, task_id="task_compare_triage_second")
    review = latest_review_for_task(second_task.task_id, root=tmp_path)
    assert review is not None
    record_review_verdict(
        review_id=review.review_id,
        verdict="approved",
        actor="tester",
        lane="review",
        reason="change triage blockers",
        root=tmp_path,
    )
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_triage_pack.py"), "--root", str(tmp_path)])

    payload = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_compare_triage.py"),
            "--root",
            str(tmp_path),
            "--other-triage-path",
            str(first_copy),
        ]
    )
    assert payload["blockers_added"] or payload["blockers_removed"] or payload["health_deltas"]
    assert "recommendations_added" in payload
