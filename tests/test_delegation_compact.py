"""Tests for delegation compact mode in source_owned_context_engine."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime.gateway.source_owned_context_engine as engine
from runtime.gateway.source_owned_context_engine import (
    DELEGATION_AGENTS,
    DELEGATION_EPISODIC_LIMIT,
    DELEGATION_RAW_USER_TURN_WINDOW,
    DELEGATION_RETRIEVAL_BUDGET_TOKENS,
    DELEGATION_SEMANTIC_LIMIT,
    DEFAULT_EPISODIC_LIMIT,
    DEFAULT_RAW_USER_TURN_WINDOW,
    DEFAULT_SEMANTIC_LIMIT,
    build_context_packet,
)


def _make_messages(n_user_turns: int = 8) -> list[dict]:
    msgs = []
    for i in range(n_user_turns):
        msgs.append({"role": "user", "content": f"Task {i}: implement feature {i}. " + "Detail. " * 15})
        msgs.append({"role": "assistant", "content": f"Done task {i}. " + "Output. " * 10})
    return msgs


def _make_tools() -> list[dict]:
    return [
        {"name": "read", "description": "Read file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}},
        {"name": "bash", "description": "Run cmd", "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}},
    ]


def _build(agent_id: str, messages: list[dict], *, disable_compact: bool = False) -> dict:
    original = engine.DELEGATION_AGENTS
    if disable_compact:
        engine.DELEGATION_AGENTS = frozenset()
    try:
        return build_context_packet(
            root=ROOT,
            session_key=f"agent:{agent_id}:test-{id(messages)}",
            system_prompt=f"You are {agent_id}.",
            current_prompt=messages[-2]["content"] if len(messages) >= 2 else "",
            messages=messages,
            tools=_make_tools(),
            agent_id=agent_id,
            channel="discord",
        )
    finally:
        engine.DELEGATION_AGENTS = original


# ── HAL gets compact mode automatically ──

def test_hal_gets_delegation_compact():
    msgs = _make_messages(8)
    packet = _build("hal", msgs)
    dc = packet.get("delegationCompact")
    assert dc is not None
    assert dc["enabled"] is True
    assert dc["rawUserTurnWindow"] == DELEGATION_RAW_USER_TURN_WINDOW
    assert dc["episodicLimit"] == DELEGATION_EPISODIC_LIMIT
    assert dc["semanticLimit"] == DELEGATION_SEMANTIC_LIMIT
    assert dc["retrievalBudgetTokens"] == DELEGATION_RETRIEVAL_BUDGET_TOKENS
    assert dc["memoryFlushSkipped"] is True


def test_archimedes_gets_delegation_compact():
    msgs = _make_messages(4)
    packet = _build("archimedes", msgs)
    dc = packet.get("delegationCompact")
    assert dc is not None
    assert dc["enabled"] is True


# ── Jarvis does NOT get compact mode ──

def test_jarvis_does_not_get_compact():
    msgs = _make_messages(8)
    packet = _build("jarvis", msgs)
    assert packet.get("delegationCompact") is None


def test_scout_does_not_get_compact():
    msgs = _make_messages(4)
    packet = _build("scout", msgs)
    assert packet.get("delegationCompact") is None


# ── Compact mode reduces context size ──

def test_compact_reduces_total_tokens():
    msgs = _make_messages(8)
    packet_full = _build("hal", msgs, disable_compact=True)
    packet_compact = _build("hal", msgs)

    full_tokens = packet_full["promptBudget"]["estimatedTotalTokens"]
    compact_tokens = packet_compact["promptBudget"]["estimatedTotalTokens"]

    assert compact_tokens < full_tokens, (
        f"Compact ({compact_tokens}) should be smaller than full ({full_tokens})"
    )


def test_compact_reduces_recent_messages():
    msgs = _make_messages(8)
    packet_full = _build("hal", msgs, disable_compact=True)
    packet_compact = _build("hal", msgs)

    full_msgs = packet_full["promptBudget"]["workingMemory"]["recentMessageCount"]
    compact_msgs = packet_compact["promptBudget"]["workingMemory"]["recentMessageCount"]

    assert compact_msgs <= full_msgs
    assert compact_msgs <= (DELEGATION_RAW_USER_TURN_WINDOW * 2 + 1)


def test_compact_reduces_memory_retrieval():
    msgs = _make_messages(4)
    packet_full = _build("hal", msgs, disable_compact=True)
    packet_compact = _build("hal", msgs)

    full_ep = packet_full["promptBudget"]["retrieval"]["episodicCount"]
    full_sem = packet_full["promptBudget"]["retrieval"]["semanticCount"]
    compact_ep = packet_compact["promptBudget"]["retrieval"]["episodicCount"]
    compact_sem = packet_compact["promptBudget"]["retrieval"]["semanticCount"]

    assert compact_ep <= DELEGATION_EPISODIC_LIMIT
    assert compact_sem <= DELEGATION_SEMANTIC_LIMIT
    # Full mode allows up to DEFAULT limits
    assert full_ep <= DEFAULT_EPISODIC_LIMIT
    assert full_sem <= DEFAULT_SEMANTIC_LIMIT


# ── Compact mode skips memory flushing ──

def test_compact_skips_memory_flush():
    """Delegation agents should not write operator preferences to durable memory."""
    msgs = _make_messages(4)
    # Add a message with operator preference pattern
    msgs.append({"role": "user", "content": "I prefer to always use pytest for testing. Never use unittest."})
    msgs.append({"role": "assistant", "content": "Understood, I will use pytest."})

    packet = _build("hal", msgs)
    dc = packet.get("delegationCompact")
    assert dc is not None
    assert dc["memoryFlushSkipped"] is True


# ── Repeated delegation runs stay compact ──

def test_repeated_runs_stay_compact():
    msgs = _make_messages(4)
    for _ in range(3):
        packet = _build("hal", msgs)
        dc = packet.get("delegationCompact")
        assert dc is not None
        assert dc["enabled"] is True
        budget = packet["promptBudget"]
        assert budget["retrieval"]["episodicCount"] <= DELEGATION_EPISODIC_LIMIT
        assert budget["retrieval"]["semanticCount"] <= DELEGATION_SEMANTIC_LIMIT


# ── Compact mode works correctly with small message sets ──

def test_compact_with_single_message():
    msgs = [{"role": "user", "content": "Implement the signal module."}]
    packet = _build("hal", msgs)
    dc = packet.get("delegationCompact")
    assert dc is not None
    assert dc["enabled"] is True
    assert not packet["blocked"]


# ── Jarvis retains full context for orchestration ──

def test_jarvis_retains_full_retrieval():
    msgs = _make_messages(8)
    packet = _build("jarvis", msgs)
    budget = packet["promptBudget"]
    # Jarvis should use full defaults
    assert budget["workingMemory"]["recentMessageCount"] > DELEGATION_RAW_USER_TURN_WINDOW * 2
    assert packet.get("delegationCompact") is None
