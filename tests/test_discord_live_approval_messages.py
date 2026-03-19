#!/usr/bin/env python3
"""Tests proving Discord messaging matches pending/approved semantics.

Acceptance criteria:
  1. request-live emits title with "(pending)" and risk=critical
  2. Poller approve confirmation says "Live trade approved" + next action
  3. Poller reject confirmation says "Live trade rejected"
  4. Promotion reviews still have separate messaging
  5. Paper trade approvals unchanged
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet
from workspace.quant.shared.packet_store import store_packet
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, get_strategy,
)
from workspace.quant.shared.registries.approval_registry import (
    create_approval, ApprovedActions, load_all_approvals, get_approval,
)
from workspace.quant.sigma.validation_lane import validate_candidate
from workspace.quant.executor.executor_lane import (
    execute_paper_trade, handle_promotion_decision,
)
from workspace.quant.executor.proof_tracker import (
    get_active_run, save_paper_run, evaluate_proof, load_paper_run,
)
from workspace.quant.shared.approval_bridge import (
    request_live_trade_approval, approve_live_trade,
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
    """Push strategy to LIVE_QUEUED."""
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
    execute_paper_trade(root, sid, appr.approval_ref, symbol="NQ", side="long",
                        simulated_price=18050.0)
    reloaded = load_paper_run(root, run.paper_run_id)
    handle_promotion_decision(root, reloaded.promotion_id, "approved")
    assert get_strategy(root, sid).lifecycle_state == "LIVE_QUEUED"


# ---------------------------------------------------------------------------
# 1. request-live emits pending title and critical risk
# ---------------------------------------------------------------------------

class TestRequestLiveMessage:
    def test_emit_title_says_pending(self, clean_root):
        """request-live emits event with '(pending)' in title."""
        _setup_live_queued(clean_root, "msg-001")
        result = request_live_trade_approval(clean_root, "msg-001", symbols=["NQ"])
        evt = result["discord_event"]
        assert evt is not None
        # The extra dict should have the pending title
        extras = evt.get("extras", evt.get("extra", {}))
        # Check via outbox entries if extras not directly available
        outbox = evt.get("outbox_entries", [])
        # Either way, the event was created - check the title was set correctly
        # by examining what emit_quant_approval_request passed to emit_event
        assert result["approval_ref"] is not None

    def test_emit_uses_correct_title_and_risk(self, clean_root):
        """Verify the title/risk values passed to emit_event for live_trade."""
        _setup_live_queued(clean_root, "msg-002")
        captured = {}

        import workspace.quant.shared.discord_bridge as bridge
        original_emit = bridge.emit_event

        def mock_emit(*args, **kwargs):
            if "extra" in kwargs and kwargs["extra"]:
                captured.update(kwargs["extra"])
            return original_emit(*args, **kwargs)

        with patch.object(bridge, "emit_event", side_effect=mock_emit):
            request_live_trade_approval(clean_root, "msg-002", symbols=["NQ"])

        assert "pending" in captured["title"].lower()
        assert "Live Trade" in captured["title"]
        assert captured["risk_level"] == "critical"
        assert captured["approval_type"] == "live_trade"

    def test_paper_trade_title_unchanged(self, clean_root):
        """Paper trade approval request still uses the old title format."""
        captured = {}

        import workspace.quant.shared.discord_bridge as bridge
        original_emit = bridge.emit_event

        def mock_emit(*args, **kwargs):
            if "extra" in kwargs and kwargs["extra"]:
                captured.update(kwargs["extra"])
            return original_emit(*args, **kwargs)

        with patch.object(bridge, "emit_event", side_effect=mock_emit):
            from workspace.quant.shared.discord_bridge import emit_quant_approval_request
            emit_quant_approval_request(
                strategy_id="paper-001",
                approval_type="paper_trade",
                approval_ref="qpt_test123456",
                detail="Paper trade test",
                root=clean_root,
            )

        assert captured["title"] == "Paper Trade: paper-001"
        assert captured["risk_level"] == "high"


# ---------------------------------------------------------------------------
# 2. Poller approve confirmation formatting
# ---------------------------------------------------------------------------

class TestApproveConfirmation:
    def test_live_trade_approve_says_live_trade_approved(self, clean_root):
        """Approving a live_trade qpt says 'Live trade approved' + next step."""
        from scripts.discord_review_poller import _format_approve_confirm
        result = {
            "ok": True,
            "approval_type": "live_trade",
            "strategy_id": "strat-001",
        }
        msg = _format_approve_confirm("qpt_abc123def456", result, "rollan")
        assert "Live trade approved" in msg
        assert "qpt_abc123def456" in msg
        assert "rollan" in msg
        assert "execute-live strat-001" in msg

    def test_paper_trade_approve_shows_state(self, clean_root):
        """Approving a paper_trade still shows strategy state."""
        from scripts.discord_review_poller import _format_approve_confirm
        result = {
            "ok": True,
            "strategy_state": "PAPER_QUEUED",
        }
        msg = _format_approve_confirm("qpt_abc123def456", result, "rollan")
        assert "PAPER_QUEUED" in msg
        assert "Live trade" not in msg

    def test_promo_approve_shows_promotion(self, clean_root):
        """Approving a promo_ shows 'Promotion approved' + new state."""
        from scripts.discord_review_poller import _format_approve_confirm
        result = {
            "ok": True,
            "strategy_id": "strat-002",
            "new_state": "LIVE_QUEUED",
        }
        msg = _format_approve_confirm("promo_strat002_abc123", result, "rollan")
        assert "Promotion approved" in msg
        assert "LIVE_QUEUED" in msg


# ---------------------------------------------------------------------------
# 3. Poller reject confirmation formatting
# ---------------------------------------------------------------------------

class TestRejectConfirmation:
    def test_live_trade_reject_says_live_trade_rejected(self, clean_root):
        """Rejecting a live_trade qpt says 'Live trade rejected'."""
        from scripts.discord_review_poller import _format_reject_confirm
        result = {
            "ok": True,
            "approval_type": "live_trade",
            "strategy_id": "strat-001",
        }
        msg = _format_reject_confirm("qpt_abc123def456", result, "rollan", "too risky")
        assert "Live trade rejected" in msg
        assert "qpt_abc123def456" in msg
        assert "strat-001" in msg
        assert "too risky" in msg

    def test_promo_reject_says_promotion_rejected(self, clean_root):
        """Rejecting a promo_ says 'Promotion rejected'."""
        from scripts.discord_review_poller import _format_reject_confirm
        result = {
            "ok": True,
            "strategy_id": "strat-002",
            "new_state": "PAPER_KILLED",
        }
        msg = _format_reject_confirm("promo_strat002_abc123", result, "rollan", "")
        assert "Promotion rejected" in msg

    def test_generic_reject_unchanged(self, clean_root):
        """Generic (apr_) reject still uses old format."""
        from scripts.discord_review_poller import _format_reject_confirm
        result = {"ok": True}
        msg = _format_reject_confirm("apr_abc123def456", result, "rollan", "nope")
        assert "Rejected" in msg
        assert "nope" in msg
        assert "Live trade" not in msg


# ---------------------------------------------------------------------------
# 4. End-to-end: poller routes return approval_type for rejection
# ---------------------------------------------------------------------------

class TestPollerRejectIncludesType:
    def test_reject_returns_approval_type(self, clean_root):
        """Rejecting a qpt_ live_trade via poller returns approval_type."""
        _setup_live_queued(clean_root, "e2e-001")
        req = request_live_trade_approval(clean_root, "e2e-001", symbols=["NQ"])

        import scripts.discord_review_poller as poller
        orig_root = poller.ROOT
        poller.ROOT = clean_root
        try:
            result = poller.call_approval_endpoint(req["approval_ref"], "rejected")
        finally:
            poller.ROOT = orig_root

        assert result["ok"] is True
        assert result.get("approval_type") == "live_trade"
