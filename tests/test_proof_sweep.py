#!/usr/bin/env python3
"""Tests proving the periodic proof sweep promotes proof-ready strategies.

Acceptance criteria:
  1. Sufficient run with no fresh fill is promoted by sweep
  2. Insufficient run stays PAPER_ACTIVE
  3. Already PAPER_REVIEW strategies are untouched
  4. No live state entered automatically
  5. Sweep is safe to call repeatedly (idempotent)
  6. Strategies without paper runs are skipped
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
from workspace.quant.executor.proof_tracker import (
    create_paper_run, save_paper_run, evaluate_proof, get_active_run,
)
from workspace.quant.run_lane_b_cycle import sweep_proof_ready


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
        "lane_placement": {l: {"primary": "NIMO", "overflow": "SonLM"}
                           for l in ["atlas", "fish", "hermes", "tradefloor", "kitt", "sigma", "executor"]},
    }
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "hosts.json").write_text(
        json.dumps(hosts, indent=2), encoding="utf-8")
    gov = {l: {
        "batch_size": 1, "max_iterations": 5, "cooldown_interval": 0,
        "cloud_burst_allowed": False, "escalation_threshold": 0.6,
        "cadence_multiplier": 1.0, "consecutive_backoff_cycles": 0, "paused": False,
    } for l in ["atlas", "fish", "hermes", "tradefloor", "kitt", "sigma", "executor"]}
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "governor_state.json").write_text(
        json.dumps(gov, indent=2), encoding="utf-8")
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "risk_limits.json").write_text(
        json.dumps({"per_strategy": {"max_position_size": 2},
                     "portfolio": {"max_total_exposure": 4}}), encoding="utf-8")
    return tmp_path


def _make_paper_active(root, sid, *, with_run=True, sufficient=False):
    """Create a PAPER_ACTIVE strategy, optionally with a paper run, optionally sufficient."""
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
    create_approval(root, sid, "paper_trade", approved_actions=actions)
    transition_strategy(root, sid, "PAPER_QUEUED", actor="kitt",
                        approval_ref="placeholder")
    transition_strategy(root, sid, "PAPER_ACTIVE", actor="executor")

    if with_run:
        run = create_paper_run(root, sid, "intraday")
        if sufficient:
            # Set metrics that satisfy intraday profile
            run.closed_count = 35
            run.win_count = 20
            run.loss_count = 15
            run.realized_pnl = 25.0
            run.expectancy = round(25.0 / 35, 2)
            run.win_rate = round(20 / 35, 4)
            run.max_drawdown = 500.0
            run.max_consecutive_losses = 3
            run.started_at = (now - timedelta(days=15)).isoformat()
            save_paper_run(root, run)
            # Evaluate so it transitions to paper_proof_ready
            evaluate_proof(root, run.paper_run_id)
        return run
    return None


class TestSweepPromotesSufficient:
    def test_sufficient_no_fresh_fill_promoted(self, clean_root):
        """Proof-ready strategy with no new fill is promoted by the sweep."""
        _make_paper_active(clean_root, "sweep-001", sufficient=True)
        assert get_strategy(clean_root, "sweep-001").lifecycle_state == "PAPER_ACTIVE"

        result = sweep_proof_ready(clean_root)

        assert "sweep-001" in result["promoted"]
        assert get_strategy(clean_root, "sweep-001").lifecycle_state == "PAPER_REVIEW"

    def test_promotion_recorded_as_sigma(self, clean_root):
        """Sweep transition uses actor=sigma."""
        _make_paper_active(clean_root, "sweep-actor", sufficient=True)
        sweep_proof_ready(clean_root)

        s = get_strategy(clean_root, "sweep-actor")
        last = s.state_history[-1]
        assert last.by == "sigma"
        assert "Proof sweep" in (last.note or "")


class TestSweepLeavesInsufficient:
    def test_insufficient_stays_paper_active(self, clean_root):
        """Strategy with insufficient proof stays PAPER_ACTIVE."""
        _make_paper_active(clean_root, "sweep-002", sufficient=False)
        assert get_strategy(clean_root, "sweep-002").lifecycle_state == "PAPER_ACTIVE"

        result = sweep_proof_ready(clean_root)

        assert "sweep-002" in result["still_accumulating"]
        assert get_strategy(clean_root, "sweep-002").lifecycle_state == "PAPER_ACTIVE"


class TestSweepSkipsOtherStates:
    def test_paper_review_untouched(self, clean_root):
        """Already PAPER_REVIEW strategies are not re-transitioned."""
        _make_paper_active(clean_root, "sweep-003", sufficient=True)
        # Manually promote
        transition_strategy(clean_root, "sweep-003", "PAPER_REVIEW", actor="sigma")
        assert get_strategy(clean_root, "sweep-003").lifecycle_state == "PAPER_REVIEW"

        history_len = len(get_strategy(clean_root, "sweep-003").state_history)
        result = sweep_proof_ready(clean_root)

        # Should not appear in promoted (not PAPER_ACTIVE)
        assert "sweep-003" not in result["promoted"]
        # History unchanged
        assert len(get_strategy(clean_root, "sweep-003").state_history) == history_len

    def test_no_run_skipped(self, clean_root):
        """Strategy without a paper run is skipped, not crashed."""
        _make_paper_active(clean_root, "sweep-004", with_run=False)

        result = sweep_proof_ready(clean_root)

        assert result["scanned"] == 0  # No run → not scanned
        assert get_strategy(clean_root, "sweep-004").lifecycle_state == "PAPER_ACTIVE"


class TestSweepNoLive:
    def test_promoted_is_paper_review_not_live(self, clean_root):
        """Sweep promotes to PAPER_REVIEW, never to LIVE_QUEUED or beyond."""
        _make_paper_active(clean_root, "sweep-005", sufficient=True)
        sweep_proof_ready(clean_root)

        s = get_strategy(clean_root, "sweep-005")
        assert s.lifecycle_state == "PAPER_REVIEW"
        assert s.lifecycle_state not in ("LIVE_QUEUED", "LIVE_ACTIVE")


class TestSweepIdempotent:
    def test_repeat_sweep_is_safe(self, clean_root):
        """Calling sweep twice does not double-promote or error."""
        _make_paper_active(clean_root, "sweep-006", sufficient=True)

        r1 = sweep_proof_ready(clean_root)
        assert "sweep-006" in r1["promoted"]

        r2 = sweep_proof_ready(clean_root)
        # Strategy is now PAPER_REVIEW, so sweep won't find it in PAPER_ACTIVE
        assert "sweep-006" not in r2["promoted"]
        assert r2["scanned"] == 0


class TestSweepMixed:
    def test_mixed_sufficient_and_insufficient(self, clean_root):
        """Sweep handles a mix of sufficient and insufficient correctly."""
        _make_paper_active(clean_root, "mix-suf", sufficient=True)
        _make_paper_active(clean_root, "mix-ins", sufficient=False)

        result = sweep_proof_ready(clean_root)

        assert "mix-suf" in result["promoted"]
        assert "mix-ins" in result["still_accumulating"]
        assert result["scanned"] == 2
        assert get_strategy(clean_root, "mix-suf").lifecycle_state == "PAPER_REVIEW"
        assert get_strategy(clean_root, "mix-ins").lifecycle_state == "PAPER_ACTIVE"
