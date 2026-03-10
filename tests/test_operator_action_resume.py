import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import latest_review_for_task, load_review, record_review_verdict, request_review
from runtime.core.task_store import create_task
from runtime.evals.trace_store import replay_trace_to_eval
from runtime.integrations.hermes_adapter import execute_hermes_task, load_hermes_result
from runtime.memory.governance import load_memory_candidate
from runtime.ralph.consolidator import execute_consolidation
from scripts.operator_checkpoint_action_pack import with_action_pack_provenance
from scripts.operator_action_ledger import (
    latest_action_by_category,
    latest_failed_action_for_task,
    latest_successful_action_for_task,
)


ROOT = Path(__file__).resolve().parents[1]


def _make_task(
    root: Path,
    *,
    task_id: str,
    review_required: bool = False,
) -> TaskRecord:
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
            f"Command failed ({completed.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def _expire_pack(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["generated_at"] = "2000-01-01T00:00:00+00:00"
    payload["recommended_ttl_seconds"] = 1
    payload["expires_at"] = "2000-01-01T00:00:01+00:00"
    payload = with_action_pack_provenance(payload)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _seed_memory_action_pack(root: Path, *, task_id: str, review_required: bool) -> dict:
    task = _make_task(root, task_id=task_id, review_required=review_required)
    hermes = execute_hermes_task(
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
    stored_result = load_hermes_result(hermes["result"]["result_id"], root=root)
    replay_trace_to_eval(
        trace_id=stored_result["trace_id"],
        actor="tester",
        lane="eval",
        evaluator_kind="replay_check",
        objective="Seed eval",
        root=root,
    )
    execute_consolidation(task_id=task.task_id, actor="tester", lane="ralph", root=root)
    return _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(root),
        ]
    )


def test_resume_latest_failed_action(tmp_path: Path):
    action_pack = _seed_memory_action_pack(tmp_path, task_id="task_resume_failed", review_required=True)
    action_id = action_pack["pack"]["memory_decision_commands"][0]["action_ids"]["promote"]

    failed = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_id,
        ],
        expect_ok=False,
    )
    failed_record = failed["execution_record"]

    review = latest_review_for_task("task_resume_failed", root=tmp_path)
    assert review is not None
    record_review_verdict(
        review_id=review.review_id,
        verdict="approved",
        actor="operator",
        lane="review",
        reason="Clear blocker for resume test",
        root=tmp_path,
    )

    resumed = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_resume_action.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            "task_resume_failed",
            "--category",
            "memory_candidate",
        ]
    )
    promoted_id = resumed["stdout_payload"]["result"]["memory_candidate"]["memory_candidate_id"]
    promoted = load_memory_candidate(promoted_id, root=tmp_path)

    assert resumed["ok"] is True
    assert resumed["resumed_from_execution_id"] == failed_record["execution_id"]
    assert promoted is not None
    assert promoted.decision_status == "promoted"


def test_resume_from_dry_run_action(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_resume_dry_run", review_required=True)
    execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "dry_resume_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Dry resume candidate",
            "summary": "dry resume summary",
            "content": "candidate body",
        },
    )
    request_review(
        task_id=task.task_id,
        reviewer_role="operator",
        requested_by="tester",
        lane="review",
        summary="Dry-run review request",
        root=tmp_path,
    )
    action_pack = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    action_id = action_pack["pack"]["pending_review_commands"][0]["action_ids"]["approve"]
    dry_run = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_id,
            "--dry-run",
        ]
    )

    resumed = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_resume_action.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--category",
            "pending_review",
        ]
    )
    review = latest_review_for_task(task.task_id, root=tmp_path)

    assert dry_run["execution_record"]["dry_run"] is True
    assert resumed["ok"] is True
    assert resumed["resumed_from_execution_id"] == dry_run["execution_record"]["execution_id"]
    assert resumed["execution_record"]["source_action_pack_id"] == dry_run["execution_record"]["source_action_pack_id"]
    assert resumed["execution_record"]["source_action_pack_fingerprint"] == dry_run["execution_record"]["source_action_pack_fingerprint"]
    assert resumed["action_pack_validation"]["status"] == "valid"
    assert review is not None
    assert review.status == "approved"


def test_recent_action_queries(tmp_path: Path):
    action_pack = _seed_memory_action_pack(tmp_path, task_id="task_resume_queries", review_required=True)
    memory_action_id = action_pack["pack"]["memory_decision_commands"][0]["action_ids"]["promote"]
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            memory_action_id,
        ],
        expect_ok=False,
    )

    review = latest_review_for_task("task_resume_queries", root=tmp_path)
    assert review is not None
    record_review_verdict(
        review_id=review.review_id,
        verdict="approved",
        actor="operator",
        lane="review",
        reason="Approve review for query test",
        root=tmp_path,
    )
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_resume_action.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            "task_resume_queries",
            "--category",
            "memory_candidate",
        ]
    )

    latest_failed = latest_failed_action_for_task(tmp_path, "task_resume_queries")
    latest_success = latest_successful_action_for_task(tmp_path, "task_resume_queries")
    latest_memory = latest_action_by_category(tmp_path, "memory_candidate")

    assert latest_failed is not None
    assert latest_failed["failure"] is True
    assert latest_success is not None
    assert latest_success["success"] is True
    assert latest_memory is not None
    assert (latest_memory.get("selected_action") or {}).get("category") == "memory_candidate"


