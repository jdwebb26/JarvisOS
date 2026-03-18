#!/usr/bin/env python3
"""Tests proving openai_executor backend dispatch wiring.

Verifies that:
1. backend_dispatch recognizes openai_executor and calls the adapter
2. Config errors produce structured error results
3. Existing backends are not affected
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.executor.backend_dispatch import (
    BACKEND_ADAPTERS,
    dispatch_to_backend,
    has_backend_adapter,
    is_known_backend,
    list_registered_backends,
)


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------

def test_openai_executor_is_registered():
    assert has_backend_adapter("openai_executor")
    assert is_known_backend("openai_executor")


def test_openai_executor_in_list_registered():
    summary = list_registered_backends()
    assert "openai_executor" in summary["wired"]


def test_existing_backends_still_registered():
    """Adding OpenAI must not break existing registrations."""
    assert has_backend_adapter("nvidia_executor")
    assert has_backend_adapter("hermes_adapter")
    assert has_backend_adapter("kitt_quant")
    assert has_backend_adapter("browser_backend")


# ---------------------------------------------------------------------------
# dispatch_to_backend tests
# ---------------------------------------------------------------------------

def test_dispatch_openai_calls_adapter():
    """Dispatch to openai_executor invokes execute_openai_chat."""
    mock_result = {
        "status": "completed",
        "content": "Test response from GPT",
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        "request_id": "breq_oai_test",
        "result_id": "bres_oai_test",
        "error": "",
    }

    with patch("runtime.integrations.openai_executor.execute_openai_chat", return_value=mock_result) as mock_call:
        result = dispatch_to_backend(
            task_id="task_openai_1",
            actor="hal",
            lane="work",
            execution_backend="openai_executor",
            messages=[{"role": "user", "content": "Analyze NQ futures"}],
            routing_decision_id="rdec_oai_test_123",
            root=Path(tempfile.mkdtemp()),
        )

    assert result["status"] == "completed"
    assert result["content"] == "Test response from GPT"
    assert result["dispatched"] is True
    assert result["execution_backend"] == "openai_executor"

    mock_call.assert_called_once()
    call_kwargs = mock_call.call_args[1]
    assert call_kwargs["task_id"] == "task_openai_1"
    assert call_kwargs["actor"] == "hal"
    assert call_kwargs["lane"] == "work"
    assert call_kwargs["routing_decision_id"] == "rdec_oai_test_123"
    assert call_kwargs["messages"] == [{"role": "user", "content": "Analyze NQ futures"}]


def test_dispatch_openai_config_error_returns_structured_error():
    """When OPENAI_API_KEY is missing, dispatch returns config_error without crashing."""
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}

    with patch.dict(os.environ, env, clear=True):
        result = dispatch_to_backend(
            task_id="task_oai_nokey",
            actor="test",
            lane="test",
            execution_backend="openai_executor",
            messages=[{"role": "user", "content": "hello"}],
            root=Path(tempfile.mkdtemp()),
        )

    assert result["status"] == "config_error"
    assert result["dispatched"] is True
    assert "OPENAI_API_KEY" in result["error"]


def test_dispatch_openai_adapter_exception_returns_error():
    """If the adapter raises an unexpected exception, dispatch catches it."""
    with patch(
        "runtime.integrations.openai_executor.execute_openai_chat",
        side_effect=RuntimeError("requests library missing"),
    ):
        result = dispatch_to_backend(
            task_id="task_oai_exc",
            actor="test",
            lane="test",
            execution_backend="openai_executor",
            messages=[{"role": "user", "content": "hello"}],
            root=Path(tempfile.mkdtemp()),
        )

    assert result["status"] == "error"
    assert result["dispatched"] is True
    assert "RuntimeError" in result["error"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
