#!/usr/bin/env python3
"""Tests proving automatic proof-ready promotion and paper-run reconciliation.

Acceptance criteria:
  1. reconcile_paper_runs creates runs for PAPER_ACTIVE strategies without one
  2. reconcile is idempotent — skips strategies that already have runs
  3. When proof becomes sufficient, strategy auto-transitions PAPER_ACTIVE → PAPER_REVIEW
  4. Non-ready runs stay PAPER_ACTIVE
  5. No live execution happens automatically — review is still required
  6. Auto-promotion uses actor="sigma" (the validation gatekeeper)
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet
from workspace.quant.shared.packet_store import store_packet
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, get_strategy,
)
from workspace.quant.shared.registries.approval_registry import (
    create_approval, ApprovedActions,
)
from workspace.quant.sigma.validation_lane import validate_candidate
from workspace.quant.executor.executor_lane import (
    execute_paper_trade, reconcile_paper_runs, _infer_horizon_class,
)
from workspace.quant.executor.proof_tracker import (
    get_active_run, load_paper_run, record_fill, evaluate_proof, save_paper_run,
)


@pytest.fixture
def clean_root(tmp_path):
    (tmp_path / "workspace" / "quant" / "shared" / "latest").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "registries").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "config").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "scheduler").mkdir(parents=True)
    (tmp_path / "state" / "quant" / "executor").mkdir(parents=True)
    for lane in ["atlas", "fish", "hermes", "sigma", "kitt", "tradefloor", "executor"]:
        (tmp_path / "workspace" / "quant" / lane).mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "executor" / "paper_runs").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "executor" / "promotions").mkdir(parents=True)

    hosts = {
        "hosts": {"NIMO": {"role": "primary", "specs": "128GB", "heavy_job_cap": 2, "ip": "127.0.0.1"}},
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
        json.dumps(hosts, indent=2), encoding="utf-8")
    gov = {lane: {
        "batch_size": 1, "max_iterations": 5, "cooldown_interval": 0,
        "cloud_burst_allowed": False, "escalation_threshold": 0.6,
        "cadence_multiplier": 1.0, "consecutive_backoff_cycles": 0, "paused": False,
    } for lane in ["atlas", "fish", "hermes", "tradefloor", "kitt", "sigma", "executor"]}
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "governor_state.json").write_text(
        json.dumps(gov, indent=2), encoding="utf-8")
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "risk_limits.json").write_text(
        json.dumps({"per_strategy": {"max_position_size": 2},
                     "portfolio": {"max_total_exposure": 4}}), encoding="utf-8")
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "review_thresholds.json").write_text(
        json.dumps({
            "validation": {"min_profit_factor": 1.3, "min_sharpe": 0.8,
                           "max_drawdown_pct": 0.15, "min_trades": 20},
            "paper_review": {"min_profit_factor": 1.3, "min_sharpe": 0.8,
                             "max_drawdown_pct": 0.15, "min_fill_rate": 0.90,
                             "max_correlation": 0.70},
        }), encoding="utf-8")
    return tmp_path


def _push_to_paper_active(root, sid):
    """Create strategy, validate, approve, place paper, return approval_ref."""
    create_strategy(root, sid, actor="atlas")
    transition_strategy(root, sid, "CANDIDATE", actor="atlas")
    cpkt = make_packet("candidate_packet", "atlas", f"Strategy {sid}",
                       strategy_id=sid, confidence=0.5,
                       timeframe_scope="15m", symbol_scope="NQ")
    store_packet(root, cpkt)
    transition_strategy(root, sid, "VALIDATING", actor="sigma")
    validate_candidate(root, cpkt, profit_factor=1.5, sharpe=1.0,
                       max_drawdown_pct=0.10, trade_count=30)
    now = datetime.now(timezone.utc)
    actions = ApprovedActions(
        execution_mode="paper", symbols=["NQ"],
        valid_from=now.isoformat(),
        valid_until=(now + timedelta(days=14)).isoformat(),
    )
    appr = create_approval(root, sid, "paper_trade", approved_actions=actions)
    transition_strategy(root, sid, "PAPER_QUEUED", actor="kitt",
                        approval_ref=appr.approval_ref)
    # First fill transitions to PAPER_ACTIVE and creates paper run
    execute_paper_trade(root, sid, appr.approval_ref, symbol="NQ", side="long")
    return appr.approval_ref


def _push_to_paper_active_no_run(root, sid):
    """Create a PAPER_ACTIVE strategy WITHOUT a paper run (simulates legacy state)."""
    create_strategy(root, sid, actor="atlas")
    transition_strategy(root, sid, "CANDIDATE", actor="atlas")
    cpkt = make_packet("candidate_packet", "atlas", f"Strategy {sid}",
                       strategy_id=sid, confidence=0.5,
                       timeframe_scope="15m", symbol_scope="NQ")
    store_packet(root, cpkt)
    transition_strategy(root, sid, "VALIDATING", actor="sigma")
    validate_candidate(root, cpkt, profit_factor=1.5, sharpe=1.0,
                       max_drawdown_pct=0.10, trade_count=30)
    now = datetime.now(timezone.utc)
    actions = ApprovedActions(
        execution_mode="paper", symbols=["NQ"],
        valid_from=now.isoformat(),
        valid_until=(now + timedelta(days=14)).isoformat(),
    )
    appr = create_approval(root, sid, "paper_trade", approved_actions=actions)
    transition_strategy(root, sid, "PAPER_QUEUED", actor="kitt",
                        approval_ref=appr.approval_ref)
    # Manually transition to PAPER_ACTIVE without going through execute_paper_trade
    transition_strategy(root, sid, "PAPER_ACTIVE", actor="executor",
                        note="Legacy transition without proof tracking")
    return appr.approval_ref


# ---------------------------------------------------------------------------
# Reconcile
# ---------------------------------------------------------------------------

class TestReconcile:
    def test_creates_run_for_missing_strategy(self, clean_root):
        """reconcile_paper_runs creates a run for PAPER_ACTIVE with no run."""
        _push_to_paper_active_no_run(clean_root, "recon-001")
        assert get_active_run(clean_root, "recon-001") is None

        created = reconcile_paper_runs(clean_root)
        assert len(created) == 1
        assert created[0]["strategy_id"] == "recon-001"

        run = get_active_run(clean_root, "recon-001")
        assert run is not None
        assert run.strategy_id == "recon-001"

    def test_idempotent(self, clean_root):
        """Second reconcile skips strategies that already have runs."""
        _push_to_paper_active_no_run(clean_root, "recon-002")
        r1 = reconcile_paper_runs(clean_root)
        assert len(r1) == 1

        r2 = reconcile_paper_runs(clean_root)
        assert len(r2) == 0

    def test_skips_strategies_with_existing_run(self, clean_root):
        """Strategies created via execute_paper_trade already have runs."""
        _push_to_paper_active(clean_root, "recon-003")
        assert get_active_run(clean_root, "recon-003") is not None

        created = reconcile_paper_runs(clean_root)
        assert all(c["strategy_id"] != "recon-003" for c in created)

    def test_multiple_missing(self, clean_root):
        """Reconcile handles multiple missing strategies."""
        _push_to_paper_active_no_run(clean_root, "recon-m1")
        _push_to_paper_active_no_run(clean_root, "recon-m2")
        created = reconcile_paper_runs(clean_root)
        assert len(created) == 2
        sids = {c["strategy_id"] for c in created}
        assert sids == {"recon-m1", "recon-m2"}


# ---------------------------------------------------------------------------
# Auto-promote on proof sufficient
# ---------------------------------------------------------------------------

class TestAutoPromote:
    def _make_sufficient_run(self, root, sid, ref):
        """Fast-forward a paper run to sufficient proof and evaluate it.

        After this call, the run is in paper_proof_ready status with
        proof_status=sufficient. The next fill will trigger auto-promote.
        """
        run = get_active_run(root, sid)
        assert run is not None
        # Set metrics that satisfy the intraday profile:
        # min_trades=30, min_days=10, min_expectancy=0.5, min_win_rate=0.50,
        # max_drawdown=1500, max_consecutive_losses=6
        run.closed_count = 35
        run.win_count = 20
        run.loss_count = 15
        run.realized_pnl = 25.0
        run.expectancy = round(25.0 / 35, 2)
        run.win_rate = round(20 / 35, 4)
        run.max_drawdown = 500.0
        run.max_consecutive_losses = 3
        # Backdate started_at so min_days is met
        run.started_at = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
        save_paper_run(root, run)
        # Evaluate so the run transitions to paper_proof_ready
        result = evaluate_proof(root, run.paper_run_id)
        assert result["sufficient"], f"Expected sufficient but got: {result['criteria']}"
        return result["run"]

    def test_auto_promotes_when_sufficient(self, clean_root):
        """When proof becomes sufficient on fill, strategy moves to PAPER_REVIEW."""
        ref = _push_to_paper_active(clean_root, "promo-001")
        self._make_sufficient_run(clean_root, "promo-001", ref)

        # Next fill triggers evaluate_proof which should see sufficient + auto-promote
        result = execute_paper_trade(
            clean_root, "promo-001", ref, symbol="NQ", side="long",
        )
        assert result["success"] is True
        assert result["proof"]["sufficient"] is True
        assert result["proof"]["auto_promoted"] is True

        # Strategy should now be PAPER_REVIEW
        s = get_strategy(clean_root, "promo-001")
        assert s.lifecycle_state == "PAPER_REVIEW"

    def test_non_ready_stays_paper_active(self, clean_root):
        """Strategy with insufficient proof stays PAPER_ACTIVE."""
        ref = _push_to_paper_active(clean_root, "stay-001")
        # Just do a normal fill — not enough for proof
        result = execute_paper_trade(
            clean_root, "stay-001", ref, symbol="NQ", side="long",
        )
        assert result["success"] is True
        assert result["proof"]["sufficient"] is False
        assert result["proof"].get("auto_promoted") is False

        s = get_strategy(clean_root, "stay-001")
        assert s.lifecycle_state == "PAPER_ACTIVE"

    def test_auto_promote_uses_sigma_actor(self, clean_root):
        """Auto-promotion transition is recorded with actor=sigma."""
        ref = _push_to_paper_active(clean_root, "actor-001")
        self._make_sufficient_run(clean_root, "actor-001", ref)
        execute_paper_trade(clean_root, "actor-001", ref, symbol="NQ", side="long")

        s = get_strategy(clean_root, "actor-001")
        assert s.lifecycle_state == "PAPER_REVIEW"
        # Last transition should be by sigma
        last = s.state_history[-1]
        assert last.by == "sigma"
        assert "Auto-promoted" in (last.note or "")

    def test_no_double_promote(self, clean_root):
        """Already-promoted strategy doesn't get promoted again on next fill."""
        ref = _push_to_paper_active(clean_root, "dbl-001")
        self._make_sufficient_run(clean_root, "dbl-001", ref)

        # First fill promotes
        r1 = execute_paper_trade(clean_root, "dbl-001", ref, symbol="NQ", side="long")
        assert r1["proof"]["auto_promoted"] is True
        assert get_strategy(clean_root, "dbl-001").lifecycle_state == "PAPER_REVIEW"

        # Strategy is now PAPER_REVIEW — further fills won't find it in PAPER_ACTIVE
        # so auto-promote won't fire (it checks lifecycle_state == PAPER_ACTIVE)
        r2 = execute_paper_trade(clean_root, "dbl-001", ref, symbol="NQ", side="long")
        assert r2["proof"].get("auto_promoted") is False


