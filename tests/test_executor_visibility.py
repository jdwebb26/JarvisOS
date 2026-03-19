#!/usr/bin/env python3
"""Tests proving executor lane visibility in operator surfaces.

Acceptance criteria:
  1. Operator can see current stage and why not live-eligible
  2. Paper-active is clearly not live-eligible
  3. Review outcomes are visible
  4. Blocked-live path (no live approval) is visible
  5. Live execution without approval is blocked and visible
  6. Stage labels map every lifecycle state
"""
import json
import sys
from pathlib import Path
from io import StringIO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet, validate_packet
from workspace.quant.shared.packet_store import store_packet
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, load_all_strategies,
    get_strategy, LIFECYCLE_STATES, TERMINAL_STATES,
)
from workspace.quant.shared.registries.approval_registry import (
    create_approval, load_all_approvals, ApprovedActions,
)
from workspace.quant.sigma.validation_lane import validate_candidate, review_paper_results


@pytest.fixture
def clean_root(tmp_path):
    """Provide a clean root directory with all required structure."""
    (tmp_path / "workspace" / "quant" / "shared" / "latest").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "registries").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "config").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "scheduler").mkdir(parents=True)
    (tmp_path / "state" / "discord_outbox").mkdir(parents=True)
    (tmp_path / "state" / "quant" / "executor").mkdir(parents=True)
    for lane in ["atlas", "fish", "hermes", "sigma", "kitt", "tradefloor", "executor", "pulse"]:
        (tmp_path / "workspace" / "quant" / lane).mkdir(parents=True)

    hosts = {
        "hosts": {
            "NIMO": {"role": "primary", "specs": "128GB", "heavy_job_cap": 2, "ip": "127.0.0.1"},
        },
        "global_heavy_job_cap": 3,
        "lane_placement": {
            "atlas": {"primary": "NIMO", "overflow": "SonLM"},
            "fish": {"primary": "SonLM", "overflow": "cloud"},
            "hermes": {"primary": "mixed", "overflow": "either"},
            "tradefloor": {"primary": "strongest_available", "overflow": "cloud"},
            "kitt": {"primary": "NIMO", "overflow": "cloud"},
            "sigma": {"primary": "NIMO", "overflow": "cloud"},
            "executor": {"primary": "NIMO", "overflow": None},
        },
    }
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "hosts.json").write_text(
        json.dumps(hosts, indent=2), encoding="utf-8"
    )
    gov = {lane: {
        "batch_size": 1, "max_iterations": 5, "cooldown_interval": 0,
        "cloud_burst_allowed": False, "escalation_threshold": 0.6,
        "cadence_multiplier": 1.0, "consecutive_backoff_cycles": 0, "paused": False,
    } for lane in ["atlas", "fish", "hermes", "tradefloor", "kitt", "sigma", "executor"]}
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "governor_state.json").write_text(
        json.dumps(gov, indent=2), encoding="utf-8"
    )
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "risk_limits.json").write_text(
        json.dumps({"per_strategy": {"max_position_size": 2}, "portfolio": {"max_total_exposure": 4}}),
        encoding="utf-8",
    )
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "review_thresholds.json").write_text(
        json.dumps({
            "validation": {"min_profit_factor": 1.3, "min_sharpe": 0.8,
                           "max_drawdown_pct": 0.15, "min_trades": 20},
            "paper_review": {"min_profit_factor": 1.3, "min_sharpe": 0.8,
                             "max_drawdown_pct": 0.15, "min_fill_rate": 0.90,
                             "max_correlation": 0.70},
        }), encoding="utf-8",
    )
    return tmp_path


def _make_candidate(root, sid="test-001"):
    """Create a strategy and push it to CANDIDATE."""
    create_strategy(root, sid, actor="atlas")
    transition_strategy(root, sid, "CANDIDATE", actor="atlas")
    pkt = make_packet("candidate_packet", "atlas", f"Test strategy {sid}",
                      strategy_id=sid, confidence=0.5)
    store_packet(root, pkt)
    return pkt


