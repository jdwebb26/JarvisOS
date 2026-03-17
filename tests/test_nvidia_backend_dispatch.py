#!/usr/bin/env python3
"""Tests proving nvidia_executor backend dispatch wiring.

Verifies that:
1. backend_dispatch recognizes nvidia_executor and calls the adapter
2. execute_once dispatches nvidia_executor tasks to the adapter
3. Qwen/unknown backends are not dispatched (fail-closed)
4. Config errors produce structured error results
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.executor.backend_dispatch import (
    BACKEND_ADAPTERS,
    KNOWN_BUT_UNWIRED,
    dispatch_to_backend,
    has_backend_adapter,
    is_known_backend,
    list_registered_backends,
)


# ---------------------------------------------------------------------------
# backend_dispatch unit tests
# ---------------------------------------------------------------------------

def test_nvidia_executor_is_registered():
    assert has_backend_adapter("nvidia_executor")
    assert is_known_backend("nvidia_executor")


def test_qwen_executor_is_not_dispatched():
    assert not has_backend_adapter("qwen_executor")
    assert not has_backend_adapter("qwen_planner")


def test_unknown_backend_is_not_known():
    assert not is_known_backend("totally_fake_backend")
    assert not has_backend_adapter("totally_fake_backend")


def test_hermes_is_known_but_unwired():
    assert is_known_backend("hermes_adapter")
    assert not has_backend_adapter("hermes_adapter")


def test_list_registered_backends():
    summary = list_registered_backends()
    assert "nvidia_executor" in summary["wired"]
    assert "hermes_adapter" in summary["known_unwired"]
    assert "qwen_executor" in summary["gateway_handled"]


# ---------------------------------------------------------------------------
# dispatch_to_backend tests
# ---------------------------------------------------------------------------

def test_dispatch_unknown_backend_fail_closed():
    result = dispatch_to_backend(
        task_id="task_test_1",
        actor="test",
        lane="test",
        execution_backend="imaginary_backend",
        messages=[{"role": "user", "content": "hello"}],
    )
    assert result["status"] == "unknown_backend"
    assert result["dispatched"] is False
    assert "imaginary_backend" in result["error"]


def test_dispatch_unwired_backend_returns_not_wired():
    result = dispatch_to_backend(
        task_id="task_test_2",
        actor="test",
        lane="test",
        execution_backend="hermes_adapter",
        messages=[{"role": "user", "content": "hello"}],
    )
    assert result["status"] == "not_wired"
    assert result["dispatched"] is False


def test_dispatch_qwen_returns_gateway_handled():
    result = dispatch_to_backend(
        task_id="task_test_3",
        actor="test",
        lane="test",
        execution_backend="qwen_executor",
        messages=[{"role": "user", "content": "hello"}],
    )
    assert result["status"] == "gateway_handled"
    assert result["dispatched"] is False


def test_dispatch_nvidia_calls_adapter():
    """Dispatch to nvidia_executor invokes execute_nvidia_chat."""
    mock_result = {
        "status": "completed",
        "content": "Test response from Kimi",
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        "request_id": "breq_test",
        "result_id": "bres_test",
        "error": "",
    }

    with patch("runtime.integrations.nvidia_executor.execute_nvidia_chat", return_value=mock_result) as mock_call:
        result = dispatch_to_backend(
            task_id="task_nvidia_1",
            actor="kitt",
            lane="kitt",
            execution_backend="nvidia_executor",
            messages=[{"role": "user", "content": "Analyze NQ futures"}],
            routing_decision_id="rdec_test_123",
            root=Path(tempfile.mkdtemp()),
        )

    assert result["status"] == "completed"
    assert result["content"] == "Test response from Kimi"
    assert result["dispatched"] is True
    assert result["execution_backend"] == "nvidia_executor"

    mock_call.assert_called_once()
    call_kwargs = mock_call.call_args[1]
    assert call_kwargs["task_id"] == "task_nvidia_1"
    assert call_kwargs["actor"] == "kitt"
    assert call_kwargs["lane"] == "kitt"
    assert call_kwargs["routing_decision_id"] == "rdec_test_123"
    assert call_kwargs["messages"] == [{"role": "user", "content": "Analyze NQ futures"}]


def test_dispatch_nvidia_config_error_returns_structured_error():
    """When NVIDIA_API_KEY is missing, dispatch returns config_error without crashing."""
    env = {k: v for k, v in os.environ.items() if k != "NVIDIA_API_KEY"}

    with patch.dict(os.environ, env, clear=True):
        result = dispatch_to_backend(
            task_id="task_nokey",
            actor="test",
            lane="test",
            execution_backend="nvidia_executor",
            messages=[{"role": "user", "content": "hello"}],
            root=Path(tempfile.mkdtemp()),
        )

    assert result["status"] == "config_error"
    assert result["dispatched"] is True
    assert "NVIDIA_API_KEY" in result["error"]


def test_dispatch_nvidia_adapter_exception_returns_error():
    """If the adapter raises an unexpected exception, dispatch catches it."""
    with patch(
        "runtime.integrations.nvidia_executor.execute_nvidia_chat",
        side_effect=RuntimeError("requests library missing"),
    ):
        result = dispatch_to_backend(
            task_id="task_exc",
            actor="test",
            lane="test",
            execution_backend="nvidia_executor",
            messages=[{"role": "user", "content": "hello"}],
            root=Path(tempfile.mkdtemp()),
        )

    assert result["status"] == "error"
    assert result["dispatched"] is True
    assert "RuntimeError" in result["error"]


# ---------------------------------------------------------------------------
# execute_once integration tests
# ---------------------------------------------------------------------------

def _make_task_dir(tmp: Path, task: dict) -> Path:
    """Write a task record into the expected state/tasks/ directory."""
    tasks_dir = tmp / "state" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    events_dir = tmp / "state" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    # Also create control store dirs
    (tmp / "state" / "controls").mkdir(parents=True, exist_ok=True)
    # Write task
    path = tasks_dir / f"{task['task_id']}.json"
    path.write_text(json.dumps(task, indent=2), encoding="utf-8")
    return tasks_dir


def _make_nvidia_task(task_id: str = "task_kitt_nv_1") -> dict:
    """Create a minimal task record with nvidia_executor backend."""
    return {
        "task_id": task_id,
        "created_at": "2026-03-17T10:00:00Z",
        "updated_at": "2026-03-17T10:00:00Z",
        "source_lane": "kitt",
        "source_channel": "",
        "source_message_id": "",
        "source_user": "operator",
        "trigger_type": "direct",
        "raw_request": "Analyze NQ regime shifts",
        "normalized_request": "Analyze NQ regime shifts using recent OHLCV data",
        "task_type": "quant",
        "priority": "normal",
        "risk_level": "normal",
        "status": "queued",
        "assigned_role": "executor",
        "assigned_model": "moonshotai/kimi-k2.5",
        "execution_backend": "nvidia_executor",
        "backend_assignment_id": "ba_test_1",
        "backend_metadata": {
            "routing": {
                "routing_decision_id": "rdec_kitt_1",
                "provider_id": "nvidia",
                "model_name": "moonshotai/kimi-k2.5",
            }
        },
        "summary": "Analyze NQ regime shifts",
        "review_required": False,
        "approval_required": False,
        "lifecycle_state": "active",
        "error_count": 0,
    }


def _make_qwen_task(task_id: str = "task_hal_qw_1") -> dict:
    """Create a minimal task record with qwen_executor backend."""
    return {
        "task_id": task_id,
        "created_at": "2026-03-17T10:00:00Z",
        "updated_at": "2026-03-17T10:00:00Z",
        "source_lane": "hal",
        "source_channel": "",
        "source_message_id": "",
        "source_user": "operator",
        "trigger_type": "direct",
        "raw_request": "Implement feature X",
        "normalized_request": "Implement feature X in routing.py",
        "task_type": "code",
        "priority": "normal",
        "risk_level": "normal",
        "status": "queued",
        "assigned_role": "executor",
        "assigned_model": "Qwen3.5-35B",
        "execution_backend": "qwen_executor",
        "backend_assignment_id": "ba_test_2",
        "backend_metadata": {
            "routing": {
                "routing_decision_id": "rdec_hal_1",
                "provider_id": "qwen",
                "model_name": "Qwen3.5-35B",
            }
        },
        "summary": "Implement feature X",
        "review_required": False,
        "approval_required": False,
        "lifecycle_state": "active",
        "error_count": 0,
    }


def test_execute_once_dispatches_nvidia_task():
    """execute_once picks an nvidia_executor task and dispatches via backend_dispatch."""
    from runtime.executor.execute_once import execute_once

    tmp = Path(tempfile.mkdtemp())
    task = _make_nvidia_task()
    _make_task_dir(tmp, task)

    mock_result = {
        "status": "completed",
        "content": "NQ regime analysis complete",
        "usage": {"total_tokens": 50},
        "request_id": "breq_1",
        "result_id": "bres_1",
        "error": "",
    }

    with patch.dict("runtime.executor.backend_dispatch.BACKEND_ADAPTERS", {"nvidia_executor": lambda **kw: mock_result}):
        with patch("runtime.controls.control_store.assert_control_allows"):
            result = execute_once(root=tmp, actor="executor", lane="kitt", allow_parallel=True)

    assert result["kind"] == "backend_dispatch"
    assert result["dispatch_result"]["status"] == "completed"
    assert result["dispatch_result"]["dispatched"] is True
    # Task should have been completed
    completed_task = json.loads((tmp / "state" / "tasks" / f"{task['task_id']}.json").read_text())
    assert completed_task["status"] == "completed"


def test_execute_once_qwen_task_uses_generic_path():
    """execute_once with qwen_executor falls through to generic type-based logic."""
    from runtime.executor.execute_once import execute_once

    tmp = Path(tempfile.mkdtemp())
    task = _make_qwen_task()
    _make_task_dir(tmp, task)

    with patch("runtime.controls.control_store.assert_control_allows"):
        result = execute_once(root=tmp, actor="executor", lane="hal", allow_parallel=True)

    # qwen_executor has no wired adapter → generic path
    assert result["kind"] == "executor_run"
    # Code tasks use "checkpoint_only" action
    assert result["finish_result"]["status"] == "running"


def test_execute_once_nvidia_failure_fails_task():
    """execute_once fails the task when nvidia_executor returns an error."""
    from runtime.executor.execute_once import execute_once

    tmp = Path(tempfile.mkdtemp())
    task = _make_nvidia_task("task_nv_fail")
    _make_task_dir(tmp, task)

    mock_result = {
        "status": "config_error",
        "content": "",
        "usage": {},
        "request_id": None,
        "result_id": None,
        "error": "NVIDIA_API_KEY is not set.",
    }

    with patch.dict("runtime.executor.backend_dispatch.BACKEND_ADAPTERS", {"nvidia_executor": lambda **kw: mock_result}):
        with patch("runtime.controls.control_store.assert_control_allows"):
            result = execute_once(root=tmp, actor="executor", lane="kitt", allow_parallel=True)

    assert result["kind"] == "backend_dispatch"
    assert result["dispatch_result"]["status"] == "config_error"
    # Task should have been failed
    failed_task = json.loads((tmp / "state" / "tasks" / "task_nv_fail.json").read_text())
    assert failed_task["status"] == "failed"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
