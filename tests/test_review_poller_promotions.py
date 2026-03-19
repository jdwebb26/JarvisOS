#!/usr/bin/env python3
"""Tests proving the review poller correctly routes promotion decisions.

Acceptance criteria:
  1. Poller recognizes promo_ IDs in approval patterns
  2. approve promo_xxx routes to handle_promotion_decision → LIVE_QUEUED
  3. reject promo_xxx routes to handle_promotion_decision → PAPER_KILLED
  4. rerun promo_xxx routes to handle_promotion_decision → ITERATE
  5. Duplicate decisions are safe
  6. No auto-live execution
  7. Existing pulse_/qpt_/apr_ routing is preserved
"""
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest


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
    """Push strategy to PAPER_REVIEW with promotion artifact. Returns promotion_id."""
    from workspace.quant.shared.schemas.packets import make_packet
    from workspace.quant.shared.packet_store import store_packet
    from workspace.quant.shared.registries.strategy_registry import (
        create_strategy, transition_strategy,
    )
    from workspace.quant.shared.registries.approval_registry import (
        create_approval, ApprovedActions,
    )
    from workspace.quant.sigma.validation_lane import validate_candidate
    from workspace.quant.executor.executor_lane import execute_paper_trade
    from workspace.quant.executor.proof_tracker import (
        get_active_run, save_paper_run, evaluate_proof, load_paper_run,
    )

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

    from workspace.quant.shared.registries.strategy_registry import get_strategy
    assert get_strategy(root, sid).lifecycle_state == "PAPER_REVIEW"

    reloaded = load_paper_run(root, run.paper_run_id)
    return reloaded.promotion_id


# ---------------------------------------------------------------------------
# Pattern matching — promo_ IDs recognized
# ---------------------------------------------------------------------------

class TestPatternRecognition:
    def test_approval_id_pattern_matches_promo(self):
        from scripts.discord_review_poller import APPROVAL_ID_PATTERN
        assert APPROVAL_ID_PATTERN.search("approve promo_strat-001_abc12345")
        assert APPROVAL_ID_PATTERN.search("reject promo_atlas-gap-65f8a3d6_deadbeef")

    def test_approve_pattern_matches_promo(self):
        from scripts.discord_review_poller import APPROVE_PATTERN
        m = APPROVE_PATTERN.match("approve promo_strat-001_abc12345")
        assert m is not None
        assert m.group(1) == "promo_strat-001_abc12345"

    def test_reject_pattern_matches_promo(self):
        from scripts.discord_review_poller import REJECT_PATTERN
        m = REJECT_PATTERN.match("reject promo_strat-001_abc12345 too risky")
        assert m is not None
        assert m.group(1) == "promo_strat-001_abc12345"
        assert m.group(2).strip() == "too risky"

    def test_rerun_pattern_matches_promo(self):
        from scripts.discord_review_poller import RERUN_PATTERN
        m = RERUN_PATTERN.match("rerun promo_strat-001_abc12345 need more data")
        assert m is not None
        assert m.group(1) == "promo_strat-001_abc12345"

    def test_existing_patterns_still_work(self):
        from scripts.discord_review_poller import APPROVE_PATTERN, REJECT_PATTERN, APPROVAL_ID_PATTERN
        # qpt_ still works
        assert APPROVE_PATTERN.match("approve qpt_abc123def456")
        # pulse_ still works
        assert REJECT_PATTERN.match("reject pulse_abc123def456")
        # apr_ still works
        assert APPROVAL_ID_PATTERN.search("approve apr_deadbeef01")


# ---------------------------------------------------------------------------
# Routing — promo_ goes to handle_promotion_decision
# ---------------------------------------------------------------------------

class TestPollerRouting:
    def test_approve_routes_to_live_queued(self, clean_root):
        """Approving promo_ via poller routing moves strategy to LIVE_QUEUED."""
        promo_id = _setup_paper_review(clean_root, "route-001")

        # Simulate what the poller does: call_approval_endpoint
        # We monkeypatch ROOT so the poller uses our test root
        import scripts.discord_review_poller as poller
        orig_root = poller.ROOT
        poller.ROOT = clean_root
        try:
            result = poller.call_approval_endpoint(promo_id, "approved", reason="Looks good")
        finally:
            poller.ROOT = orig_root

        assert result["ok"] is True
        assert result["new_state"] == "LIVE_QUEUED"

        from workspace.quant.shared.registries.strategy_registry import get_strategy
        s = get_strategy(clean_root, "route-001")
        assert s.lifecycle_state == "LIVE_QUEUED"

    def test_reject_routes_to_paper_killed(self, clean_root):
        promo_id = _setup_paper_review(clean_root, "route-002")

        import scripts.discord_review_poller as poller
        orig_root = poller.ROOT
        poller.ROOT = clean_root
        try:
            result = poller.call_approval_endpoint(promo_id, "rejected", reason="Too risky")
        finally:
            poller.ROOT = orig_root

        assert result["ok"] is True
        assert result["new_state"] == "PAPER_KILLED"

    def test_rerun_routes_to_iterate(self, clean_root):
        promo_id = _setup_paper_review(clean_root, "route-003")

        import scripts.discord_review_poller as poller
        orig_root = poller.ROOT
        poller.ROOT = clean_root
        try:
            result = poller.call_approval_endpoint(promo_id, "rerun_paper", reason="Need more regimes")
        finally:
            poller.ROOT = orig_root

        assert result["ok"] is True
        assert result["new_state"] == "ITERATE"

    def test_no_auto_live_execution(self, clean_root):
        """Approve goes to LIVE_QUEUED, NOT LIVE_ACTIVE."""
        promo_id = _setup_paper_review(clean_root, "route-004")

        import scripts.discord_review_poller as poller
        orig_root = poller.ROOT
        poller.ROOT = clean_root
        try:
            poller.call_approval_endpoint(promo_id, "approved")
        finally:
            poller.ROOT = orig_root

        from workspace.quant.shared.registries.strategy_registry import get_strategy
        s = get_strategy(clean_root, "route-004")
        assert s.lifecycle_state == "LIVE_QUEUED"
        assert s.lifecycle_state != "LIVE_ACTIVE"

    def test_duplicate_decision_safe(self, clean_root):
        promo_id = _setup_paper_review(clean_root, "route-005")

        import scripts.discord_review_poller as poller
        orig_root = poller.ROOT
        poller.ROOT = clean_root
        try:
            r1 = poller.call_approval_endpoint(promo_id, "approved")
            r2 = poller.call_approval_endpoint(promo_id, "approved")
        finally:
            poller.ROOT = orig_root

        assert r1["ok"] is True
        assert r2["ok"] is False  # Already decided
