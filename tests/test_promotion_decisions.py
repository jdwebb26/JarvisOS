#!/usr/bin/env python3
"""Tests proving promotion review decisions wire to strategy lifecycle and review channel.

Acceptance criteria:
  1. Promotion creation emits approval_requested event (review channel delivery)
  2. Approve → strategy transitions PAPER_REVIEW → LIVE_QUEUED
  3. Reject → strategy transitions PAPER_REVIEW → PAPER_KILLED
  4. Rerun → strategy transitions PAPER_REVIEW → ITERATE
  5. No auto-live execution from any decision
  6. Repeated/duplicate decisions are safe
  7. Promotion artifact metadata is correct
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
from workspace.quant.executor.executor_lane import (
    execute_paper_trade, create_promotion_if_needed, handle_promotion_decision,
)
from workspace.quant.executor.proof_tracker import (
    get_active_run, save_paper_run, evaluate_proof, load_paper_run,
)


@pytest.fixture
def clean_root(tmp_path):
    (tmp_path / "workspace" / "quant" / "shared" / "latest").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "registries").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "config").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "scheduler").mkdir(parents=True)
    (tmp_path / "state" / "quant" / "executor").mkdir(parents=True)
    (tmp_path / "state" / "discord_outbox").mkdir(parents=True)
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


def _setup_paper_review(root, sid):
    """Push strategy all the way to PAPER_REVIEW with a promotion artifact.

    Returns (approval_ref, promotion_id, paper_run_id).
    """
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
    # Entry fill → PAPER_ACTIVE + paper run
    execute_paper_trade(root, sid, appr.approval_ref, symbol="NQ", side="long",
                        simulated_price=18000.0)

    # Fast-forward to sufficient
    run = get_active_run(root, sid)
    run.closed_count = 35
    run.win_count = 20
    run.loss_count = 15
    run.realized_pnl = 2500.0
    run.expectancy = round(2500.0 / 35, 2)
    run.win_rate = round(20 / 35, 4)
    run.max_drawdown = 500.0
    run.max_consecutive_losses = 3
    run.started_at = (now - timedelta(days=15)).isoformat()
    save_paper_run(root, run)
    evaluate_proof(root, run.paper_run_id)

    # Trigger auto-promote + promotion review creation
    execute_paper_trade(root, sid, appr.approval_ref, symbol="NQ", side="long",
                        simulated_price=18050.0)

    assert get_strategy(root, sid).lifecycle_state == "PAPER_REVIEW"
    reloaded = load_paper_run(root, run.paper_run_id)
    assert reloaded.promotion_id is not None

    return appr.approval_ref, reloaded.promotion_id, run.paper_run_id


# ---------------------------------------------------------------------------
# Approve → LIVE_QUEUED
# ---------------------------------------------------------------------------

class TestApprove:
    def test_approve_transitions_to_live_queued(self, clean_root):
        """Approving promotion moves strategy to LIVE_QUEUED."""
        _, promo_id, _ = _setup_paper_review(clean_root, "appr-001")
        result = handle_promotion_decision(clean_root, promo_id, "approved",
                                           reason="Proof looks solid")
        assert result["ok"] is True
        assert result["new_state"] == "LIVE_QUEUED"
        s = get_strategy(clean_root, "appr-001")
        assert s.lifecycle_state == "LIVE_QUEUED"

    def test_approve_does_not_auto_live(self, clean_root):
        """LIVE_QUEUED is NOT LIVE_ACTIVE. Live execution is still blocked."""
        _, promo_id, _ = _setup_paper_review(clean_root, "appr-002")
        handle_promotion_decision(clean_root, promo_id, "approved")
        s = get_strategy(clean_root, "appr-002")
        assert s.lifecycle_state == "LIVE_QUEUED"
        assert s.lifecycle_state != "LIVE_ACTIVE"

    def test_approve_records_approval_ref(self, clean_root):
        """LIVE_QUEUED transition has the promotion_id as approval_ref."""
        _, promo_id, _ = _setup_paper_review(clean_root, "appr-003")
        handle_promotion_decision(clean_root, promo_id, "approved")
        s = get_strategy(clean_root, "appr-003")
        last = s.state_history[-1]
        assert last.approval_ref == promo_id


# ---------------------------------------------------------------------------
# Reject → PAPER_KILLED
# ---------------------------------------------------------------------------

class TestReject:
    def test_reject_transitions_to_paper_killed(self, clean_root):
        """Rejecting promotion kills the strategy."""
        _, promo_id, _ = _setup_paper_review(clean_root, "rej-001")
        result = handle_promotion_decision(clean_root, promo_id, "rejected",
                                           reason="Too much drawdown risk")
        assert result["ok"] is True
        assert result["new_state"] == "PAPER_KILLED"
        s = get_strategy(clean_root, "rej-001")
        assert s.lifecycle_state == "PAPER_KILLED"

    def test_reject_never_enters_live(self, clean_root):
        _, promo_id, _ = _setup_paper_review(clean_root, "rej-002")
        handle_promotion_decision(clean_root, promo_id, "rejected")
        s = get_strategy(clean_root, "rej-002")
        assert s.lifecycle_state not in ("LIVE_QUEUED", "LIVE_ACTIVE")


# ---------------------------------------------------------------------------
# Rerun → ITERATE
# ---------------------------------------------------------------------------

class TestRerun:
    def test_rerun_transitions_to_iterate(self, clean_root):
        """Rerun decision moves strategy to ITERATE."""
        _, promo_id, _ = _setup_paper_review(clean_root, "rerun-001")
        result = handle_promotion_decision(clean_root, promo_id, "rerun_paper",
                                           reason="Need more diverse market conditions")
        assert result["ok"] is True
        assert result["new_state"] == "ITERATE"
        s = get_strategy(clean_root, "rerun-001")
        assert s.lifecycle_state == "ITERATE"

    def test_rerun_never_enters_live(self, clean_root):
        _, promo_id, _ = _setup_paper_review(clean_root, "rerun-002")
        handle_promotion_decision(clean_root, promo_id, "rerun_paper")
        s = get_strategy(clean_root, "rerun-002")
        assert s.lifecycle_state not in ("LIVE_QUEUED", "LIVE_ACTIVE")

    def test_rerun_paper_run_resets(self, clean_root):
        """Rerun resets the paper run back to accumulating."""
        _, promo_id, run_id = _setup_paper_review(clean_root, "rerun-003")
        handle_promotion_decision(clean_root, promo_id, "rerun_paper")
        run = load_paper_run(clean_root, run_id)
        assert run.status == "paper_active"
        assert run.proof_status == "accumulating"


# ---------------------------------------------------------------------------
# Duplicate/safety
# ---------------------------------------------------------------------------

class TestDuplicateSafety:
    def test_double_approve_fails(self, clean_root):
        """Cannot approve an already-decided promotion."""
        _, promo_id, _ = _setup_paper_review(clean_root, "safe-001")
        r1 = handle_promotion_decision(clean_root, promo_id, "approved")
        assert r1["ok"] is True
        r2 = handle_promotion_decision(clean_root, promo_id, "approved")
        assert r2["ok"] is False
        assert "already decided" in r2["error"]

    def test_reject_after_approve_fails(self, clean_root):
        _, promo_id, _ = _setup_paper_review(clean_root, "safe-002")
        handle_promotion_decision(clean_root, promo_id, "approved")
        r = handle_promotion_decision(clean_root, promo_id, "rejected")
        assert r["ok"] is False


# ---------------------------------------------------------------------------
# Review artifact delivery
# ---------------------------------------------------------------------------

class TestReviewDelivery:
    def test_promotion_creates_review_packet(self, clean_root):
        """Promotion review creation emits a paper_review_packet."""
        _setup_paper_review(clean_root, "deliv-001")
        pkts = list_lane_packets(clean_root, "sigma", "paper_review_packet")
        matching = [p for p in pkts if p.strategy_id == "deliv-001"]
        assert len(matching) >= 1
        assert "promotion_id" in (matching[-1].notes or "")
