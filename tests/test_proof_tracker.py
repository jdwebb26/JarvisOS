#!/usr/bin/env python3
"""Tests for executor proof tracker — paper run lifecycle, proof metrics,
promotion gating, and live execution blocking.

Proves:
  1. Paper run lifecycle (create, record fills, status transitions)
  2. Proof metric accumulation (win_rate, expectancy, drawdown, consecutive losses)
  3. Strategy-specific proof windows (different profiles, different thresholds)
  4. Promotion packet generation when proof is sufficient
  5. Blocked live path without approval
  6. Approved vs rejected promotion behavior
  7. Proof evaluation correctly checks all criteria
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.executor.proof_tracker import (
    ProofProfile, PaperRun, PromotionReview, LiveExecRequest,
    DEFAULT_PROFILES, load_proof_profiles, get_proof_profile,
    create_paper_run, save_paper_run, load_paper_run, get_active_run,
    list_paper_runs, record_fill, evaluate_proof,
    create_promotion_review, decide_promotion, request_live_execution,
)


@pytest.fixture
def clean_root(tmp_path):
    (tmp_path / "workspace" / "quant" / "shared" / "latest").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "config").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "executor" / "paper_runs").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "executor" / "promotions").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "sigma").mkdir(parents=True)
    return tmp_path


# ---- Proof profiles ----

class TestProofProfiles:
    def test_default_profiles_exist(self):
        assert "scalp" in DEFAULT_PROFILES
        assert "intraday" in DEFAULT_PROFILES
        assert "swing" in DEFAULT_PROFILES
        assert "event" in DEFAULT_PROFILES

    def test_profiles_have_distinct_thresholds(self):
        scalp = DEFAULT_PROFILES["scalp"]
        swing = DEFAULT_PROFILES["swing"]
        assert scalp.min_trades_required > swing.min_trades_required
        assert scalp.min_days_required < swing.min_days_required

    def test_load_from_config(self, clean_root):
        custom = {"custom": {"time_horizon_class": "custom", "min_trades_required": 100,
                              "min_days_required": 30, "min_expectancy": 2.0,
                              "max_drawdown": 500.0, "max_consecutive_losses": 2}}
        path = clean_root / "workspace" / "quant" / "shared" / "config" / "proof_profiles.json"
        path.write_text(json.dumps(custom), encoding="utf-8")
        profiles = load_proof_profiles(clean_root)
        assert "custom" in profiles
        assert profiles["custom"].min_trades_required == 100

    def test_invalid_horizon_raises(self, clean_root):
        with pytest.raises(ValueError, match="Unknown horizon_class"):
            get_proof_profile(clean_root, "invalid")


# ---- Paper run lifecycle ----

class TestPaperRunLifecycle:
    def test_create_paper_run(self, clean_root):
        run = create_paper_run(clean_root, "strat-001", "intraday")
        assert run.strategy_id == "strat-001"
        assert run.status == "paper_active"
        assert run.horizon_class == "intraday"
        assert run.entry_count == 0
        assert run.proof_status == "accumulating"

    def test_load_paper_run(self, clean_root):
        run = create_paper_run(clean_root, "strat-002", "swing")
        loaded = load_paper_run(clean_root, run.paper_run_id)
        assert loaded is not None
        assert loaded.strategy_id == "strat-002"

    def test_get_active_run(self, clean_root):
        run = create_paper_run(clean_root, "strat-003", "scalp")
        active = get_active_run(clean_root, "strat-003")
        assert active is not None
        assert active.paper_run_id == run.paper_run_id

    def test_no_active_run(self, clean_root):
        assert get_active_run(clean_root, "nonexistent") is None

    def test_list_paper_runs(self, clean_root):
        create_paper_run(clean_root, "strat-a", "scalp")
        create_paper_run(clean_root, "strat-b", "swing")
        runs = list_paper_runs(clean_root)
        assert len(runs) == 2


# ---- Proof metric accumulation ----

class TestMetricAccumulation:
    def test_record_winning_fill(self, clean_root):
        run = create_paper_run(clean_root, "metrics-001", "intraday")
        updated = record_fill(clean_root, run.paper_run_id, pnl=50.0, is_winner=True)
        assert updated.entry_count == 1
        assert updated.closed_count == 1
        assert updated.win_count == 1
        assert updated.loss_count == 0
        assert updated.realized_pnl == 50.0
        assert updated.win_rate == 1.0
        assert updated.expectancy == 50.0

    def test_record_losing_fill(self, clean_root):
        run = create_paper_run(clean_root, "metrics-002", "intraday")
        updated = record_fill(clean_root, run.paper_run_id, pnl=-30.0, is_winner=False)
        assert updated.win_count == 0
        assert updated.loss_count == 1
        assert updated.consecutive_losses == 1
        assert updated.win_rate == 0.0

    def test_mixed_fills(self, clean_root):
        run = create_paper_run(clean_root, "metrics-003", "intraday")
        record_fill(clean_root, run.paper_run_id, 50.0, True)
        record_fill(clean_root, run.paper_run_id, -20.0, False)
        updated = record_fill(clean_root, run.paper_run_id, 30.0, True)
        assert updated.win_count == 2
        assert updated.loss_count == 1
        assert updated.win_rate == pytest.approx(0.6667, abs=0.01)
        assert updated.expectancy == pytest.approx(20.0, abs=0.1)  # 60/3

    def test_consecutive_losses_tracked(self, clean_root):
        run = create_paper_run(clean_root, "metrics-004", "intraday")
        record_fill(clean_root, run.paper_run_id, 50.0, True)
        record_fill(clean_root, run.paper_run_id, -10.0, False)
        record_fill(clean_root, run.paper_run_id, -10.0, False)
        updated = record_fill(clean_root, run.paper_run_id, -10.0, False)
        assert updated.consecutive_losses == 3
        assert updated.max_consecutive_losses == 3
        # Win resets consecutive
        updated2 = record_fill(clean_root, run.paper_run_id, 50.0, True)
        assert updated2.consecutive_losses == 0
        assert updated2.max_consecutive_losses == 3  # Still tracks the max

    def test_drawdown_tracked(self, clean_root):
        run = create_paper_run(clean_root, "metrics-005", "intraday")
        record_fill(clean_root, run.paper_run_id, -100.0, False)
        record_fill(clean_root, run.paper_run_id, -200.0, False)
        updated = record_fill(clean_root, run.paper_run_id, 50.0, True)
        assert updated.max_drawdown >= 250.0  # Worst point was -300 total


# ---- Proof evaluation with strategy-specific windows ----

class TestProofEvaluation:
    def _build_passing_run(self, root, strategy_id, horizon, num_trades, num_wins):
        run = create_paper_run(root, strategy_id, horizon)
        run.started_at = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        save_paper_run(root, run)
        # Interleave wins and losses to keep consecutive losses low
        num_losses = num_trades - num_wins
        wins_left, losses_left = num_wins, num_losses
        for i in range(num_trades):
            if wins_left > 0 and (losses_left == 0 or i % 3 != 2):
                record_fill(root, run.paper_run_id, 2.0, True)
                wins_left -= 1
            else:
                record_fill(root, run.paper_run_id, -0.5, False)
                losses_left -= 1
        return run

    def test_sufficient_proof(self, clean_root):
        run = self._build_passing_run(clean_root, "eval-001", "intraday", 35, 25)
        result = evaluate_proof(clean_root, run.paper_run_id)
        assert result["sufficient"] is True
        assert all(c["met"] for c in result["criteria"].values())
        reloaded = load_paper_run(clean_root, run.paper_run_id)
        assert reloaded.status == "paper_proof_ready"

    def test_insufficient_trades(self, clean_root):
        run = create_paper_run(clean_root, "eval-002", "intraday")
        run.started_at = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        save_paper_run(clean_root, run)
        record_fill(clean_root, run.paper_run_id, 50.0, True)
        result = evaluate_proof(clean_root, run.paper_run_id)
        assert result["sufficient"] is False
        assert not result["criteria"]["min_trades"]["met"]

    def test_scalp_vs_swing_different_thresholds(self, clean_root):
        """Same trade count passes swing but not scalp."""
        # Swing needs 15 trades; scalp needs 50
        run_swing = self._build_passing_run(clean_root, "swing-001", "swing", 20, 15)
        run_scalp = create_paper_run(clean_root, "scalp-001", "scalp")
        run_scalp.started_at = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        save_paper_run(clean_root, run_scalp)
        for i in range(20):
            record_fill(clean_root, run_scalp.paper_run_id, 1.0, True)

        eval_swing = evaluate_proof(clean_root, run_swing.paper_run_id)
        eval_scalp = evaluate_proof(clean_root, run_scalp.paper_run_id)
        assert eval_swing["sufficient"] is True
        assert eval_scalp["sufficient"] is False

    def test_insufficient_days(self, clean_root):
        run = create_paper_run(clean_root, "eval-003", "intraday")
        # Don't backdate — started now, needs 10 days
        for i in range(35):
            record_fill(clean_root, run.paper_run_id, 1.0, True)
        result = evaluate_proof(clean_root, run.paper_run_id)
        assert not result["criteria"]["min_days"]["met"]


# ---- Promotion ----

class TestPromotion:
    def _build_proven_run(self, root, strategy_id="promo-001"):
        run = create_paper_run(root, strategy_id, "intraday")
        run.started_at = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        save_paper_run(root, run)
        # Interleave: 2 wins then 1 loss to keep consecutive losses low
        wins, losses = 25, 10
        for i in range(35):
            if wins > 0 and (losses == 0 or i % 3 != 2):
                record_fill(root, run.paper_run_id, 2.0, True)
                wins -= 1
            else:
                record_fill(root, run.paper_run_id, -0.5, False)
                losses -= 1
        return run

    def test_create_promotion_review(self, clean_root):
        run = self._build_proven_run(clean_root)
        promo, pkt = create_promotion_review(clean_root, run.paper_run_id)
        assert promo.status == "pending"
        assert promo.strategy_id == "promo-001"
        assert promo.recommended_action == "promote_to_live"
        assert pkt.packet_type == "paper_review_packet"
        assert pkt.strategy_id == "promo-001"

    def test_promotion_blocked_if_insufficient(self, clean_root):
        run = create_paper_run(clean_root, "promo-fail", "intraday")
        with pytest.raises(ValueError, match="Proof insufficient"):
            create_promotion_review(clean_root, run.paper_run_id)

    def test_approve_promotion(self, clean_root):
        run = self._build_proven_run(clean_root, "promo-approve")
        promo, _ = create_promotion_review(clean_root, run.paper_run_id)
        decided = decide_promotion(clean_root, promo.promotion_id, "approved", "Looks good")
        assert decided.status == "approved"
        reloaded = load_paper_run(clean_root, run.paper_run_id)
        assert reloaded.status == "live_ready"

    def test_reject_promotion(self, clean_root):
        run = self._build_proven_run(clean_root, "promo-reject")
        promo, _ = create_promotion_review(clean_root, run.paper_run_id)
        decided = decide_promotion(clean_root, promo.promotion_id, "rejected", "Needs more data")
        assert decided.status == "rejected"
        reloaded = load_paper_run(clean_root, run.paper_run_id)
        assert reloaded.status == "review_rejected"

    def test_rerun_paper(self, clean_root):
        run = self._build_proven_run(clean_root, "promo-rerun")
        promo, _ = create_promotion_review(clean_root, run.paper_run_id)
        decided = decide_promotion(clean_root, promo.promotion_id, "rerun_paper", "Try different regime")
        assert decided.status == "rerun_paper"
        reloaded = load_paper_run(clean_root, run.paper_run_id)
        assert reloaded.status == "paper_active"


# ---- Live execution gating ----

class TestLiveGating:
    def _create_approved_promotion(self, root, strategy_id="live-001"):
        run = create_paper_run(root, strategy_id, "intraday")
        run.started_at = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        save_paper_run(root, run)
        wins, losses = 25, 10
        for i in range(35):
            if wins > 0 and (losses == 0 or i % 3 != 2):
                record_fill(root, run.paper_run_id, 2.0, True)
                wins -= 1
            else:
                record_fill(root, run.paper_run_id, -0.5, False)
                losses -= 1
        promo, _ = create_promotion_review(root, run.paper_run_id)
        decide_promotion(root, promo.promotion_id, "approved")
        return promo

    def test_live_request_with_approved_promotion(self, clean_root):
        promo = self._create_approved_promotion(clean_root)
        req = request_live_execution(
            clean_root, "live-001", promo.promotion_id,
            operator_approval_ref="qpt_test123",
        )
        assert req.status == "pending"
        assert req.strategy_id == "live-001"
        assert req.approved_promotion_id == promo.promotion_id

    def test_live_blocked_without_approval(self, clean_root):
        """Pending promotion cannot produce a live request."""
        run = create_paper_run(clean_root, "live-blocked", "intraday")
        run.started_at = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        save_paper_run(clean_root, run)
        wins, losses = 25, 10
        for i in range(35):
            if wins > 0 and (losses == 0 or i % 3 != 2):
                record_fill(clean_root, run.paper_run_id, 2.0, True)
                wins -= 1
            else:
                record_fill(clean_root, run.paper_run_id, -0.5, False)
                losses -= 1
        promo, _ = create_promotion_review(clean_root, run.paper_run_id)
        # Promotion is pending — NOT approved
        with pytest.raises(ValueError, match="not approved"):
            request_live_execution(
                clean_root, "live-blocked", promo.promotion_id,
                operator_approval_ref="qpt_test",
            )

    def test_live_blocked_after_rejection(self, clean_root):
        run = create_paper_run(clean_root, "live-rejected", "intraday")
        run.started_at = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        save_paper_run(clean_root, run)
        wins, losses = 25, 10
        for i in range(35):
            if wins > 0 and (losses == 0 or i % 3 != 2):
                record_fill(clean_root, run.paper_run_id, 2.0, True)
                wins -= 1
            else:
                record_fill(clean_root, run.paper_run_id, -0.5, False)
                losses -= 1
        promo, _ = create_promotion_review(clean_root, run.paper_run_id)
        decide_promotion(clean_root, promo.promotion_id, "rejected")
        with pytest.raises(ValueError, match="not approved"):
            request_live_execution(
                clean_root, "live-rejected", promo.promotion_id,
                operator_approval_ref="qpt_test",
            )

    def test_live_requires_operator_approval_ref(self, clean_root):
        promo = self._create_approved_promotion(clean_root, "live-noref")
        with pytest.raises(ValueError, match="operator_approval_ref"):
            request_live_execution(
                clean_root, "live-noref", promo.promotion_id,
                operator_approval_ref="",
            )

    def test_live_wrong_strategy_blocked(self, clean_root):
        promo = self._create_approved_promotion(clean_root, "live-right")
        with pytest.raises(ValueError, match="not live-wrong"):
            request_live_execution(
                clean_root, "live-wrong", promo.promotion_id,
                operator_approval_ref="qpt_test",
            )
