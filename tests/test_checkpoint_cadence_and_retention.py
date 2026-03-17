"""Tests for compare-history preservation, retention/pruning, and cadence wrapper."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.review_store import request_review
from runtime.core.task_store import create_task
from runtime.integrations.hermes_adapter import execute_hermes_task
from scripts.operator_triage_support import (
    build_control_plane_checkpoint,
    compare_control_plane_checkpoints,
    prune_compare_history,
    prune_control_plane_checkpoints,
    operator_control_plane_checkpoints_dir,
    _compare_history_paths,
)


ROOT = Path(__file__).resolve().parents[1]


def _run_json(cmd: list[str], *, expect_ok: bool = True) -> dict:
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if expect_ok and completed.returncode != 0:
        raise AssertionError(
            f"Command failed ({completed.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
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


def _prepare(root: Path, task_id: str) -> None:
    _seed_review_task(root, task_id=task_id)
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_checkpoint_action_pack.py"), "--root", str(root)])
    _run_json([sys.executable, str(ROOT / "scripts" / "operator_decision_inbox.py"), "--root", str(root)])


# ---------------------------------------------------------------------------
# Compare-history preservation
# ---------------------------------------------------------------------------


def test_compare_writes_timestamped_history(tmp_path: Path):
    _prepare(tmp_path, "task_hist_1")
    build_control_plane_checkpoint(tmp_path, limit=5)
    build_control_plane_checkpoint(tmp_path, limit=5)

    compare_control_plane_checkpoints(tmp_path)

    # Latest must exist
    latest = tmp_path / "state" / "logs" / "operator_compare_control_plane_checkpoints_latest.json"
    assert latest.exists()

    # At least one timestamped history file must also exist
    history = _compare_history_paths(tmp_path)
    assert len(history) >= 1
    # History content should match latest
    assert json.loads(latest.read_text()) == json.loads(history[-1].read_text())


def test_multiple_compares_accumulate_history(tmp_path: Path):
    _prepare(tmp_path, "task_hist_2")
    build_control_plane_checkpoint(tmp_path, limit=5)
    build_control_plane_checkpoint(tmp_path, limit=5)

    compare_control_plane_checkpoints(tmp_path)
    build_control_plane_checkpoint(tmp_path, limit=5)
    compare_control_plane_checkpoints(tmp_path)

    history = _compare_history_paths(tmp_path)
    assert len(history) >= 2


# ---------------------------------------------------------------------------
# Retention / pruning — checkpoints
# ---------------------------------------------------------------------------


def test_prune_checkpoints_keeps_recent(tmp_path: Path):
    _prepare(tmp_path, "task_prune_ckpt")
    for _ in range(5):
        build_control_plane_checkpoint(tmp_path, limit=5)

    result = prune_control_plane_checkpoints(tmp_path, keep=3)
    assert result["total_before"] == 5
    assert result["deleted_count"] == 2
    assert result["kept"] == 3

    remaining = list(operator_control_plane_checkpoints_dir(tmp_path).glob("*.json"))
    assert len(remaining) == 3


def test_prune_checkpoints_noop_when_under_limit(tmp_path: Path):
    _prepare(tmp_path, "task_prune_noop")
    build_control_plane_checkpoint(tmp_path, limit=5)

    result = prune_control_plane_checkpoints(tmp_path, keep=10)
    assert result["deleted_count"] == 0


# ---------------------------------------------------------------------------
# Retention / pruning — compare history
# ---------------------------------------------------------------------------


def test_prune_compare_history_keeps_recent(tmp_path: Path):
    _prepare(tmp_path, "task_prune_cmp")
    for _ in range(5):
        build_control_plane_checkpoint(tmp_path, limit=5)
        compare_control_plane_checkpoints(tmp_path)

    before = _compare_history_paths(tmp_path)
    assert len(before) >= 5

    result = prune_compare_history(tmp_path, keep=2)
    assert result["deleted_count"] >= 3
    after = _compare_history_paths(tmp_path)
    assert len(after) == 2


def test_prune_compare_history_noop_when_under_limit(tmp_path: Path):
    _prepare(tmp_path, "task_prune_cmp_noop")
    build_control_plane_checkpoint(tmp_path, limit=5)
    build_control_plane_checkpoint(tmp_path, limit=5)
    compare_control_plane_checkpoints(tmp_path)

    result = prune_compare_history(tmp_path, keep=10)
    assert result["deleted_count"] == 0


# ---------------------------------------------------------------------------
# Cadence wrapper (subprocess)
# ---------------------------------------------------------------------------


def test_cadence_script_runs_end_to_end(tmp_path: Path):
    _prepare(tmp_path, "task_cadence")
    # Seed at least one prior checkpoint so compare has something to diff against
    build_control_plane_checkpoint(tmp_path, limit=5)

    payload = _run_json([
        sys.executable,
        str(ROOT / "scripts" / "operator_checkpoint_cadence.py"),
        "--root", str(tmp_path),
        "--keep-checkpoints", "10",
        "--keep-compare", "10",
    ])

    assert payload["ok"] is True
    assert payload["checkpoint_id"].startswith("opcpckpt_")
    assert payload["compare"]["current"] is not None
    assert payload["pruned_checkpoints"]["deleted_count"] == 0
    assert payload["pruned_compare"]["deleted_count"] == 0
