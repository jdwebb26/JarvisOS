#!/usr/bin/env python3
"""Tests for Sigma validation lane."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet
from workspace.quant.shared.registries.strategy_registry import create_strategy, transition_strategy, get_strategy
from workspace.quant.sigma.validation_lane import validate_candidate, review_paper_results


@pytest.fixture
def sigma_root(tmp_path):
    for d in ["workspace/quant/shared/registries",
              "workspace/quant/shared/latest",
              "workspace/quant/sigma"]:
        (tmp_path / d).mkdir(parents=True)
    return tmp_path


def _make_candidate(root, strategy_id="test-001"):
    create_strategy(root, strategy_id, actor="atlas")
    transition_strategy(root, strategy_id, "CANDIDATE", actor="atlas")
    transition_strategy(root, strategy_id, "VALIDATING", actor="sigma")
    return make_packet("candidate_packet", "atlas", "test candidate", strategy_id=strategy_id)


def test_validate_promotes_good_candidate(sigma_root):
    candidate = _make_candidate(sigma_root)
    outcome, pkt = validate_candidate(
        sigma_root, candidate,
        profit_factor=1.7, sharpe=1.1, max_drawdown_pct=0.06, trade_count=50,
    )
    assert outcome == "promoted"
    s = get_strategy(sigma_root, "test-001")
    assert s.lifecycle_state == "PROMOTED"


def test_validate_rejects_low_pf(sigma_root):
    candidate = _make_candidate(sigma_root)
    outcome, pkt = validate_candidate(
        sigma_root, candidate,
        profit_factor=0.9, sharpe=1.1, max_drawdown_pct=0.06, trade_count=50,
    )
    assert outcome == "rejected"
    assert pkt.rejection_reason == "poor_oos"
    s = get_strategy(sigma_root, "test-001")
    assert s.lifecycle_state == "REJECTED"


def test_validate_rejects_high_drawdown(sigma_root):
    candidate = _make_candidate(sigma_root)
    outcome, pkt = validate_candidate(
        sigma_root, candidate,
        profit_factor=1.5, sharpe=1.0, max_drawdown_pct=0.25, trade_count=50,
    )
    assert outcome == "rejected"
    assert pkt.rejection_reason == "excessive_drawdown"


def test_validate_rejects_insufficient_trades(sigma_root):
    candidate = _make_candidate(sigma_root)
    outcome, pkt = validate_candidate(
        sigma_root, candidate,
        profit_factor=1.5, sharpe=1.0, max_drawdown_pct=0.05, trade_count=5,
    )
    assert outcome == "rejected"
    assert pkt.rejection_reason == "insufficient_trades"


def test_validate_requires_strategy_id(sigma_root):
    bad = make_packet("candidate_packet", "atlas", "no strategy id")
    with pytest.raises(ValueError, match="strategy_id"):
        validate_candidate(sigma_root, bad, 1.5, 1.0, 0.05, 50)


# --- Paper Review Tests ---

def test_review_advance(sigma_root):
    outcome, pkt = review_paper_results(
        sigma_root, "test-001",
        realized_pf=1.5, realized_sharpe=1.0, max_drawdown=0.05,
        avg_slippage=0.02, fill_rate=0.95, trade_count=30,
    )
    assert outcome == "advance_to_live"


def test_review_iterate(sigma_root):
    outcome, pkt = review_paper_results(
        sigma_root, "test-001",
        realized_pf=1.1, realized_sharpe=0.9, max_drawdown=0.05,
        avg_slippage=0.02, fill_rate=0.95, trade_count=30,
    )
    assert outcome == "iterate"
    assert pkt.iteration_guidance is not None


def test_review_kill(sigma_root):
    outcome, pkt = review_paper_results(
        sigma_root, "test-001",
        realized_pf=0.7, realized_sharpe=0.3, max_drawdown=0.20,
        avg_slippage=0.10, fill_rate=0.80, trade_count=30,
    )
    assert outcome == "kill"
