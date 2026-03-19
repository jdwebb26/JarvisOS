#!/usr/bin/env python3
"""Tests proving the LIVE_QUEUED → live approval → live execution path.

Acceptance criteria:
  1. LIVE_QUEUED strategy can request a live_trade approval artifact
  2. Live approval posts to #review with correct approval_type
  3. Live executor rejects missing/wrong approval
  4. Valid live approval allows the live path to proceed
  5. Promotion approval alone is NOT enough for live execution
  6. Review poller routes qpt_ live_trade approvals correctly
  7. Operator surfaces show what is waiting on live approval
  8. Duplicate/invalid states are handled safely
  9. No bypass path exists
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
    create_strategy, transition_strategy, get_strategy, get_strategies_by_state,
)
from workspace.quant.shared.registries.approval_registry import (
    create_approval, ApprovedActions, load_all_approvals, get_approval,
)
from workspace.quant.sigma.validation_lane import validate_candidate
from workspace.quant.executor.executor_lane import (
    execute_paper_trade, execute_live_trade, handle_promotion_decision,
)
from workspace.quant.executor.proof_tracker import (
    get_active_run, save_paper_run, evaluate_proof, load_paper_run,
)
from workspace.quant.shared.approval_bridge import (
    request_live_trade_approval, approve_live_trade, execute_approved_live_trade,
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


def _setup_live_queued(root, sid):
    """Push strategy all the way to LIVE_QUEUED via promotion approval.

    Returns (paper_approval_ref, promotion_id).
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
    execute_paper_trade(root, sid, appr.approval_ref, symbol="NQ", side="long",
                        simulated_price=18000.0)

    # Fast-forward to sufficient proof
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
    promo_id = reloaded.promotion_id
    assert promo_id is not None

    # Approve promotion → LIVE_QUEUED
    result = handle_promotion_decision(root, promo_id, "approved", reason="Proof solid")
    assert result["ok"] is True
    assert get_strategy(root, sid).lifecycle_state == "LIVE_QUEUED"

    return appr.approval_ref, promo_id


# ---------------------------------------------------------------------------
# 1. Request live trade approval
# ---------------------------------------------------------------------------

class TestRequestLiveApproval:
    def test_creates_live_trade_approval(self, clean_root):
        """LIVE_QUEUED strategy can request a live_trade approval artifact."""
        _setup_live_queued(clean_root, "live-001")
        result = request_live_trade_approval(clean_root, "live-001", symbols=["NQ"])
        assert result["error"] is None
        assert result["approval_ref"] is not None
        assert result["approval_ref"].startswith("qpt_")

        approval = get_approval(clean_root, result["approval_ref"])
        assert approval.approval_type == "live_trade"
        assert approval.approved_actions.execution_mode == "live"
        assert approval.strategy_id == "live-001"

    def test_wrong_state_rejected(self, clean_root):
        """Cannot request live approval for a non-LIVE_QUEUED strategy."""
        create_strategy(clean_root, "live-002", actor="atlas")
        result = request_live_trade_approval(clean_root, "live-002", symbols=["NQ"])
        assert result["error"] is not None
        assert "LIVE_QUEUED" in result["error"]

    def test_approval_posts_to_review(self, clean_root):
        """Live approval request emits a discord event for #review."""
        _setup_live_queued(clean_root, "live-003")
        result = request_live_trade_approval(clean_root, "live-003", symbols=["NQ"])
        assert result["discord_event"] is not None


# ---------------------------------------------------------------------------
# 2. Approve live trade
# ---------------------------------------------------------------------------

class TestApproveLiveTrade:
    def test_approve_validates_live_approval(self, clean_root):
        """approve_live_trade validates the approval is live_trade type."""
        _setup_live_queued(clean_root, "aprlive-001")
        req = request_live_trade_approval(clean_root, "aprlive-001", symbols=["NQ"])
        result = approve_live_trade(clean_root, "aprlive-001", approval_ref=req["approval_ref"])
        assert result["success"] is True
        assert result["approval_ref"] == req["approval_ref"]

    def test_approve_rejects_paper_approval(self, clean_root):
        """approve_live_trade rejects a paper_trade approval type."""
        _setup_live_queued(clean_root, "aprlive-002")
        # The paper approval from setup is paper_trade type
        approvals = [a for a in load_all_approvals(clean_root)
                     if a.strategy_id == "aprlive-002" and a.approval_type == "paper_trade"]
        assert len(approvals) > 0
        result = approve_live_trade(clean_root, "aprlive-002", approval_ref=approvals[0].approval_ref)
        assert result["success"] is False
        assert "not live_trade" in result["error"]

    def test_approve_no_state_change(self, clean_root):
        """approve_live_trade does NOT transition strategy state."""
        _setup_live_queued(clean_root, "aprlive-003")
        request_live_trade_approval(clean_root, "aprlive-003", symbols=["NQ"])
        approve_live_trade(clean_root, "aprlive-003")
        s = get_strategy(clean_root, "aprlive-003")
        assert s.lifecycle_state == "LIVE_QUEUED"  # Still queued, not active

    def test_approve_finds_latest_live_approval(self, clean_root):
        """approve_live_trade auto-finds latest live_trade approval when no ref given."""
        _setup_live_queued(clean_root, "aprlive-004")
        req = request_live_trade_approval(clean_root, "aprlive-004", symbols=["NQ"])
        result = approve_live_trade(clean_root, "aprlive-004")
        assert result["success"] is True
        assert result["approval_ref"] == req["approval_ref"]


