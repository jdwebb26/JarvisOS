"""Tests for the Cadence → PersonaPlex bridge.

Verifies that conversational utterances route through PersonaPlex while
command intents remain bounded/safe.
"""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.cadence_ingress import (
    classify_cadence_intent,
    route_cadence_utterance,
)


def _mock_chat(user_input, *, root=None, voice_session_id=None, conversation_id=None):
    """Fake PersonaPlex chat that returns a structured result."""
    from runtime.personaplex.session import create_session
    session = create_session(voice_session_id=voice_session_id or "", root=root)
    return {
        "response": f"PersonaPlex says: {user_input}",
        "intent": {"intent": "conversational", "command_type": ""},
        "action_proposed": None,
        "action_executed": None,
        "session": session,
        "llm_usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        "error": "",
    }


def _mock_chat_command(user_input, *, root=None, voice_session_id=None, conversation_id=None):
    """Fake PersonaPlex chat that returns a command proposal (not execution)."""
    from runtime.personaplex.session import create_session
    session = create_session(voice_session_id=voice_session_id or "", root=root)
    return {
        "response": "Proposed action: Approve Task: task_abc123\nType 'yes' to confirm.",
        "intent": {"intent": "command", "command_type": "approve_task"},
        "action_proposed": {"action_id": "pact_test", "description": "Approve Task: task_abc123"},
        "action_executed": None,
        "session": session,
        "llm_usage": {},
        "error": "",
    }


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

def test_what_failed_today_classifies():
    """Conversational queries classify into a PersonaPlex-eligible intent."""
    result = classify_cadence_intent("what failed today")
    # "what failed today" may match jarvis_orchestration, scout_research, or unclassified
    # — all of which now route to PersonaPlex
    assert result["intent"] in ("jarvis_orchestration", "scout_research", "unclassified")


def test_summarize_system_state_classifies():
    result = classify_cadence_intent("summarize the current system state")
    assert result["intent"] in ("jarvis_orchestration", "scout_research", "unclassified")


def test_approve_task_classifies_as_approval():
    result = classify_cadence_intent("approve task_a7d82c0f29f8")
    assert result["intent"] == "approval_confirmation"


# ---------------------------------------------------------------------------
# Bridge routing tests (mocked LLM)
# ---------------------------------------------------------------------------

def test_conversational_routes_to_personaplex():
    with TemporaryDirectory() as tmp:
        with patch("runtime.voice.cadence_ingress.chat", _mock_chat, create=True):
            with patch("runtime.personaplex.engine.chat", _mock_chat):
                result = route_cadence_utterance(
                    "what failed today",
                    execute=True,
                    root=Path(tmp),
                )
        assert result["route_reason"] == "personaplex_conversation"
        assert result["routed"] is True
        delegation = result["delegation_result"]
        assert "response" in delegation
        assert delegation["response"]  # non-empty


def test_unclassified_routes_to_personaplex():
    with TemporaryDirectory() as tmp:
        with patch("runtime.personaplex.engine.chat", _mock_chat):
            result = route_cadence_utterance(
                "tell me something interesting",
                execute=True,
                root=Path(tmp),
            )
        assert result["route_reason"] == "personaplex_conversation"
        assert result["routed"] is True


def test_approval_routes_to_personaplex_safely():
    with TemporaryDirectory() as tmp:
        with patch("runtime.personaplex.engine.chat", _mock_chat_command):
            result = route_cadence_utterance(
                "approve task_abc123",
                execute=True,
                root=Path(tmp),
            )
        assert result["route_reason"] == "personaplex_conversation"
        delegation = result["delegation_result"]
        # PersonaPlex proposes, does not execute
        assert delegation.get("action_proposed") is not None
        assert delegation["personaplex_intent"] == "command"


def test_preview_mode_still_routes_to_personaplex():
    """Even in preview mode, PersonaPlex-eligible intents route to PersonaPlex."""
    with TemporaryDirectory() as tmp:
        with patch("runtime.personaplex.engine.chat", _mock_chat):
            # "show me the status" → jarvis_orchestration → PersonaPlex
            result = route_cadence_utterance(
                "show me the status",
                execute=False,
                root=Path(tmp),
            )
        assert result["route_reason"] == "personaplex_conversation"


def test_voice_session_id_passed_through():
    """Voice session ID should be passed to PersonaPlex."""
    captured = {}

    def capture_chat(user_input, *, root=None, voice_session_id=None, conversation_id=None):
        captured["voice_session_id"] = voice_session_id
        return _mock_chat(user_input, root=root, voice_session_id=voice_session_id)

    with TemporaryDirectory() as tmp:
        with patch("runtime.personaplex.engine.chat", capture_chat):
            route_cadence_utterance(
                "what needs attention",
                voice_session_id="vsession_test123",
                execute=True,
                root=Path(tmp),
            )
    assert captured.get("voice_session_id") == "vsession_test123"


def test_personaplex_error_returns_gracefully():
    """If PersonaPlex fails, return a clean error without crashing."""
    def failing_chat(*args, **kwargs):
        raise RuntimeError("LM Studio unreachable")

    with TemporaryDirectory() as tmp:
        with patch("runtime.personaplex.engine.chat", failing_chat):
            # Use an utterance that classifies as unclassified (PersonaPlex-eligible)
            result = route_cadence_utterance(
                "tell me something about the runtime",
                execute=True,
                root=Path(tmp),
            )
    assert result["routed"] is False
    assert result["route_reason"] == "personaplex_error"
    assert "LM Studio unreachable" in result["delegation_result"]["error"]


def test_browser_action_still_bypasses_personaplex():
    """Browser actions should still go through Bowser, not PersonaPlex."""
    result = classify_cadence_intent("browse to finance.yahoo.com")
    # URL-bearing browser commands should NOT be routed to PersonaPlex
    assert result["intent"] in ("browser_action", "voice_subsystem")


def test_hal_task_still_bypasses_personaplex():
    """Code tasks should still go through intake, not PersonaPlex."""
    result = classify_cadence_intent("implement the artifact cleanup function")
    assert result["intent"] == "hal_task"


def test_local_quick_still_inline():
    """Greetings should still be handled inline."""
    with TemporaryDirectory() as tmp:
        result = route_cadence_utterance(
            "hello",
            execute=True,
            root=Path(tmp),
        )
    assert result["route_reason"] == "local_quick_inline"


def test_delegation_result_has_conversation_id():
    """PersonaPlex delegation should include the conversation_id."""
    with TemporaryDirectory() as tmp:
        with patch("runtime.personaplex.engine.chat", _mock_chat):
            # Use a jarvis_orchestration intent to ensure PersonaPlex routing
            result = route_cadence_utterance(
                "show me the current status",
                execute=True,
                root=Path(tmp),
            )
    delegation = result["delegation_result"]
    assert "conversation_id" in delegation
    assert delegation["conversation_id"]  # non-empty
