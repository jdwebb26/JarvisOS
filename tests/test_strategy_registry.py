#!/usr/bin/env python3
"""Tests for quant lanes strategy registry."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, get_strategy, load_all_strategies,
    LIFECYCLE_STATES, TERMINAL_STATES, TRANSITION_AUTHORITY,
)


@pytest.fixture
def registry_root(tmp_path):
    """Create a temp root with the expected directory structure."""
    (tmp_path / "workspace" / "quant" / "shared" / "registries").mkdir(parents=True)
    return tmp_path


def test_create_strategy(registry_root):
    entry = create_strategy(registry_root, "test-001", actor="atlas")
    assert entry.strategy_id == "test-001"
    assert entry.lifecycle_state == "IDEA"
    assert len(entry.state_history) == 1
    assert entry.state_history[0].by == "atlas"


def test_create_duplicate_fails(registry_root):
    create_strategy(registry_root, "test-001", actor="atlas")
    with pytest.raises(ValueError, match="already exists"):
        create_strategy(registry_root, "test-001", actor="atlas")


def test_create_non_idea_fails(registry_root):
    with pytest.raises(ValueError, match="must start as IDEA"):
        create_strategy(registry_root, "test-001", initial_state="CANDIDATE", actor="atlas")


def test_create_unauthorized_actor_fails(registry_root):
    with pytest.raises(ValueError, match="cannot create IDEA"):
        create_strategy(registry_root, "test-001", actor="executor")


def test_transition_happy_path(registry_root):
    create_strategy(registry_root, "test-001", actor="atlas")
    entry = transition_strategy(registry_root, "test-001", "CANDIDATE", actor="atlas")
    assert entry.lifecycle_state == "CANDIDATE"
    assert len(entry.state_history) == 2


def test_transition_unauthorized(registry_root):
    create_strategy(registry_root, "test-001", actor="atlas")
    with pytest.raises(ValueError, match="cannot transition"):
        transition_strategy(registry_root, "test-001", "CANDIDATE", actor="executor")


def test_transition_invalid_path(registry_root):
    create_strategy(registry_root, "test-001", actor="atlas")
    with pytest.raises(ValueError, match="not defined"):
        transition_strategy(registry_root, "test-001", "PROMOTED", actor="sigma")


def test_transition_from_terminal(registry_root):
    create_strategy(registry_root, "test-001", actor="atlas")
    transition_strategy(registry_root, "test-001", "CANDIDATE", actor="atlas")
    transition_strategy(registry_root, "test-001", "VALIDATING", actor="sigma")
    transition_strategy(registry_root, "test-001", "REJECTED", actor="sigma")
    with pytest.raises(ValueError, match="terminal state"):
        transition_strategy(registry_root, "test-001", "CANDIDATE", actor="atlas")


def test_paper_queued_requires_approval(registry_root):
    create_strategy(registry_root, "test-001", actor="atlas")
    transition_strategy(registry_root, "test-001", "CANDIDATE", actor="atlas")
    transition_strategy(registry_root, "test-001", "VALIDATING", actor="sigma")
    transition_strategy(registry_root, "test-001", "PROMOTED", actor="sigma")
    with pytest.raises(ValueError, match="approval_ref is required"):
        transition_strategy(registry_root, "test-001", "PAPER_QUEUED", actor="kitt")


def test_paper_queued_with_approval(registry_root):
    create_strategy(registry_root, "test-001", actor="atlas")
    transition_strategy(registry_root, "test-001", "CANDIDATE", actor="atlas")
    transition_strategy(registry_root, "test-001", "VALIDATING", actor="sigma")
    transition_strategy(registry_root, "test-001", "PROMOTED", actor="sigma")
    entry = transition_strategy(registry_root, "test-001", "PAPER_QUEUED", actor="kitt",
                                approval_ref="approval-2026-03-18-001")
    assert entry.lifecycle_state == "PAPER_QUEUED"
    assert entry.state_history[-1].approval_ref == "approval-2026-03-18-001"


def test_retirement_requires_reason(registry_root):
    create_strategy(registry_root, "test-001", actor="atlas")
    with pytest.raises(ValueError, match="retirement_reason"):
        transition_strategy(registry_root, "test-001", "RETIRED", actor="kitt")


def test_retirement_with_reason(registry_root):
    create_strategy(registry_root, "test-001", actor="kitt")
    entry = transition_strategy(registry_root, "test-001", "RETIRED", actor="kitt",
                                retirement_reason="strategy expired")
    assert entry.lifecycle_state == "RETIRED"


def test_retirement_unauthorized(registry_root):
    create_strategy(registry_root, "test-001", actor="atlas")
    with pytest.raises(ValueError, match="cannot retire"):
        transition_strategy(registry_root, "test-001", "RETIRED", actor="executor",
                            retirement_reason="test")


def test_get_strategy(registry_root):
    create_strategy(registry_root, "test-001", actor="atlas")
    s = get_strategy(registry_root, "test-001")
    assert s is not None
    assert s.strategy_id == "test-001"
    assert get_strategy(registry_root, "nonexistent") is None


def test_load_all(registry_root):
    create_strategy(registry_root, "test-001", actor="atlas")
    create_strategy(registry_root, "test-002", actor="kitt")
    all_s = load_all_strategies(registry_root)
    assert len(all_s) == 2


def test_idempotent_transition(registry_root):
    create_strategy(registry_root, "test-001", actor="atlas")
    transition_strategy(registry_root, "test-001", "CANDIDATE", actor="atlas")
    # Same transition again should be idempotent
    entry = transition_strategy(registry_root, "test-001", "CANDIDATE", actor="atlas")
    assert entry.lifecycle_state == "CANDIDATE"
    # Should not add duplicate history entry
    assert len(entry.state_history) == 2


def test_full_lifecycle_walk(registry_root):
    """Walk through: IDEA → CANDIDATE → VALIDATING → PROMOTED → PAPER_QUEUED."""
    create_strategy(registry_root, "test-001", actor="atlas")
    transition_strategy(registry_root, "test-001", "CANDIDATE", actor="atlas")
    transition_strategy(registry_root, "test-001", "VALIDATING", actor="sigma")
    transition_strategy(registry_root, "test-001", "PROMOTED", actor="sigma")
    entry = transition_strategy(registry_root, "test-001", "PAPER_QUEUED", actor="kitt",
                                approval_ref="approval-2026-03-18-001")
    assert entry.lifecycle_state == "PAPER_QUEUED"
    assert len(entry.state_history) == 5
