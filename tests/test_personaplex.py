#!/usr/bin/env python3
"""Tests for PersonaPlex conversational copilot.

Covers:
- Session create / load / persist / turn management
- Intent classification (conversational, command, escalation, meta)
- Context assembly (read-only, bounded)
- Engine conversation flow (with mocked LLM)
- Action proposal / confirmation / cancellation safety
- Safe file reading boundaries
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Session tests
# ---------------------------------------------------------------------------

class TestSession:
    def test_create_session(self, tmp_path):
        from runtime.personaplex.session import create_session, load_session

        session = create_session(actor="operator", root=tmp_path)
        assert session.conversation_id.startswith("ppx_")
        assert session.actor == "operator"
        assert session.mode == "conversational"
        assert session.turn_count == 0
        assert len(session.turns) == 0

        # Verify persisted
        loaded = load_session(session.conversation_id, root=tmp_path)
        assert loaded is not None
        assert loaded.conversation_id == session.conversation_id

    def test_add_turns(self, tmp_path):
        from runtime.personaplex.session import create_session, add_turn

        session = create_session(root=tmp_path)
        session = add_turn(session, "user", "hello", root=tmp_path)
        session = add_turn(session, "assistant", "hi there", root=tmp_path)
        assert session.turn_count == 2
        assert len(session.turns) == 2
        assert session.turns[0].role == "user"
        assert session.turns[1].content == "hi there"

    def test_turn_overflow_creates_summary(self, tmp_path):
        from runtime.personaplex.session import create_session, add_turn, MAX_RECENT_TURNS

        session = create_session(root=tmp_path)
        for i in range(MAX_RECENT_TURNS + 5):
            session = add_turn(session, "user", f"message {i}", root=tmp_path)
            session = add_turn(session, "assistant", f"reply {i}", root=tmp_path)

        assert len(session.turns) <= MAX_RECENT_TURNS
        assert session.rolling_summary != ""
        assert session.turn_count == (MAX_RECENT_TURNS + 5) * 2

    def test_build_conversation_messages(self, tmp_path):
        from runtime.personaplex.session import (
            create_session, add_turn, build_conversation_messages,
        )

        session = create_session(root=tmp_path)
        session.rolling_summary = "Earlier: user asked about tasks."
        session = add_turn(session, "user", "what's queued?", root=tmp_path)
        session = add_turn(session, "assistant", "3 tasks queued.", root=tmp_path)

        messages = build_conversation_messages(session)
        assert len(messages) == 3  # summary + 2 turns
        assert messages[0]["role"] == "system"
        assert "Earlier" in messages[0]["content"]
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"

    def test_pending_action_lifecycle(self, tmp_path):
        from runtime.personaplex.session import (
            create_session, add_pending_action, resolve_pending_action,
            clear_resolved_actions,
        )

        session = create_session(root=tmp_path)
        action = add_pending_action(
            session, description="Approve task_abc", action_type="approve_task",
            action_params={"task_id": "task_abc"}, root=tmp_path,
        )
        assert action.status == "pending"
        assert len(session.pending_actions) == 1

        resolve_pending_action(session, action.action_id, "confirmed", root=tmp_path)
        assert session.pending_actions[0].status == "confirmed"

        clear_resolved_actions(session, root=tmp_path)
        assert len(session.pending_actions) == 0

    def test_list_sessions(self, tmp_path):
        from runtime.personaplex.session import create_session, list_sessions

        s1 = create_session(root=tmp_path)
        s2 = create_session(root=tmp_path)
        sessions = list_sessions(root=tmp_path)
        assert len(sessions) == 2
        # Most recent first
        assert sessions[0].conversation_id == s2.conversation_id


# ---------------------------------------------------------------------------
# Intent classification tests
# ---------------------------------------------------------------------------

class TestIntentClassification:
    def test_conversational_intent(self):
        from runtime.personaplex.intent import classify_intent, INTENT_CONVERSATIONAL

        result = classify_intent("what needs approval right now?")
        assert result["intent"] == INTENT_CONVERSATIONAL

        result = classify_intent("summarize the system state")
        assert result["intent"] == INTENT_CONVERSATIONAL

        result = classify_intent("what did Hermes do recently?")
        assert result["intent"] == INTENT_CONVERSATIONAL

    def test_command_intent(self):
        from runtime.personaplex.intent import classify_intent, INTENT_COMMAND

        result = classify_intent("approve task_abc123def")
        assert result["intent"] == INTENT_COMMAND
        assert result["command_type"] == "approve_task"
        assert "task_abc123def" in result["extracted_ids"]

        result = classify_intent("reject task_xyz789")
        assert result["intent"] == INTENT_COMMAND
        assert result["command_type"] == "reject_task"

        result = classify_intent("retry task_abc123def")
        assert result["intent"] == INTENT_COMMAND
        assert result["command_type"] == "retry_task"

    def test_escalation_intent(self):
        from runtime.personaplex.intent import classify_intent, INTENT_ESCALATION

        result = classify_intent("should I approve this task?")
        assert result["intent"] == INTENT_ESCALATION

        result = classify_intent("can you approve that for me?")
        assert result["intent"] == INTENT_ESCALATION

    def test_confirmation_intent(self):
        from runtime.personaplex.intent import classify_intent, INTENT_ESCALATION

        result = classify_intent("yes")
        assert result["intent"] == INTENT_ESCALATION
        assert result["command_type"] == "confirm_pending"

        result = classify_intent("confirm")
        assert result["intent"] == INTENT_ESCALATION
        assert result["command_type"] == "confirm_pending"

    def test_meta_intent(self):
        from runtime.personaplex.intent import classify_intent, INTENT_META

        result = classify_intent("help")
        assert result["intent"] == INTENT_META
        assert result["command_type"] == "help"

        result = classify_intent("new session")
        assert result["intent"] == INTENT_META
        assert result["command_type"] == "new_session"

        result = classify_intent("quit")
        assert result["intent"] == INTENT_META
        assert result["command_type"] == "quit"

    def test_id_extraction(self):
        from runtime.personaplex.intent import classify_intent

        result = classify_intent("tell me about task_abc123 and apr_def456")
        assert "task_abc123" in result["extracted_ids"]
        assert "apr_def456" in result["extracted_ids"]

    def test_read_only_check(self):
        from runtime.personaplex.intent import classify_intent, is_read_only_intent

        conv = classify_intent("what's the status?")
        assert is_read_only_intent(conv)

        cmd = classify_intent("approve task_abc")
        assert not is_read_only_intent(cmd)

        meta = classify_intent("help")
        assert is_read_only_intent(meta)


# ---------------------------------------------------------------------------
# Context assembly tests
# ---------------------------------------------------------------------------

class TestContext:
    def test_assemble_runtime_context(self, tmp_path):
        from runtime.personaplex.context import assemble_runtime_context

        # Create minimal state dirs
        (tmp_path / "state" / "approvals").mkdir(parents=True)
        (tmp_path / "state" / "reviews").mkdir(parents=True)
        (tmp_path / "state" / "tasks").mkdir(parents=True)
        (tmp_path / "state" / "events").mkdir(parents=True)
        (tmp_path / "state" / "agent_status").mkdir(parents=True)

        ctx = assemble_runtime_context(root=tmp_path)
        assert "PENDING APPROVALS:" in ctx
        assert "TASK STATUS:" in ctx

    def test_pending_approvals_read(self, tmp_path):
        from runtime.personaplex.context import read_pending_approvals

        approvals_dir = tmp_path / "state" / "approvals"
        approvals_dir.mkdir(parents=True)
        (approvals_dir / "apr_test1.json").write_text(json.dumps({
            "approval_id": "apr_test1",
            "task_id": "task_test1",
            "status": "pending",
            "summary": "Review needed",
            "requested_by": "ralph",
            "created_at": "2026-03-18T10:00:00Z",
        }))
        (approvals_dir / "apr_test2.json").write_text(json.dumps({
            "approval_id": "apr_test2",
            "task_id": "task_test2",
            "status": "approved",
            "summary": "Already done",
        }))

        pending = read_pending_approvals(root=tmp_path)
        assert len(pending) == 1
        assert pending[0]["approval_id"] == "apr_test1"

    def test_safe_file_read(self, tmp_path):
        from runtime.personaplex.context import safe_read_file

        # Create a safe file
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "test.md").write_text("# Hello\nThis is a test.")

        result = safe_read_file(str(docs / "test.md"), root=tmp_path)
        assert result["error"] == ""
        assert "Hello" in result["content"]

    def test_safe_file_blocks_secrets(self, tmp_path):
        from runtime.personaplex.context import safe_read_file

        secrets = tmp_path / "secrets.env"
        secrets.write_text("API_KEY=sk-secret")

        result = safe_read_file(str(secrets), root=tmp_path)
        assert result["error"] != ""
        assert "not allowed" in result["error"].lower() or "secrets" in result["error"].lower()

    def test_safe_file_blocks_outside_root(self, tmp_path):
        from runtime.personaplex.context import safe_read_file

        result = safe_read_file("/etc/passwd", root=tmp_path)
        assert result["error"] != ""
        assert "outside" in result["error"].lower()

    def test_safe_file_blocks_bad_extension(self, tmp_path):
        from runtime.personaplex.context import safe_read_file

        binary = tmp_path / "data.bin"
        binary.write_bytes(b"\x00\x01\x02")

        result = safe_read_file(str(binary), root=tmp_path)
        assert result["error"] != ""
        assert "not in the safe-read list" in result["error"]


# ---------------------------------------------------------------------------
# Engine tests (with mocked LLM)
# ---------------------------------------------------------------------------

def _mock_llm_response(content="Here is the status."):
    """Mock the _call_llm function."""
    return {
        "content": content,
        "model": "qwen3.5-35b-a3b",
        "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
        "error": "",
    }


class TestEngine:
    def test_conversational_turn(self, tmp_path):
        from runtime.personaplex.engine import chat

        # Create minimal state dirs
        for d in ["tasks", "approvals", "reviews", "events", "agent_status"]:
            (tmp_path / "state" / d).mkdir(parents=True, exist_ok=True)

        with patch("runtime.personaplex.engine._call_llm", return_value=_mock_llm_response()):
            result = chat("what needs attention?", root=tmp_path)

        assert result["response"] == "Here is the status."
        assert result["intent"]["intent"] == "conversational"
        assert result["error"] == ""
        assert result["session"].turn_count == 2  # user + assistant

    def test_multi_turn_session(self, tmp_path):
        from runtime.personaplex.engine import chat

        for d in ["tasks", "approvals", "reviews", "events", "agent_status"]:
            (tmp_path / "state" / d).mkdir(parents=True, exist_ok=True)

        with patch("runtime.personaplex.engine._call_llm", return_value=_mock_llm_response("Turn 1")):
            r1 = chat("hello", root=tmp_path)

        conv_id = r1["session"].conversation_id

        with patch("runtime.personaplex.engine._call_llm", return_value=_mock_llm_response("Turn 2")):
            r2 = chat("what's queued?", conversation_id=conv_id, root=tmp_path)

        assert r2["session"].conversation_id == conv_id
        assert r2["session"].turn_count == 4  # 2 turns * 2 messages each
        assert r2["response"] == "Turn 2"

    def test_help_meta(self, tmp_path):
        from runtime.personaplex.engine import chat

        for d in ["tasks", "approvals", "reviews", "events", "agent_status"]:
            (tmp_path / "state" / d).mkdir(parents=True, exist_ok=True)

        result = chat("help", root=tmp_path)
        assert "conversational copilot" in result["response"].lower()
        assert result["intent"]["intent"] == "meta"

    def test_command_proposes_action(self, tmp_path):
        from runtime.personaplex.engine import chat

        for d in ["tasks", "approvals", "reviews", "events", "agent_status"]:
            (tmp_path / "state" / d).mkdir(parents=True, exist_ok=True)

        result = chat("approve task_abc123def", root=tmp_path)
        assert result["intent"]["intent"] == "command"
        assert result["action_proposed"] is not None
        assert result["action_proposed"]["action_type"] == "approve_task"
        assert result["action_proposed"]["status"] == "pending"
        assert "confirm" in result["response"].lower()

    def test_command_without_id_asks_for_it(self, tmp_path):
        from runtime.personaplex.engine import chat

        for d in ["tasks", "approvals", "reviews", "events", "agent_status"]:
            (tmp_path / "state" / d).mkdir(parents=True, exist_ok=True)

        result = chat("approve the task", root=tmp_path)
        assert result["intent"]["intent"] == "command"
        assert result["action_proposed"] is None
        assert "need" in result["response"].lower() or "which" in result["response"].lower()

    def test_confirmation_with_no_pending(self, tmp_path):
        from runtime.personaplex.engine import chat

        for d in ["tasks", "approvals", "reviews", "events", "agent_status"]:
            (tmp_path / "state" / d).mkdir(parents=True, exist_ok=True)

        with patch("runtime.personaplex.engine._call_llm", return_value=_mock_llm_response("No pending actions.")):
            result = chat("yes", root=tmp_path)

        # Should fall through to conversational since no pending action
        assert result["action_executed"] is None

    def test_llm_error_fallback(self, tmp_path):
        from runtime.personaplex.engine import chat

        for d in ["tasks", "approvals", "reviews", "events", "agent_status"]:
            (tmp_path / "state" / d).mkdir(parents=True, exist_ok=True)

        error_response = {"content": "", "model": "", "usage": {}, "error": "Connection refused"}

        with patch("runtime.personaplex.engine._call_llm", return_value=error_response):
            result = chat("what needs approval?", root=tmp_path)

        assert "LLM error" in result["response"]
        # Should still provide some useful info
        assert "approval" in result["response"].lower()

    def test_quit_ends_session(self, tmp_path):
        from runtime.personaplex.engine import chat

        for d in ["tasks", "approvals", "reviews", "events", "agent_status"]:
            (tmp_path / "state" / d).mkdir(parents=True, exist_ok=True)

        result = chat("quit", root=tmp_path)
        assert result["session"].mode == "ended"

    def test_never_executes_without_confirmation(self, tmp_path):
        """Core safety test: commands produce proposals, never direct execution."""
        from runtime.personaplex.engine import chat

        for d in ["tasks", "approvals", "reviews", "events", "agent_status"]:
            (tmp_path / "state" / d).mkdir(parents=True, exist_ok=True)

        # Issue a command
        result = chat("approve task_abc123", root=tmp_path)
        assert result["action_proposed"] is not None
        assert result["action_executed"] is None

        # Verify no task state was modified
        tasks_dir = tmp_path / "state" / "tasks"
        assert len(list(tasks_dir.glob("*.json"))) == 0


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
