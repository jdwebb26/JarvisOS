#!/usr/bin/env python3
"""Tests for todo_intake — direct task creation from #todo messages."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _mock_intake_result(**overrides):
    base = {
        "kind": "task_created",
        "ok": True,
        "task_created": True,
        "task_id": "task_test_todo_001",
        "short_summary": "Test todo summary",
        "initial_status": "queued",
        "final_status": "queued",
        "task_type": "general",
        "priority": "normal",
        "risk_level": "normal",
        "assigned_model": "Qwen3.5-35B",
    }
    base.update(overrides)
    return base


def test_submit_todo_creates_task(tmp_path):
    from scripts.todo_intake import submit_todo

    mock_task = MagicMock()
    mock_task.status = "queued"
    mock_task.execution_backend = "qwen_executor"

    with (
        patch("scripts.todo_intake.create_task_from_message_result",
              return_value=_mock_intake_result()) as mock_create,
        patch("scripts.todo_intake._load_task", return_value=mock_task),
        patch("scripts.todo_intake._save_task"),
        patch("scripts.todo_intake.emit_event", return_value={"event_id": "devt_test"}),
    ):
        result = submit_todo("Test todo item", root=tmp_path)

    assert result["task_created"] is True
    assert result["todo_intake"] is True
    assert result["source_channel"] == "todo"
    # create_task_from_message_result should be called with task: prefix
    call_text = mock_create.call_args[1]["text"]
    assert call_text.startswith("task: ")


def test_submit_todo_preserves_existing_task_prefix(tmp_path):
    from scripts.todo_intake import submit_todo

    with (
        patch("scripts.todo_intake.create_task_from_message_result",
              return_value=_mock_intake_result()) as mock_create,
        patch("scripts.todo_intake._load_task", return_value=None),
        patch("scripts.todo_intake.emit_event", return_value={"event_id": "devt_test"}),
    ):
        result = submit_todo("task: Already has prefix", root=tmp_path)

    call_text = mock_create.call_args[1]["text"]
    assert call_text == "task: Already has prefix"
    assert not call_text.startswith("task: task:")


def test_submit_todo_overrides_backend_for_general(tmp_path):
    from scripts.todo_intake import submit_todo

    mock_task = MagicMock()
    mock_task.status = "queued"
    mock_task.execution_backend = "qwen_executor"

    with (
        patch("scripts.todo_intake.create_task_from_message_result",
              return_value=_mock_intake_result(task_type="general", risk_level="normal")),
        patch("scripts.todo_intake._load_task", return_value=mock_task),
        patch("scripts.todo_intake._save_task") as mock_save,
        patch("scripts.todo_intake.emit_event", return_value={"event_id": "devt_test"}),
    ):
        result = submit_todo("Simple general task", root=tmp_path)

    # Should override to ralph_adapter
    assert result.get("execution_backend_override") == "ralph_adapter"
    mock_save.assert_called_once()
    saved_task = mock_save.call_args[0][1]
    assert saved_task.execution_backend == "ralph_adapter"


def test_submit_todo_does_not_override_deploy(tmp_path):
    from scripts.todo_intake import submit_todo

    with (
        patch("scripts.todo_intake.create_task_from_message_result",
              return_value=_mock_intake_result(task_type="deploy", risk_level="high_stakes")),
        patch("scripts.todo_intake._load_task"),
        patch("scripts.todo_intake._save_task"),
        patch("scripts.todo_intake.emit_event", return_value={"event_id": "devt_test"}),
    ):
        result = submit_todo("Deploy something", root=tmp_path)

    # Should NOT override deploy tasks
    assert result.get("execution_backend_override") is None


def test_submit_todo_empty_text():
    from scripts.todo_intake import submit_todo
    result = submit_todo("")
    assert result["ok"] is False
    assert "empty" in result["error"]


def test_submit_todo_emits_discord_event(tmp_path):
    from scripts.todo_intake import submit_todo

    captured = []

    def mock_emit(kind, agent_id, **kw):
        captured.append({"kind": kind, "agent_id": agent_id, **kw})
        return {"event_id": "devt_test"}

    with (
        patch("scripts.todo_intake.create_task_from_message_result",
              return_value=_mock_intake_result()),
        patch("scripts.todo_intake._load_task", return_value=None),
        patch("scripts.todo_intake.emit_event", side_effect=mock_emit),
    ):
        result = submit_todo("Test event emission", root=tmp_path)

    assert len(captured) == 1
    assert captured[0]["kind"] == "task_created"
    assert "[todo]" in captured[0]["detail"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
