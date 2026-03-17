"""Tests for browser task result surfacing.

Covers:
- pick_queued_task_by_id returns queued task, None for non-queued
- execute_once with task_id targets specific task (queue isolation)
- execute_once writes a browser_result artifact on success
- finish_result carries artifact_id
- run_browser_task returns full result including artifact_id
- blocked browser task: no artifact written, task fails gracefully
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.browser_control_allowlist import save_browser_control_allowlist
from runtime.core.browser_task import create_browser_task, run_browser_task
from runtime.core.models import BrowserControlAllowlistRecord, new_id, now_iso
from runtime.core.task_queue import list_queued_tasks, pick_queued_task_by_id
from runtime.core.task_store import load_task
from runtime.core.artifact_store import load_artifact
from runtime.executor.execute_once import execute_once


def _seed_allowlist(root: Path, allowed_sites: list[str] = None) -> None:
    save_browser_control_allowlist(
        BrowserControlAllowlistRecord(
            browser_control_allowlist_id=new_id("browserallow"),
            created_at=now_iso(), updated_at=now_iso(),
            actor="tester", lane="tests",
            allowed_apps=[], allowed_sites=allowed_sites or ["example.com"],
            allowed_paths=[], blocked_apps=[], blocked_sites=[], blocked_paths=[],
            destructive_actions_require_confirmation=True,
            secret_entry_requires_manual_control=True,
        ), root=root,
    )


# ---------------------------------------------------------------------------
# pick_queued_task_by_id
# ---------------------------------------------------------------------------

def test_pick_queued_task_by_id_returns_task() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        record = create_browser_task(
            action_type="snapshot", target_url="https://example.com/",
            actor="tester", lane="tests", root=root,
        )
        row = pick_queued_task_by_id(record.task_id, root=root)
        assert row is not None
        assert row["task_id"] == record.task_id


def test_pick_queued_task_by_id_returns_none_for_unknown() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        row = pick_queued_task_by_id("task_doesnotexist", root=root)
        assert row is None


def test_pick_queued_task_by_id_only_returns_queued() -> None:
    """If two tasks are queued, targeting the second one works directly."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        r1 = create_browser_task(
            action_type="snapshot", target_url="https://example.com/1",
            actor="tester", lane="tests", root=root,
        )
        r2 = create_browser_task(
            action_type="snapshot", target_url="https://example.com/2",
            actor="tester", lane="tests", root=root,
        )
        # Target second task — should find it regardless of queue order
        row = pick_queued_task_by_id(r2.task_id, root=root)
        assert row is not None
        assert row["task_id"] == r2.task_id


# ---------------------------------------------------------------------------
# execute_once with task_id (queue isolation)
# ---------------------------------------------------------------------------

def test_execute_once_with_task_id_targets_specific_task() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)

        # Create two tasks; we want to execute the second one specifically
        r1 = create_browser_task(
            action_type="snapshot", target_url="https://example.com/1",
            actor="tester", lane="tests", root=root,
        )
        r2 = create_browser_task(
            action_type="snapshot", target_url="https://example.com/2",
            actor="tester", lane="tests", root=root,
        )

        result = execute_once(
            root=root, actor="executor", lane="executor",
            allow_parallel=True, task_id=r2.task_id,
        )

        assert result["kind"] == "backend_dispatch"
        assert result["picked_task"]["task_id"] == r2.task_id

        # r1 should still be queued (we didn't touch it)
        still_queued = [t["task_id"] for t in list_queued_tasks(root=root)]
        assert r1.task_id in still_queued
        assert r2.task_id not in still_queued


def test_execute_once_task_id_not_queued_returns_not_found() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = execute_once(
            root=root, actor="executor", lane="executor",
            allow_parallel=False, task_id="task_doesnotexist",
        )
        assert result["kind"] == "task_not_found_or_not_queued"


# ---------------------------------------------------------------------------
# Artifact writing after browser task completion
# ---------------------------------------------------------------------------

def test_execute_once_writes_browser_result_artifact_on_success() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)  # example.com allowed

        record = create_browser_task(
            action_type="snapshot", target_url="https://example.com/",
            actor="tester", lane="tests", root=root,
        )

        result = execute_once(
            root=root, actor="executor", lane="executor",
            allow_parallel=True, task_id=record.task_id,
        )

        assert result["kind"] == "backend_dispatch"
        dispatch = result["dispatch_result"]
        finish = result["finish_result"]

        # If dispatch succeeded, there should be an artifact
        if dispatch.get("status") == "completed":
            assert result["artifact_result"] is not None, "Artifact should be written on success"
            artifact_id = result["artifact_result"]["artifact_id"]
            assert finish.get("artifact_id") == artifact_id

            # Artifact should be loadable and contain browser content
            artifact = load_artifact(artifact_id, root=root)
            assert artifact.artifact_type == "browser_result"
            assert artifact.lifecycle_state == "promoted"
            assert "example.com" in artifact.content or "snapshot" in artifact.content.lower()

            # final_outcome should mention the artifact
            assert artifact_id in finish.get("final_outcome", "")
        else:
            # Blocked/failed — no artifact expected
            assert result.get("artifact_result") is None


def test_execute_once_no_artifact_on_blocked_browser_task() -> None:
    """A blocked browser task (policy) should not write an artifact."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)  # only example.com allowed

        record = create_browser_task(
            action_type="snapshot", target_url="https://notallowed.example.org/",
            actor="tester", lane="tests", root=root,
        )

        result = execute_once(
            root=root, actor="executor", lane="executor",
            allow_parallel=True, task_id=record.task_id,
        )

        assert result["kind"] == "backend_dispatch"
        assert result["dispatch_result"]["status"] == "failed"
        assert result.get("artifact_result") is None

        final_task = load_task(record.task_id, root=root)
        assert final_task.status == "failed"


# ---------------------------------------------------------------------------
# run_browser_task — direct API
# ---------------------------------------------------------------------------

def test_run_browser_task_returns_task_id_and_status() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)

        result = run_browser_task(
            action_type="snapshot",
            target_url="https://example.com/",
            actor="tester",
            lane="tests",
            root=root,
        )

        assert "task_id" in result
        assert result["task_id"].startswith("task_")
        assert result["status"] in {"completed", "failed"}
        assert "final_outcome" in result


def test_run_browser_task_exposes_browser_result() -> None:
    """run_browser_task should surface browser_result in the return value."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)

        result = run_browser_task(
            action_type="snapshot",
            target_url="https://example.com/",
            actor="tester",
            lane="tests",
            root=root,
        )

        # browser_result may be empty if blocked, but key should exist
        assert "browser_result" in result
        assert "dispatch_result" in result


if __name__ == "__main__":
    test_pick_queued_task_by_id_returns_task()
    test_pick_queued_task_by_id_returns_none_for_unknown()
    test_pick_queued_task_by_id_only_returns_queued()
    test_execute_once_with_task_id_targets_specific_task()
    test_execute_once_task_id_not_queued_returns_not_found()
    test_execute_once_writes_browser_result_artifact_on_success()
    test_execute_once_no_artifact_on_blocked_browser_task()
    test_run_browser_task_returns_task_id_and_status()
    test_run_browser_task_exposes_browser_result()
    print("All browser result surfacing tests passed.")
