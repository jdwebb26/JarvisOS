"""Tests for learnings digest injection into context packets."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.learnings_store import record_learning
from runtime.gateway.source_owned_context_engine import (
    LEARNINGS_AGENTS,
    LEARNINGS_DIGEST_CHAR_CAP,
    LEARNINGS_MAX_DELEGATION,
    LEARNINGS_MAX_ORCHESTRATOR,
    _build_learnings_digest,
    build_context_packet,
)


def _seed_learnings(root: Path) -> None:
    """Seed test learnings for jarvis, hal, archimedes."""
    record_learning(
        trigger="operator_correction",
        lesson="Never auto-promote strategies with Profit Factor below 1.3.",
        agent_id="jarvis",
        confidence=0.9,
        applies_to=["jarvis", "hal", "archimedes"],
        root=root,
    )
    record_learning(
        trigger="task_failure",
        lesson="Docker sandbox timeout after 120s — feature generation exceeded memory on 16GB node.",
        agent_id="hal",
        task_type="code",
        confidence=0.6,
        root=root,
    )
    record_learning(
        trigger="review_rejection",
        lesson="Review rejected: missing unit tests for edge cases in signal module.",
        agent_id="hal",
        task_type="code",
        confidence=0.75,
        applies_to=["hal"],
        root=root,
    )
    record_learning(
        trigger="environment_gotcha",
        lesson="SearXNG returns empty results when query contains special characters like NQ=F.",
        agent_id="kitt",
        confidence=0.7,
        applies_to=["kitt", "hermes", "scout"],
        root=root,
    )


def _make_packet(agent_id: str, root: Path) -> dict:
    return build_context_packet(
        root=root,
        session_key=f"agent:{agent_id}:test-learnings",
        system_prompt=f"You are {agent_id}.",
        current_prompt="Implement a new signal module.",
        messages=[{"role": "user", "content": "Implement a new signal module."}],
        tools=[],
        agent_id=agent_id,
        channel="discord",
    )


# ── Jarvis gets learnings digest ──

def test_jarvis_receives_learnings():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Create required state dirs
        (root / "state" / "memory_entries").mkdir(parents=True)
        _seed_learnings(root)

        packet = _make_packet("jarvis", root)
        ld = packet.get("learningsDigest", {})
        assert ld["itemCount"] > 0
        assert ld["charCount"] > 0
        assert "Profit Factor" in ld["text"]


# ── HAL gets learnings (compact) ──

def test_hal_receives_compact_learnings():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "state" / "memory_entries").mkdir(parents=True)
        _seed_learnings(root)

        packet = _make_packet("hal", root)
        ld = packet.get("learningsDigest", {})
        assert ld["itemCount"] > 0
        assert ld["itemCount"] <= LEARNINGS_MAX_DELEGATION
        assert ld["charCount"] <= LEARNINGS_DIGEST_CHAR_CAP


# ── Archimedes gets learnings (compact) ──

def test_archimedes_receives_compact_learnings():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "state" / "memory_entries").mkdir(parents=True)
        _seed_learnings(root)

        packet = _make_packet("archimedes", root)
        ld = packet.get("learningsDigest", {})
        # Archimedes gets learnings that apply_to includes archimedes
        assert ld["itemCount"] > 0
        assert ld["itemCount"] <= LEARNINGS_MAX_DELEGATION


# ── Scout does NOT get learnings ──

def test_scout_gets_no_learnings():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "state" / "memory_entries").mkdir(parents=True)
        _seed_learnings(root)

        packet = _make_packet("scout", root)
        ld = packet.get("learningsDigest", {})
        assert ld["itemCount"] == 0
        assert ld["text"] == ""


# ── Learnings are counted in prompt budget ──

def test_learnings_in_prompt_budget():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "state" / "memory_entries").mkdir(parents=True)
        _seed_learnings(root)

        packet = _make_packet("jarvis", root)
        budget = packet["promptBudget"]
        cats = budget["categories"]
        assert "learningsDigest" in cats
        ld_tokens = cats["learningsDigest"]["tokens"]
        assert ld_tokens > 0
        # Learnings tokens should be part of total
        assert budget["estimatedTotalTokens"] >= ld_tokens


# ── No learnings → empty digest, zero budget ──

def test_no_learnings_empty_digest():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "state" / "memory_entries").mkdir(parents=True)
        # Don't seed any learnings

        packet = _make_packet("jarvis", root)
        ld = packet.get("learningsDigest", {})
        assert ld["itemCount"] == 0
        assert ld["text"] == ""
        assert packet["promptBudget"]["categories"]["learningsDigest"]["tokens"] == 0


# ── Digest format is compact plain text ──

def test_digest_format_is_compact():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "state" / "memory_entries").mkdir(parents=True)
        _seed_learnings(root)

        digest = _build_learnings_digest("hal", delegation_compact=True, root=root)
        text = digest["text"]
        # Should be bullet points, not JSON
        assert not text.startswith("{")
        assert not text.startswith("[")
        for line in text.strip().splitlines():
            assert line.startswith("- "), f"Expected bullet point, got: {line!r}"


# ── Char cap enforced ──

def test_digest_char_cap_enforced():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "state" / "memory_entries").mkdir(parents=True)
        # Seed many long learnings to exceed cap
        for i in range(20):
            record_learning(
                trigger="manual",
                lesson=f"Learning {i}: " + "x" * 200,
                agent_id="jarvis",
                confidence=0.8,
                root=root,
            )

        digest = _build_learnings_digest("jarvis", delegation_compact=False, root=root)
        assert digest["charCount"] <= LEARNINGS_DIGEST_CHAR_CAP
        assert digest["capped"] is True


# ── Delegation vs orchestrator item caps ──

def test_delegation_gets_fewer_items_than_orchestrator():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "state" / "memory_entries").mkdir(parents=True)
        for i in range(10):
            record_learning(
                trigger="manual",
                lesson=f"Global learning number {i} about system behavior.",
                confidence=0.8,
                root=root,
            )

        d_orch = _build_learnings_digest("jarvis", delegation_compact=False, root=root)
        d_deleg = _build_learnings_digest("hal", delegation_compact=True, root=root)

        assert d_orch["itemCount"] <= LEARNINGS_MAX_ORCHESTRATOR
        assert d_deleg["itemCount"] <= LEARNINGS_MAX_DELEGATION
        assert d_deleg["itemCount"] <= d_orch["itemCount"]


# ── Agent-scoped: kitt learnings don't leak to jarvis ──

def test_agent_scoped_learnings_no_cross_leak():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "state" / "memory_entries").mkdir(parents=True)
        record_learning(
            trigger="environment_gotcha",
            lesson="SearXNG special char issue only affects kitt/hermes/scout.",
            agent_id="kitt",
            confidence=0.7,
            applies_to=["kitt", "hermes", "scout"],
            root=root,
        )

        # Jarvis should NOT see kitt-only learnings
        d_jarvis = _build_learnings_digest("jarvis", delegation_compact=False, root=root)
        assert "SearXNG" not in d_jarvis["text"]

        # HAL should NOT see kitt-only learnings
        d_hal = _build_learnings_digest("hal", delegation_compact=True, root=root)
        assert "SearXNG" not in d_hal["text"]
