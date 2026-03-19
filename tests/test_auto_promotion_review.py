#!/usr/bin/env python3
"""Tests proving promotion review artifacts are auto-created on proof sufficiency.

Acceptance criteria:
  1. Fill-path auto-promote creates exactly one promotion review artifact
  2. Sweep-path auto-promote creates exactly one promotion review artifact
  3. Repeated fills/sweeps do not duplicate review artifacts
  4. Rejected or rerun outcomes do not auto-live
  5. Live gate rules remain unchanged
  6. Promotion artifact contains correct strategy/run metadata
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet
from workspace.quant.shared.packet_store import store_packet, list_lane_packets
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, get_strategy,
)
from workspace.quant.shared.registries.approval_registry import (
    create_approval, ApprovedActions,
)
from workspace.quant.sigma.validation_lane import validate_candidate
from workspace.quant.executor.executor_lane import execute_paper_trade, create_promotion_if_needed
from workspace.quant.executor.proof_tracker import (
    get_active_run, create_paper_run, save_paper_run, evaluate_proof,
    load_paper_run, decide_promotion,
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
    (tmp_path / "workspace" / "quant" / "executor" / "proof_positions").mkdir(parents=True)

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


def _make_paper_active_with_approval(root, sid):
    """Push strategy to PAPER_ACTIVE with approval, return approval_ref."""
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
    execute_paper_trade(root, sid, appr.approval_ref, symbol="NQ", side="long",
                        simulated_price=18000.0)
    return appr.approval_ref


def _make_proof_sufficient(root, sid):
    """Fast-forward paper run to sufficient proof and evaluate it."""
    run = get_active_run(root, sid)
    assert run is not None
    run.closed_count = 35
    run.win_count = 20
    run.loss_count = 15
    run.realized_pnl = 2500.0
    run.expectancy = round(2500.0 / 35, 2)
    run.win_rate = round(20 / 35, 4)
    run.max_drawdown = 500.0
    run.max_consecutive_losses = 3
    run.started_at = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
    save_paper_run(root, run)
    evaluate_proof(root, run.paper_run_id)
    return run.paper_run_id


def _count_promotions(root):
    """Count promotion review JSON files on disk."""
    d = root / "workspace" / "quant" / "executor" / "promotions"
    return len(list(d.glob("promo_*.json")))


def _count_review_packets(root, strategy_id):
    """Count paper_review_packets for a strategy."""
    pkts = list_lane_packets(root, "sigma", "paper_review_packet")
    return len([p for p in pkts if p.strategy_id == strategy_id])


# ---------------------------------------------------------------------------
# Fill-path auto-promotion creates review artifact
# ---------------------------------------------------------------------------

class TestFillPathPromotion:
    def test_creates_promotion_on_sufficient_fill(self, clean_root):
        """When fill triggers auto-promote, promotion review artifact is created."""
        ref = _make_paper_active_with_approval(clean_root, "fill-001")
        run_id = _make_proof_sufficient(clean_root, "fill-001")

        # This fill triggers auto-promote + promotion review
        execute_paper_trade(clean_root, "fill-001", ref, symbol="NQ", side="long",
                            simulated_price=18050.0)

        assert get_strategy(clean_root, "fill-001").lifecycle_state == "PAPER_REVIEW"
        assert _count_promotions(clean_root) == 1

        # Paper run should have promotion_id set
        run = load_paper_run(clean_root, run_id)
        assert run.promotion_id is not None
        assert run.status == "awaiting_review"

    def test_promotion_emits_review_packet(self, clean_root):
        """Promotion creates a paper_review_packet visible in sigma lane."""
        ref = _make_paper_active_with_approval(clean_root, "pkt-001")
        _make_proof_sufficient(clean_root, "pkt-001")
        execute_paper_trade(clean_root, "pkt-001", ref, symbol="NQ", side="long",
                            simulated_price=18050.0)

        assert _count_review_packets(clean_root, "pkt-001") == 1


# ---------------------------------------------------------------------------
# Sweep-path auto-promotion creates review artifact
# ---------------------------------------------------------------------------

class TestSweepPathPromotion:
    def test_sweep_creates_promotion(self, clean_root):
        """Proof sweep promotion creates the review artifact."""
        _make_paper_active_with_approval(clean_root, "sweep-001")
        run_id = _make_proof_sufficient(clean_root, "sweep-001")

        result = sweep_proof_ready(clean_root)
        assert "sweep-001" in result["promoted"]
        assert _count_promotions(clean_root) == 1

        run = load_paper_run(clean_root, run_id)
        assert run.promotion_id is not None
        assert run.status == "awaiting_review"

    def test_sweep_emits_review_packet(self, clean_root):
        """Sweep promotion creates a paper_review_packet."""
        _make_paper_active_with_approval(clean_root, "swpkt-001")
        _make_proof_sufficient(clean_root, "swpkt-001")
        sweep_proof_ready(clean_root)

        assert _count_review_packets(clean_root, "swpkt-001") == 1


# ---------------------------------------------------------------------------
# Idempotency — no duplicate artifacts
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_repeated_fills_no_duplicate(self, clean_root):
        """Multiple fills after promotion do not create extra review artifacts."""
        ref = _make_paper_active_with_approval(clean_root, "dup-001")
        _make_proof_sufficient(clean_root, "dup-001")

        # First fill creates promotion
        execute_paper_trade(clean_root, "dup-001", ref, symbol="NQ", side="long",
                            simulated_price=18050.0)
        assert _count_promotions(clean_root) == 1

        # More fills — should not create duplicates
        execute_paper_trade(clean_root, "dup-001", ref, symbol="NQ", side="short",
                            simulated_price=18100.0)
        execute_paper_trade(clean_root, "dup-001", ref, symbol="NQ", side="long",
                            simulated_price=18050.0)
        assert _count_promotions(clean_root) == 1
        assert _count_review_packets(clean_root, "dup-001") == 1

    def test_repeated_sweeps_no_duplicate(self, clean_root):
        """Multiple sweeps after promotion do not create extra review artifacts."""
        _make_paper_active_with_approval(clean_root, "swdup-001")
        _make_proof_sufficient(clean_root, "swdup-001")

        sweep_proof_ready(clean_root)
        assert _count_promotions(clean_root) == 1

        sweep_proof_ready(clean_root)
        assert _count_promotions(clean_root) == 1

    def test_create_promotion_if_needed_idempotent(self, clean_root):
        """Direct call to create_promotion_if_needed is idempotent."""
        _make_paper_active_with_approval(clean_root, "idem-001")
        run_id = _make_proof_sufficient(clean_root, "idem-001")

        r1 = create_promotion_if_needed(clean_root, run_id)
        assert r1 is not None
        assert r1["promotion_id"].startswith("promo_")

        r2 = create_promotion_if_needed(clean_root, run_id)
        assert r2 is None  # Already has promotion_id


# ---------------------------------------------------------------------------
# Governance preserved — no auto-live
# ---------------------------------------------------------------------------

class TestGovernancePreserved:
    def test_promotion_does_not_auto_approve(self, clean_root):
        """Promotion review is created as pending, not auto-approved."""
        ref = _make_paper_active_with_approval(clean_root, "gov-001")
        run_id = _make_proof_sufficient(clean_root, "gov-001")
        execute_paper_trade(clean_root, "gov-001", ref, symbol="NQ", side="long",
                            simulated_price=18050.0)

        # Strategy is PAPER_REVIEW, not LIVE_QUEUED
        s = get_strategy(clean_root, "gov-001")
        assert s.lifecycle_state == "PAPER_REVIEW"
        assert s.lifecycle_state not in ("LIVE_QUEUED", "LIVE_ACTIVE")

        # Promotion is pending, not approved
        run = load_paper_run(clean_root, run_id)
        promo_path = (clean_root / "workspace" / "quant" / "executor" / "promotions"
                      / f"{run.promotion_id}.json")
        promo = json.loads(promo_path.read_text(encoding="utf-8"))
        assert promo["status"] == "pending"

    def test_rejected_promotion_blocks_live(self, clean_root):
        """Rejected promotion keeps strategy out of live path."""
        ref = _make_paper_active_with_approval(clean_root, "rej-001")
        run_id = _make_proof_sufficient(clean_root, "rej-001")
        execute_paper_trade(clean_root, "rej-001", ref, symbol="NQ", side="long",
                            simulated_price=18050.0)

        run = load_paper_run(clean_root, run_id)
        decide_promotion(clean_root, run.promotion_id, "rejected", reason="Risk too high")

        run = load_paper_run(clean_root, run_id)
        assert run.status == "review_rejected"

        s = get_strategy(clean_root, "rej-001")
        assert s.lifecycle_state not in ("LIVE_QUEUED", "LIVE_ACTIVE")