# ---------------------------------------------------------------------------
# 3. Live executor rejects missing/wrong approval
# ---------------------------------------------------------------------------

class TestLiveExecutorRejects:
    def test_rejects_without_any_approval(self, clean_root):
        """Live executor rejects when no approval exists."""
        _setup_live_queued(clean_root, "rej-001")
        result = execute_live_trade(
            clean_root, "rej-001", "qpt_nonexistent_ref",
            symbol="NQ", side="long",
        )
        assert result["success"] is False
        assert result["rejection_reason"] is not None

    def test_rejects_paper_approval_for_live(self, clean_root):
        """Live executor rejects when given a paper_trade approval."""
        paper_ref, _ = _setup_live_queued(clean_root, "rej-002")
        result = execute_live_trade(
            clean_root, "rej-002", paper_ref,
            symbol="NQ", side="long",
        )
        assert result["success"] is False
        assert result["rejection_reason"] in ("mode_mismatch", "invalid_approval")

    def test_rejects_promotion_id_for_live(self, clean_root):
        """Live executor rejects promotion approval ID (promo_xxx)."""
        _, promo_id = _setup_live_queued(clean_root, "rej-003")
        result = execute_live_trade(
            clean_root, "rej-003", promo_id,
            symbol="NQ", side="long",
        )
        assert result["success"] is False
        # promo_ IDs are not in the approval registry, so this should fail

    def test_rejects_revoked_live_approval(self, clean_root):
        """Live executor rejects a revoked live approval."""
        _setup_live_queued(clean_root, "rej-004")
        req = request_live_trade_approval(clean_root, "rej-004", symbols=["NQ"])
        from workspace.quant.shared.registries.approval_registry import revoke_approval
        revoke_approval(clean_root, req["approval_ref"])
        result = execute_live_trade(
            clean_root, "rej-004", req["approval_ref"],
            symbol="NQ", side="long",
        )
        assert result["success"] is False

    def test_emits_rejection_packet(self, clean_root):
        """Rejection emits an execution_rejection_packet."""
        _setup_live_queued(clean_root, "rej-005")
        result = execute_live_trade(
            clean_root, "rej-005", "qpt_nonexistent_ref",
            symbol="NQ", side="long",
        )
        assert len(result["packets"]) >= 1
        pkt = result["packets"][0]
        assert pkt["packet_type"] == "execution_rejection_packet"


# ---------------------------------------------------------------------------
# 4. Valid live approval allows execution (broker boundary)
# ---------------------------------------------------------------------------

class TestLiveExecutionWithApproval:
    def test_valid_approval_reaches_broker_boundary(self, clean_root):
        """With valid live approval, execution proceeds to broker check.

        Since no live broker is configured in test, it should fail at broker
        boundary — but ONLY at broker boundary, not at approval checks.
        """
        _setup_live_queued(clean_root, "exec-001")
        req = request_live_trade_approval(clean_root, "exec-001", symbols=["NQ"])
        result = execute_live_trade(
            clean_root, "exec-001", req["approval_ref"],
            symbol="NQ", side="long",
        )
        # Should fail at broker health, not approval
        assert result["success"] is False
        assert result["rejection_reason"] == "broker_unhealthy"
        # Broker error means it got PAST approval validation
        assert result.get("broker_error") is not None or result["rejection_reason"] == "broker_unhealthy"

    def test_approval_valid_means_preflight_passes(self, clean_root):
        """Valid live approval passes all approval preflights."""
        _setup_live_queued(clean_root, "exec-002")
        req = request_live_trade_approval(clean_root, "exec-002", symbols=["NQ"])

        from workspace.quant.shared.registries.approval_registry import validate_approval_for_execution
        valid, reason = validate_approval_for_execution(
            clean_root, req["approval_ref"], "exec-002", "live", "NQ",
        )
        assert valid is True