def test_resume_respects_duplicate_protection_without_force(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_resume_duplicate_guard")
    execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "resume_duplicate_guard_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Resume duplicate guard candidate",
            "summary": "resume duplicate guard summary",
            "content": "candidate body",
        },
    )
    action_pack = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    action_id = action_pack["pack"]["artifact_followup_commands"][0]["action_ids"]["inspect_artifact_json"]
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_id,
        ]
    )

    resumed = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_resume_action.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--category",
            "artifact_followup",
            "--replay-success",
        ],
        expect_ok=False,
    )

    assert resumed["ok"] is False
    assert resumed["failure"]["kind"] == "already_executed"


def test_resume_allows_force_replay_of_successful_action(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_resume_force_guard")
    execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "resume_force_guard_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Resume force guard candidate",
            "summary": "resume force guard summary",
            "content": "candidate body",
        },
    )
    action_pack = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    action_id = action_pack["pack"]["artifact_followup_commands"][0]["action_ids"]["inspect_artifact_json"]
    _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_id,
        ]
    )

    resumed = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_resume_action.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--category",
            "artifact_followup",
            "--replay-success",
            "--force",
        ]
    )

    assert resumed["ok"] is True
    assert resumed["selected_action"]["action_id"] == action_id


def test_resume_respects_stale_action_guard(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_resume_stale_guard", review_required=True)
    execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "resume_stale_guard_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Resume stale guard candidate",
            "summary": "resume stale guard summary",
            "content": "candidate body",
        },
    )
    request_review(
        task_id=task.task_id,
        reviewer_role="operator",
        requested_by="tester",
        lane="review",
        summary="Resume stale guard review request",
        root=tmp_path,
    )
    action_pack = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    action_id = action_pack["pack"]["pending_review_commands"][0]["action_ids"]["approve"]
    dry_run = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_id,
            "--dry-run",
        ]
    )
    review = load_review((dry_run["selected_action"] or {})["target_id"], root=tmp_path)
    assert review is not None
    record_review_verdict(
        review_id=review.review_id,
        verdict="approved",
        actor="operator",
        lane="review",
        reason="Make dry-run action stale before resume",
        root=tmp_path,
    )

    resumed = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_resume_action.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--category",
            "pending_review",
        ],
        expect_ok=False,
    )

    assert resumed["ok"] is False
    assert resumed["failure"]["kind"] == "stale_action"


def test_resume_respects_expired_pinned_pack_provenance(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_resume_pinned_pack", review_required=True)
    execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: {
            "run_id": "resume_pinned_pack_run",
            "family": "qwen3.5",
            "model_name": "Qwen3.5-35B-A3B",
            "title": "Resume pinned pack candidate",
            "summary": "resume pinned pack summary",
            "content": "candidate body",
        },
    )
    request_review(
        task_id=task.task_id,
        reviewer_role="operator",
        requested_by="tester",
        lane="review",
        summary="Resume pinned pack review request",
        root=tmp_path,
    )
    action_pack = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"),
            "--root",
            str(tmp_path),
        ]
    )
    pack_path = Path(action_pack["json_path"])
    short_lived_payload = json.loads(pack_path.read_text(encoding="utf-8"))
    generated_at = datetime.now(timezone.utc)
    short_lived_payload["generated_at"] = generated_at.isoformat()
    short_lived_payload["recommended_ttl_seconds"] = 1
    short_lived_payload["expires_at"] = (generated_at + timedelta(seconds=1)).isoformat()
    short_lived_payload = with_action_pack_provenance(short_lived_payload)
    pack_path.write_text(json.dumps(short_lived_payload, indent=2) + "\n", encoding="utf-8")
    action_id = action_pack["pack"]["pending_review_commands"][0]["action_ids"]["approve"]
    dry_run = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_action_executor.py"),
            "--root",
            str(tmp_path),
            "--action-id",
            action_id,
            "--action-pack-path",
            str(pack_path),
            "--dry-run",
        ]
    )
    time.sleep(1.2)

    resumed = _run_json(
        [
            sys.executable,
            str(ROOT / "scripts" / "operator_resume_action.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            task.task_id,
            "--category",
            "pending_review",
        ],
        expect_ok=False,
    )

    assert dry_run["execution_record"]["source_action_pack_requested_explicit"] is True
    assert resumed["ok"] is False
    assert resumed["failure"]["kind"] == "expired_pack"
