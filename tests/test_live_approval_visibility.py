#!/usr/bin/env python3
"""Tests proving operator surfaces correctly show live approval state.

Acceptance criteria:
  1. _live_approval_state returns correct state for each scenario
  2. Brief producer pipeline section includes LIVE_QUEUED with approval state
  3. Brief operator actions include LIVE_QUEUED next action
  4. All four states are distinguishable: no_request, approved, revoked, expired
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
    create_approval, ApprovedActions, load_all_approvals, revoke_approval,
)
from workspace.quant.sigma.validation_lane import validate_candidate
from workspace.quant.executor.executor_lane import (
    execute_paper_trade, handle_promotion_decision,
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


def _setup_live_queued(root, sid):
    """Push strategy to LIVE_QUEUED via the full lifecycle."""
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
# 0. Shared helper: resolve_live_approval_state
# ---------------------------------------------------------------------------

class TestSharedHelper:
    """Verify the single source of truth directly."""

    def test_returns_no_request(self, clean_root):
        _setup_live_queued(clean_root, "sh-001")
        approvals = load_all_approvals(clean_root)
        from workspace.quant.shared.live_approval_state import resolve_live_approval_state
        la = resolve_live_approval_state("sh-001", approvals)
        assert la["state"] == "no_request"
        assert la["approval_ref"] is None
        assert "request-live" in la["action"]

    def test_returns_approved(self, clean_root):
        _setup_live_queued(clean_root, "sh-002")
        from workspace.quant.shared.approval_bridge import request_live_trade_approval
        request_live_trade_approval(clean_root, "sh-002", symbols=["NQ"])
        approvals = load_all_approvals(clean_root)
        from workspace.quant.shared.live_approval_state import resolve_live_approval_state
        la = resolve_live_approval_state("sh-002", approvals)
        assert la["state"] == "approved"
        assert la["approval_ref"] is not None
        assert "execute-live" in la["action"]

    def test_returns_revoked(self, clean_root):
        _setup_live_queued(clean_root, "sh-003")
        from workspace.quant.shared.approval_bridge import request_live_trade_approval
        result = request_live_trade_approval(clean_root, "sh-003", symbols=["NQ"])
        revoke_approval(clean_root, result["approval_ref"])
        approvals = load_all_approvals(clean_root)
        from workspace.quant.shared.live_approval_state import resolve_live_approval_state
        la = resolve_live_approval_state("sh-003", approvals)
        assert la["state"] == "revoked"
        assert "request-live" in la["action"]

    def test_returns_expired(self, clean_root):
        _setup_live_queued(clean_root, "sh-004")
        now = datetime.now(timezone.utc)
        actions = ApprovedActions(
            execution_mode="live", symbols=["NQ"],
            valid_from=(now - timedelta(days=10)).isoformat(),
            valid_until=(now - timedelta(days=1)).isoformat(),
            broker_target="live_adapter",
        )
        create_approval(clean_root, "sh-004", "live_trade", approved_actions=actions)
        approvals = load_all_approvals(clean_root)
        from workspace.quant.shared.live_approval_state import resolve_live_approval_state
        la = resolve_live_approval_state("sh-004", approvals)
        assert la["state"] == "expired"
        assert "request-live" in la["action"]

    def test_quant_lanes_delegates(self, clean_root):
        """quant_lanes._live_approval_state is the shared helper."""
        import scripts.quant_lanes as ql
        from workspace.quant.shared.live_approval_state import resolve_live_approval_state
        assert ql._live_approval_state is resolve_live_approval_state

    def test_brief_producer_delegates(self, clean_root):
        """brief_producer._live_approval_state is the shared helper."""
        from workspace.quant.kitt.brief_producer import _live_approval_state
        from workspace.quant.shared.live_approval_state import resolve_live_approval_state
        assert _live_approval_state is resolve_live_approval_state


# ---------------------------------------------------------------------------
# 1. _live_approval_state in quant_lanes.py (now delegating to shared helper)
# ---------------------------------------------------------------------------

class TestLiveApprovalStateHelper:
    def test_no_request(self, clean_root):
        """No live_trade approval → state='no_request'."""
        _setup_live_queued(clean_root, "vis-001")
        approvals = load_all_approvals(clean_root)

        # Import the helper from quant_lanes
        import scripts.quant_lanes as ql
        la = ql._live_approval_state("vis-001", approvals)
        assert la["state"] == "no_request"
        assert "request-live" in la["action"]
        assert "needs" in la["label"]

    def test_approved(self, clean_root):
        """Valid live_trade approval → state='approved'."""
        _setup_live_queued(clean_root, "vis-002")
        from workspace.quant.shared.approval_bridge import request_live_trade_approval
        request_live_trade_approval(clean_root, "vis-002", symbols=["NQ"])
        approvals = load_all_approvals(clean_root)

        import scripts.quant_lanes as ql
        la = ql._live_approval_state("vis-002", approvals)
        assert la["state"] == "approved"
        assert "execute-live" in la["action"]
        assert la["approval_ref"] is not None

    def test_revoked(self, clean_root):
        """Revoked live_trade approval → state='revoked'."""
        _setup_live_queued(clean_root, "vis-003")
        from workspace.quant.shared.approval_bridge import request_live_trade_approval
        result = request_live_trade_approval(clean_root, "vis-003", symbols=["NQ"])
        revoke_approval(clean_root, result["approval_ref"])
        approvals = load_all_approvals(clean_root)

        import scripts.quant_lanes as ql
        la = ql._live_approval_state("vis-003", approvals)
        assert la["state"] == "revoked"
        assert "request-live" in la["action"]
        assert "revoked" in la["label"]

    def test_expired(self, clean_root):
        """Expired live_trade approval → state='expired'."""
        _setup_live_queued(clean_root, "vis-004")
        # Create an already-expired approval
        now = datetime.now(timezone.utc)
        actions = ApprovedActions(
            execution_mode="live", symbols=["NQ"],
            valid_from=(now - timedelta(days=10)).isoformat(),
            valid_until=(now - timedelta(days=1)).isoformat(),
            broker_target="live_adapter",
        )
        create_approval(clean_root, "vis-004", "live_trade", approved_actions=actions)
        approvals = load_all_approvals(clean_root)

        import scripts.quant_lanes as ql
        la = ql._live_approval_state("vis-004", approvals)
        assert la["state"] == "expired"
        assert "request-live" in la["action"]
        assert "expired" in la["label"]


# ---------------------------------------------------------------------------
# 2. _live_approval_state in brief_producer.py
# ---------------------------------------------------------------------------

class TestBriefProducerLiveApprovalState:
    def test_brief_helper_no_request(self, clean_root):
        """brief_producer._live_approval_state matches quant_lanes version."""
        _setup_live_queued(clean_root, "brief-001")
        approvals = load_all_approvals(clean_root)

        from workspace.quant.kitt.brief_producer import _live_approval_state
        la = _live_approval_state("brief-001", approvals)
        assert la["state"] == "no_request"

    def test_brief_helper_approved(self, clean_root):
        _setup_live_queued(clean_root, "brief-002")
        from workspace.quant.shared.approval_bridge import request_live_trade_approval
        request_live_trade_approval(clean_root, "brief-002", symbols=["NQ"])
        approvals = load_all_approvals(clean_root)

        from workspace.quant.kitt.brief_producer import _live_approval_state
        la = _live_approval_state("brief-002", approvals)
        assert la["state"] == "approved"
        assert "execute-live" in la["action"]


# ---------------------------------------------------------------------------
# 3. Brief pipeline section includes LIVE_QUEUED
# ---------------------------------------------------------------------------

class TestBriefPipelineSection:
    def test_live_queued_in_pipeline(self, clean_root):
        """LIVE_QUEUED strategies appear in brief pipeline section."""
        _setup_live_queued(clean_root, "bpipe-001")
        from workspace.quant.kitt.brief_producer import _strategies_by_state, _pipeline_section
        by_state = _strategies_by_state(clean_root)
        section = _pipeline_section(by_state, clean_root)
        assert "LIVE_QUEUED" in section
        assert "bpipe-001" in section
        assert "needs live_trade approval" in section

    def test_live_queued_with_approval_in_pipeline(self, clean_root):
        """LIVE_QUEUED with approval shows ready for execute-live."""
        _setup_live_queued(clean_root, "bpipe-002")
        from workspace.quant.shared.approval_bridge import request_live_trade_approval
        request_live_trade_approval(clean_root, "bpipe-002", symbols=["NQ"])

        from workspace.quant.kitt.brief_producer import _strategies_by_state, _pipeline_section
        by_state = _strategies_by_state(clean_root)
        section = _pipeline_section(by_state, clean_root)
        assert "live-approved" in section


# ---------------------------------------------------------------------------
# 4. Brief operator actions includes LIVE_QUEUED
# ---------------------------------------------------------------------------

class TestBriefOperatorActions:
    def test_live_queued_in_operator_actions(self, clean_root):
        """LIVE_QUEUED shows in operator actions with correct next step."""
        _setup_live_queued(clean_root, "bact-001")
        from workspace.quant.kitt.brief_producer import _strategies_by_state, _operator_actions
        by_state = _strategies_by_state(clean_root)
        actions = _operator_actions(by_state, clean_root)
        assert "request-live" in actions
        assert "bact-001" in actions

    def test_approved_shows_execute(self, clean_root):
        """With live approval, operator action shows execute-live."""
        _setup_live_queued(clean_root, "bact-002")
        from workspace.quant.shared.approval_bridge import request_live_trade_approval
        request_live_trade_approval(clean_root, "bact-002", symbols=["NQ"])

        from workspace.quant.kitt.brief_producer import _strategies_by_state, _operator_actions
        by_state = _strategies_by_state(clean_root)
        actions = _operator_actions(by_state, clean_root)
        assert "execute-live" in actions


# ---------------------------------------------------------------------------
# 5. Full brief integration
# ---------------------------------------------------------------------------

class TestFullBriefIntegration:
    def test_produce_brief_includes_live_queued(self, clean_root):
        """Full brief production includes LIVE_QUEUED visibility."""
        _setup_live_queued(clean_root, "full-001")
        from workspace.quant.kitt.brief_producer import produce_brief
        pkt = produce_brief(clean_root, market_read="Test market read")
        brief_text = pkt.notes
        assert "LIVE_QUEUED" in brief_text
        assert "full-001" in brief_text
        assert "request-live" in brief_text


# ---------------------------------------------------------------------------
# 6. operator_status quant live surface
# ---------------------------------------------------------------------------

class TestOperatorStatusLiveQueued:
    def test_no_request(self, clean_root):
        """operator_status sees LIVE_QUEUED with no live_trade approval."""
        _setup_live_queued(clean_root, "ops-001")
        from unittest.mock import patch
        with patch("scripts.operator_status.ROOT", clean_root):
            from scripts.operator_status import _quant_live_queued
            items = _quant_live_queued()
        assert len(items) == 1
        assert items[0]["strategy_id"] == "ops-001"
        assert items[0]["approval_state"] == "no_request"
        assert "request-live" in items[0]["action"]

    def test_approved(self, clean_root):
        """operator_status sees approved live_trade approval."""
        _setup_live_queued(clean_root, "ops-002")
        from workspace.quant.shared.approval_bridge import request_live_trade_approval
        request_live_trade_approval(clean_root, "ops-002", symbols=["NQ"])
        from unittest.mock import patch
        with patch("scripts.operator_status.ROOT", clean_root):
            from scripts.operator_status import _quant_live_queued
            items = _quant_live_queued()
        assert len(items) == 1
        assert items[0]["approval_state"] == "approved"
        assert "execute-live" in items[0]["action"]

    def test_revoked(self, clean_root):
        """operator_status sees revoked live_trade approval."""
        _setup_live_queued(clean_root, "ops-004")
        from workspace.quant.shared.approval_bridge import request_live_trade_approval
        result = request_live_trade_approval(clean_root, "ops-004", symbols=["NQ"])
        revoke_approval(clean_root, result["approval_ref"])
        from unittest.mock import patch
        with patch("scripts.operator_status.ROOT", clean_root):
            from scripts.operator_status import _quant_live_queued
            items = _quant_live_queued()
        assert len(items) == 1
        assert items[0]["approval_state"] == "revoked"

    def test_terminal_render(self, clean_root):
        """Terminal render includes LIVE QUEUED section."""
        from scripts.operator_status import render_terminal
        data = {
            "ts": "2026-03-19T10:00:00Z",
            "approvals": [], "queued": [], "blocked": [], "failed": [],
            "quant_live_queued": [
                {"strategy_id": "ops-005", "approval_state": "no_request",
                 "approval_ref": None, "action": "request-live ops-005",
                 "label": "needs live_trade approval request"},
            ],
            "timers": [{"unit": "x", "label": "R", "active": True}],
            "outbox": {"pending": 0, "failed": 0},
        }
        text = render_terminal(data)
        assert "LIVE QUEUED" in text
        assert "ops-005" in text

    def test_discord_render(self, clean_root):
        """Discord render includes LIVE_QUEUED section."""
        from scripts.operator_status import render_discord
        data = {
            "ts": "2026-03-19T10:00:00Z",
            "approvals": [], "queued": [], "blocked": [], "failed": [],
            "quant_live_queued": [
                {"strategy_id": "ops-006", "approval_state": "approved",
                 "approval_ref": "qpt_test",
                 "action": "execute-live ops-006 --approval-ref qpt_test",
                 "label": "live-approved, ready for execute-live (qpt_test)"},
            ],
            "timers": [{"unit": "x", "label": "R", "active": True}],
            "outbox": {"pending": 0, "failed": 0},
        }
        text = render_discord(data)
        assert "LIVE_QUEUED" in text
        assert "ops-006" in text
