"""Tests for task chunking — parent/child task decomposition."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import TaskRecord, new_id, now_iso
from runtime.core.task_store import create_task, load_task
from runtime.core.task_chunking import (
    CHUNK_CHAR_THRESHOLD,
    CHUNK_VERB_THRESHOLD,
    MAX_CHILDREN,
    MIN_CHILDREN,
    _heuristic_split,
    chunk_task,
    get_children_status,
    rollup_parent,
    should_chunk,
)


def _make_task(request: str, *, parent_id: str = None, child_ids: list = None) -> TaskRecord:
    ts = now_iso()
    return TaskRecord(
        task_id=new_id("task"),
        created_at=ts, updated_at=ts,
        source_lane="test", source_channel="test", source_message_id="",
        source_user="test", trigger_type="test",
        raw_request=request, normalized_request=request,
        task_type="code", status="queued",
        execution_backend="ralph_adapter",
        parent_task_id=parent_id,
        child_task_ids=child_ids or [],
    )


def _setup_root():
    tmp = tempfile.mkdtemp()
    root = Path(tmp)
    for d in ("state/tasks", "state/events", "state/controls"):
        (root / d).mkdir(parents=True)
    return root


# ── should_chunk ──

SMALL_REQUEST = "Fix the login bug."

LARGE_REQUEST = (
    "Build a complete NQ futures trading signal module. "
    "1. Create the data model for OHLCV bars with volume confirmation. "
    "2. Implement the EMA crossover calculator with configurable periods. "
    "3. Add regime detection that validates VIX levels before generating signals. "
    "4. Write unit tests for all edge cases including missing data and zero volume. "
    "5. Integrate with the strategy factory pipeline and update the config."
)


def test_small_request_not_chunked():
    task = _make_task(SMALL_REQUEST)
    assert not should_chunk(task)


def test_large_request_chunked():
    task = _make_task(LARGE_REQUEST)
    assert should_chunk(task)


def test_child_task_not_rechunked():
    task = _make_task(LARGE_REQUEST, parent_id="task_parent_001")
    assert not should_chunk(task)


def test_already_chunked_not_rechunked():
    task = _make_task(LARGE_REQUEST, child_ids=["task_child_001"])
    assert not should_chunk(task)


# ── heuristic_split ──

def test_heuristic_numbered_list():
    text = (
        "1. Create the data model\n"
        "2. Implement the calculator\n"
        "3. Write the tests"
    )
    parts = _heuristic_split(text)
    assert len(parts) >= 3


def test_heuristic_sentence_split():
    text = (
        "First build the authentication module with JWT tokens. "
        "Then create the API endpoints for user management. "
        "Finally write integration tests against a test database."
    )
    parts = _heuristic_split(text)
    assert len(parts) >= 2


# ── chunk_task ──

def test_chunk_creates_children():
    root = _setup_root()
    task = _make_task(LARGE_REQUEST)
    create_task(task, root=root)

    subtasks = [
        "Create OHLCV data model with volume confirmation",
        "Implement EMA crossover calculator with configurable periods",
        "Add VIX regime detection for signal validation",
    ]
    child_ids = chunk_task(task, root=root, subtask_descriptions=subtasks)

    assert len(child_ids) == 3

    # Parent should have child_task_ids
    parent = load_task(task.task_id, root=root)
    assert parent.child_task_ids == child_ids
    assert parent.backend_metadata.get("chunked") is True

    # Each child should exist and point to parent
    for cid in child_ids:
        child = load_task(cid, root=root)
        assert child is not None
        assert child.parent_task_id == task.task_id
        assert child.status == "queued"
        assert child.execution_backend == "ralph_adapter"


def test_chunk_respects_min_children():
    root = _setup_root()
    task = _make_task(LARGE_REQUEST)
    create_task(task, root=root)

    child_ids = chunk_task(task, root=root, subtask_descriptions=["Only one"])
    assert child_ids == []  # Too few


# ── get_children_status ──

def test_children_status_tracking():
    root = _setup_root()
    parent = _make_task(LARGE_REQUEST)
    create_task(parent, root=root)

    subtasks = ["Sub A", "Sub B long enough", "Sub C also long enough"]
    child_ids = chunk_task(parent, root=root, subtask_descriptions=subtasks)

    status = get_children_status(parent.task_id, root=root)
    assert status["has_children"]
    assert status["total"] == 3
    assert status["pending"] == 3
    assert not status["all_done"]


# ── rollup_parent ──

def test_rollup_completes_parent():
    root = _setup_root()
    parent = _make_task(LARGE_REQUEST)
    parent.status = "completed"
    parent.final_outcome = "Chunked into 3 subtasks: a, b, c"
    create_task(parent, root=root)

    subtasks = [
        "Create data model with validation",
        "Implement calculator with tests",
        "Write integration test suite",
    ]
    child_ids = chunk_task(parent, root=root, subtask_descriptions=subtasks)

    # Simulate children completing
    from runtime.core.task_runtime import start_task, complete_task
    for cid in child_ids:
        start_task(root=root, task_id=cid, actor="ralph", lane="test", reason="test")
        complete_task(root=root, task_id=cid, actor="ralph", lane="test",
                      final_outcome=f"Child {cid} done")

    result = rollup_parent(parent.task_id, root=root)
    assert result["action"] == "completed"

    parent_after = load_task(parent.task_id, root=root)
    assert "All 3 subtasks completed" in parent_after.final_outcome


def test_rollup_waits_for_pending():
    root = _setup_root()
    parent = _make_task(LARGE_REQUEST)
    parent.status = "completed"
    parent.final_outcome = "Chunked into 2 subtasks: x, y"
    create_task(parent, root=root)

    subtasks = ["Do part one of the work", "Do part two of the work"]
    child_ids = chunk_task(parent, root=root, subtask_descriptions=subtasks)

    # Only complete one child
    from runtime.core.task_runtime import start_task, complete_task
    start_task(root=root, task_id=child_ids[0], actor="ralph", lane="test", reason="test")
    complete_task(root=root, task_id=child_ids[0], actor="ralph", lane="test",
                  final_outcome="Done")

    result = rollup_parent(parent.task_id, root=root)
    assert result["action"] == "wait"
    assert "1 children still pending" in result["reason"]


def test_rollup_fails_parent_on_child_failure():
    root = _setup_root()
    parent = _make_task(LARGE_REQUEST)
    parent.status = "completed"
    parent.final_outcome = "Chunked into 2 subtasks"
    create_task(parent, root=root)

    subtasks = ["Part one of the work here", "Part two of the work here"]
    child_ids = chunk_task(parent, root=root, subtask_descriptions=subtasks)

    from runtime.core.task_runtime import start_task, complete_task, fail_task
    start_task(root=root, task_id=child_ids[0], actor="ralph", lane="test", reason="test")
    complete_task(root=root, task_id=child_ids[0], actor="ralph", lane="test",
                  final_outcome="Done")
    start_task(root=root, task_id=child_ids[1], actor="ralph", lane="test", reason="test")
    fail_task(root=root, task_id=child_ids[1], actor="ralph", lane="test",
              reason="child failed")

    result = rollup_parent(parent.task_id, root=root)
    assert result["action"] == "failed"