# ---------------------------------------------------------------------------
# 5. Promotion approval is NOT enough for live execution
# ---------------------------------------------------------------------------

class TestPromotionNotEnough:
    def test_promotion_approval_cannot_execute_live(self, clean_root):
        """Promotion approval (promo_xxx) is NOT a live execution approval."""
        _, promo_id = _setup_live_queued(clean_root, "nobypass-001")
        result = execute_live_trade(
            clean_root, "nobypass-001", promo_id,
            symbol="NQ", side="long",
        )
        assert result["success"] is False

    def test_live_queued_without_live_approval_blocked(self, clean_root):
        """LIVE_QUEUED state alone is not enough — need explicit live_trade approval."""
        _setup_live_queued(clean_root, "nobypass-002")
        # Only has paper_trade approval, not live_trade
        approvals = [a for a in load_all_approvals(clean_root)
                     if a.strategy_id == "nobypass-002" and not a.revoked]
        # All existing approvals are paper_trade type
        for a in approvals:
            if a.approval_type == "paper_trade":
                result = execute_live_trade(
                    clean_root, "nobypass-002", a.approval_ref,
                    symbol="NQ", side="long",
                )
                assert result["success"] is False
                assert result["rejection_reason"] in ("mode_mismatch", "invalid_approval")


# ---------------------------------------------------------------------------
# 6. Review poller routes live_trade qpt_ approvals correctly
# ---------------------------------------------------------------------------

class TestPollerLiveRouting:
    def test_poller_routes_live_trade_approval(self, clean_root):
        """Review poller recognizes qpt_ live_trade and calls approve_live_trade."""
        _setup_live_queued(clean_root, "poll-001")
        req = request_live_trade_approval(clean_root, "poll-001", symbols=["NQ"])

        import scripts.discord_review_poller as poller
        orig_root = poller.ROOT
        poller.ROOT = clean_root
        try:
            result = poller.call_approval_endpoint(req["approval_ref"], "approved")
        finally:
            poller.ROOT = orig_root

        assert result["ok"] is True
        assert result.get("approval_type") == "live_trade"

    def test_poller_reject_revokes_live_approval(self, clean_root):
        """Rejecting a qpt_ live_trade approval revokes it."""
        _setup_live_queued(clean_root, "poll-002")
        req = request_live_trade_approval(clean_root, "poll-002", symbols=["NQ"])

        import scripts.discord_review_poller as poller
        orig_root = poller.ROOT
        poller.ROOT = clean_root
        try:
            result = poller.call_approval_endpoint(req["approval_ref"], "rejected")
        finally:
            poller.ROOT = orig_root

        assert result["ok"] is True
        assert result["decision"] == "rejected"

        approval = get_approval(clean_root, req["approval_ref"])
        assert approval.revoked is True


# ---------------------------------------------------------------------------
# 7. Operator surfaces show live approval status
# ---------------------------------------------------------------------------

class TestOperatorSurfaces:
    def test_live_queued_shows_needs_approval(self, clean_root):
        """get_strategies_by_state returns LIVE_QUEUED strategies."""
        _setup_live_queued(clean_root, "surf-001")
        queued = get_strategies_by_state(clean_root, "LIVE_QUEUED")
        sids = [s.strategy_id for s in queued]
        assert "surf-001" in sids

    def test_can_distinguish_approved_vs_pending(self, clean_root):
        """Operator can tell whether LIVE_QUEUED has a live_trade approval."""
        _setup_live_queued(clean_root, "surf-002")
        # Before requesting live approval
        approvals = load_all_approvals(clean_root)
        has_live = any(a.strategy_id == "surf-002" and not a.revoked
                       and a.approved_actions.execution_mode == "live"
                       for a in approvals)
        assert has_live is False

        # After requesting live approval
        request_live_trade_approval(clean_root, "surf-002", symbols=["NQ"])
        approvals = load_all_approvals(clean_root)
        has_live = any(a.strategy_id == "surf-002" and not a.revoked
                       and a.approved_actions.execution_mode == "live"
                       for a in approvals)
        assert has_live is True


# ---------------------------------------------------------------------------
# 8. No auto-live execution
# ---------------------------------------------------------------------------

class TestNoAutoLive:
    def test_approve_live_does_not_execute(self, clean_root):
        """Approving live trade does not auto-execute anything."""
        _setup_live_queued(clean_root, "noauto-001")
        request_live_trade_approval(clean_root, "noauto-001", symbols=["NQ"])
        approve_live_trade(clean_root, "noauto-001")
        s = get_strategy(clean_root, "noauto-001")
        assert s.lifecycle_state == "LIVE_QUEUED"
        assert s.lifecycle_state != "LIVE_ACTIVE"