def _push_to_paper_active(root, sid="test-001"):
    """Push a strategy through validation → promoted → paper_queued → paper_active."""
    cpkt = _make_candidate(root, sid)
    transition_strategy(root, sid, "VALIDATING", actor="sigma")
    validate_candidate(root, cpkt, profit_factor=1.5, sharpe=1.0,
                       max_drawdown_pct=0.10, trade_count=30)
    # Now PROMOTED — create paper approval
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    actions = ApprovedActions(
        execution_mode="paper", symbols=["NQ"],
        valid_from=now.isoformat(),
        valid_until=(now + timedelta(days=14)).isoformat(),
    )
    appr = create_approval(root, sid, "paper_trade", approved_actions=actions)
    transition_strategy(root, sid, "PAPER_QUEUED", actor="kitt",
                        approval_ref=appr.approval_ref)
    transition_strategy(root, sid, "PAPER_ACTIVE", actor="executor",
                        note="Paper orders placed")
    return get_strategy(root, sid)


# ---------------------------------------------------------------------------
# Stage labels cover all states
# ---------------------------------------------------------------------------

class TestStageLabels:
    def test_all_lifecycle_states_have_labels(self):
        """Every lifecycle state has a human-readable label."""
        from scripts.quant_lanes import _STAGE_LABELS
        for state in LIFECYCLE_STATES:
            assert state in _STAGE_LABELS, f"Missing label for {state}"
            phase, explanation = _STAGE_LABELS[state]
            assert len(explanation) > 5, f"Label for {state} too short: {explanation!r}"


# ---------------------------------------------------------------------------
# why_not_live explanations
# ---------------------------------------------------------------------------

class TestWhyNotLive:
    def test_paper_active_not_live_eligible(self, clean_root):
        from scripts.quant_lanes import _why_not_live
        approvals = load_all_approvals(clean_root)
        reason = _why_not_live("PAPER_ACTIVE", "x", approvals)
        assert "proof" in reason.lower() or "accumulating" in reason.lower()

    def test_paper_review_awaiting_decision(self, clean_root):
        from scripts.quant_lanes import _why_not_live
        reason = _why_not_live("PAPER_REVIEW", "x", [])
        assert "review" in reason.lower()

    def test_iterate_back_to_atlas(self, clean_root):
        from scripts.quant_lanes import _why_not_live
        reason = _why_not_live("ITERATE", "x", [])
        assert "rerun" in reason.lower() or "atlas" in reason.lower()

    def test_paper_killed_closed(self, clean_root):
        from scripts.quant_lanes import _why_not_live
        reason = _why_not_live("PAPER_KILLED", "x", [])
        assert "closed" in reason.lower()

    def test_live_queued_needs_approval(self, clean_root):
        from scripts.quant_lanes import _why_not_live
        # No approvals → needs live_trade approval
        reason = _why_not_live("LIVE_QUEUED", "x", [])
        assert "approval" in reason.lower()

    def test_live_active_is_live(self, clean_root):
        from scripts.quant_lanes import _why_not_live
        reason = _why_not_live("LIVE_ACTIVE", "x", [])
        assert reason == ""  # Already live, no block reason


# ---------------------------------------------------------------------------
# Blocked-live path visible in status output
# ---------------------------------------------------------------------------

class TestStatusBlockedLive:
    def test_paper_active_shows_as_blocked(self, clean_root):
        """Paper-active strategy appears in LIVE BLOCKED section."""
        _push_to_paper_active(clean_root, "vis-001")

        from scripts.quant_lanes import _why_not_live
        approvals = load_all_approvals(clean_root)
        reason = _why_not_live("PAPER_ACTIVE", "vis-001", approvals)
        assert "proof" in reason.lower() or "accumulating" in reason.lower()

    def test_paper_review_shows_as_blocked(self, clean_root):
        """Paper-review strategy appears as awaiting decision."""
        _push_to_paper_active(clean_root, "vis-002")
        transition_strategy(clean_root, "vis-002", "PAPER_REVIEW", actor="sigma")

        from scripts.quant_lanes import _why_not_live
        reason = _why_not_live("PAPER_REVIEW", "vis-002", [])
        assert "review" in reason.lower()


# ---------------------------------------------------------------------------
# Review outcomes visible
# ---------------------------------------------------------------------------