# ---------------------------------------------------------------------------
# No automatic live execution
# ---------------------------------------------------------------------------

class TestNoAutoLive:
    def test_auto_promote_does_not_go_live(self, clean_root):
        """Auto-promotion goes to PAPER_REVIEW, not LIVE_QUEUED or LIVE_ACTIVE."""
        ref = _push_to_paper_active(clean_root, "nolive-001")
        run = get_active_run(clean_root, "nolive-001")
        run.closed_count = 35
        run.win_count = 20
        run.loss_count = 15
        run.realized_pnl = 25.0
        run.expectancy = round(25.0 / 35, 2)
        run.win_rate = round(20 / 35, 4)
        run.max_drawdown = 500.0
        run.max_consecutive_losses = 3
        run.started_at = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
        save_paper_run(clean_root, run)
        # Evaluate so run transitions to paper_proof_ready
        evaluate_proof(clean_root, run.paper_run_id)

        execute_paper_trade(clean_root, "nolive-001", ref, symbol="NQ", side="long")

        s = get_strategy(clean_root, "nolive-001")
        # Must be PAPER_REVIEW, NOT LIVE_QUEUED or LIVE_ACTIVE
        assert s.lifecycle_state == "PAPER_REVIEW"
        assert s.lifecycle_state not in ("LIVE_QUEUED", "LIVE_ACTIVE")