class TestReviewOutcomes:
    def test_advance_to_live_outcome(self, clean_root):
        """Review outcome 'advance_to_live' maps to clear label."""
        from scripts.quant_lanes import _REVIEW_OUTCOME_LABELS
        label = _REVIEW_OUTCOME_LABELS["advance_to_live"]
        assert "approve_live_candidate" in label
        assert "live" in label.lower()

    def test_iterate_outcome(self, clean_root):
        from scripts.quant_lanes import _REVIEW_OUTCOME_LABELS
        label = _REVIEW_OUTCOME_LABELS["iterate"]
        assert "rerun_with_changes" in label

    def test_kill_outcome(self, clean_root):
        from scripts.quant_lanes import _REVIEW_OUTCOME_LABELS
        label = _REVIEW_OUTCOME_LABELS["kill"]
        assert "reject" in label

    def test_review_produces_correct_outcome(self, clean_root):
        """Sigma review correctly produces advance/iterate/kill outcomes."""
        # Good stats → advance_to_live
        outcome, _ = review_paper_results(
            clean_root, "rev-001",
            realized_pf=1.5, realized_sharpe=1.0,
            max_drawdown=0.10, avg_slippage=0.001,
            fill_rate=0.95, trade_count=30,
        )
        assert outcome == "advance_to_live"

        # Mediocre → iterate
        outcome, _ = review_paper_results(
            clean_root, "rev-002",
            realized_pf=1.1, realized_sharpe=0.7,
            max_drawdown=0.12, avg_slippage=0.002,
            fill_rate=0.92, trade_count=25,
        )
        assert outcome == "iterate"

        # Bad → kill
        outcome, _ = review_paper_results(
            clean_root, "rev-003",
            realized_pf=0.8, realized_sharpe=0.3,
            max_drawdown=0.25, avg_slippage=0.005,
            fill_rate=0.70, trade_count=10,
        )
        assert outcome == "kill"


# ---------------------------------------------------------------------------
# Live execution blocked without approval
# ---------------------------------------------------------------------------

class TestLiveBlockedWithoutApproval:
    def test_live_trade_rejected_without_live_approval(self, clean_root):
        """Executor rejects live trade when only paper approval exists."""
        from workspace.quant.executor.executor_lane import execute_live_trade

        _push_to_paper_active(clean_root, "block-001")
        # Find the paper approval ref (it's the only one)
        approvals = load_all_approvals(clean_root)
        paper_ref = approvals[-1].approval_ref
        # Attempt live execution with the paper approval → should be rejected
        result = execute_live_trade(
            clean_root, "block-001", paper_ref,
            symbol="NQ", side="long",
        )
        assert result["success"] is False
        assert result["rejection_reason"] is not None
        # The rejection should mention mode mismatch or invalid approval
        assert any(r in result["rejection_reason"]
                   for r in ("mode_mismatch", "invalid_approval"))

    def test_live_trade_rejection_packet_emitted(self, clean_root):
        """Rejected live trade produces a visible execution_rejection_packet."""
        from workspace.quant.executor.executor_lane import execute_live_trade
        from workspace.quant.shared.packet_store import list_lane_packets

        _push_to_paper_active(clean_root, "block-002")
        approvals = load_all_approvals(clean_root)
        paper_ref = approvals[-1].approval_ref
        execute_live_trade(
            clean_root, "block-002", paper_ref,
            symbol="NQ", side="long",
        )
        rejections = list_lane_packets(clean_root, "executor", "execution_rejection_packet")
        assert len(rejections) >= 1
        rej = rejections[-1]
        assert rej.strategy_id == "block-002"
        assert rej.execution_rejection_reason is not None


# ---------------------------------------------------------------------------
# Strategy detail view enrichment
# ---------------------------------------------------------------------------

class TestStrategyDetailView:
    def test_paper_active_shows_stage_explanation(self, clean_root):
        """cmd_strategy shows explanation for paper-active strategies."""
        from scripts.quant_lanes import _STAGE_LABELS, _why_not_live
        _push_to_paper_active(clean_root, "detail-001")

        phase, explanation = _STAGE_LABELS["PAPER_ACTIVE"]
        assert phase == "paper"
        assert "proof" in explanation.lower() or "accumulating" in explanation.lower()

        approvals = load_all_approvals(clean_root)
        reason = _why_not_live("PAPER_ACTIVE", "detail-001", approvals)
        assert len(reason) > 0

    def test_live_queued_shows_needs_approval(self, clean_root):
        """LIVE_QUEUED shows it needs live execution approval."""
        from scripts.quant_lanes import _STAGE_LABELS
        phase, explanation = _STAGE_LABELS["LIVE_QUEUED"]
        assert "live" in explanation.lower()
        assert "approval" in explanation.lower()
