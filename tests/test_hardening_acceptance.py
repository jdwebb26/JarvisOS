#!/usr/bin/env python3
"""Hardening and final acceptance tests for the quant lanes system.

Tests:
  1. Lane health summaries (Sigma, Executor, TradeFloor)
  2. Silent/stale lane detection
  3. Kill switch enforcement
  4. Portfolio risk checks
  5. Governor visibility
  6. Final end-to-end acceptance proof
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet, validate_packet
from workspace.quant.shared.packet_store import store_packet, get_latest, list_lane_packets
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, get_strategy, load_all_strategies,
)
from workspace.quant.shared.registries.approval_registry import (
    create_approval, ApprovedActions,
)


@pytest.fixture
def clean_root(tmp_path):
    """Provide a clean root directory for each test."""
    (tmp_path / "workspace" / "quant" / "shared" / "latest").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "registries").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "config").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "scheduler").mkdir(parents=True)
    (tmp_path / "state" / "quant" / "executor").mkdir(parents=True)
    for lane in ["atlas", "fish", "hermes", "sigma", "kitt", "tradefloor", "executor"]:
        (tmp_path / "workspace" / "quant" / lane).mkdir(parents=True)

    hosts = {
        "hosts": {
            "NIMO": {"role": "primary", "specs": "128GB", "heavy_job_cap": 2, "ip": "127.0.0.1"},
            "SonLM": {"role": "secondary", "specs": "lighter", "heavy_job_cap": 1, "ip": None},
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

    (tmp_path / "workspace" / "quant" / "shared" / "config" / "kill_switch.json").write_text(
        json.dumps({"engaged": False, "engaged_at": None, "engaged_by": None, "reason": None}),
        encoding="utf-8",
    )

    (tmp_path / "workspace" / "quant" / "shared" / "config" / "risk_limits.json").write_text(
        json.dumps({
            "portfolio": {
                "max_total_exposure": 4,
                "max_correlated_strategies": 3,
                "max_total_drawdown": 5000,
                "concentration_threshold": 0.6,
            },
            "per_strategy": {
                "max_position_size": 2,
                "max_loss_per_trade": 500,
                "max_drawdown": 2000,
            },
        }, indent=2), encoding="utf-8",
    )

    return tmp_path


# ---- Lane health summaries ----

class TestSigmaHealthSummary:
    def test_sigma_health_emits_valid_packet(self, clean_root):
        from workspace.quant.sigma.validation_lane import emit_health_summary
        h = emit_health_summary(
            clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 5,
            validations_done=3, promotions=1, rejections=2,
        )
        assert validate_packet(h) == []
        assert h.lane == "sigma"
        assert h.packet_type == "health_summary"
        assert h.governor_action_taken in ("push", "hold", "backoff", "pause")

    def test_sigma_health_includes_counts(self, clean_root):
        from workspace.quant.sigma.validation_lane import emit_health_summary
        h = emit_health_summary(
            clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 5,
            promotions=2, rejections=3,
        )
        assert "promoted" in h.thesis or "promoted" in (h.notable_events or "")


class TestExecutorHealthSummary:
    def test_executor_health_emits_valid_packet(self, clean_root):
        from workspace.quant.executor.executor_lane import emit_health_summary
        h = emit_health_summary(
            clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 3,
            executions_attempted=2, executions_filled=1, executions_rejected=1,
        )
        assert validate_packet(h) == []
        assert h.lane == "executor"
        assert h.governor_action_taken in ("push", "hold", "backoff", "pause")

    def test_executor_health_shows_kill_switch(self, clean_root):
        # Engage kill switch
        ks_path = clean_root / "workspace" / "quant" / "shared" / "config" / "kill_switch.json"
        ks_path.write_text(json.dumps({"engaged": True, "reason": "test"}), encoding="utf-8")

        from workspace.quant.executor.executor_lane import emit_health_summary
        h = emit_health_summary(
            clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 0,
        )
        assert "ENGAGED" in h.thesis

    def test_executor_health_shows_portfolio_exposure(self, clean_root):
        from workspace.quant.executor.executor_lane import emit_health_summary
        h = emit_health_summary(
            clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 0,
        )
        assert "portfolio_exposure" in h.thesis


class TestTradeFloorHealthSummary:
    def test_tradefloor_health_emits_valid_packet(self, clean_root):
        from workspace.quant.tradefloor.synthesis_lane import emit_health_summary
        h = emit_health_summary(
            clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 2,
            syntheses_run=1, cadence_refusals=1,
        )
        assert validate_packet(h) == []
        assert h.lane == "tradefloor"
        assert h.governor_action_taken in ("push", "hold", "backoff", "pause")


# ---- Stale lane detection ----

class TestStaleLaneDetection:
    def test_empty_lanes_are_stale(self, clean_root):
        from workspace.quant.shared.restart import check_stale_lanes
        result = check_stale_lanes(clean_root)
        for lane in ["atlas", "fish", "hermes", "sigma", "kitt", "executor"]:
            assert result[lane]["stale"] is True
            assert result[lane]["last_packet_id"] is None

    def test_recent_packet_not_stale(self, clean_root):
        from workspace.quant.shared.restart import check_stale_lanes
        store_packet(clean_root, make_packet(
            "research_packet", "hermes", "Fresh research", confidence=0.5))
        result = check_stale_lanes(clean_root)
        assert result["hermes"]["stale"] is False
        assert result["hermes"]["last_packet_age_hours"] < 1.0

    def test_tradefloor_excluded(self, clean_root):
        from workspace.quant.shared.restart import check_stale_lanes
        result = check_stale_lanes(clean_root)
        assert "tradefloor" not in result  # On-demand, not expected to be regular


# ---- Kill switch ----

class TestKillSwitch:
    def test_kill_switch_off_by_default(self, clean_root):
        from workspace.quant.shared.restart import check_kill_switch
        ks = check_kill_switch(clean_root)
        assert ks["engaged"] is False

    def test_kill_switch_engaged_blocks_execution(self, clean_root):
        ks_path = clean_root / "workspace" / "quant" / "shared" / "config" / "kill_switch.json"
        ks_path.write_text(json.dumps({
            "engaged": True, "engaged_at": "2026-01-01T00:00:00Z",
            "reason": "emergency",
        }), encoding="utf-8")

        from workspace.quant.shared.restart import check_kill_switch
        ks = check_kill_switch(clean_root)
        assert ks["engaged"] is True
        assert ks["reason"] == "emergency"

        # Executor should refuse
        from workspace.quant.executor.executor_lane import execute_paper_trade
        create_strategy(clean_root, "ks-001", actor="atlas")
        result = execute_paper_trade(
            clean_root, "ks-001", "fake-ref", "NQ", "long",
        )
        assert result["success"] is False
        assert result["rejection_reason"] == "kill_switch_engaged"


# ---- Portfolio risk ----

class TestPortfolioRisk:
    def test_no_active_strategies_ok(self, clean_root):
        from workspace.quant.executor.executor_lane import check_portfolio_risk
        risk = check_portfolio_risk(clean_root)
        assert risk["ok"] is True
        assert risk["exposure"] == 0

    def test_within_limits(self, clean_root):
        from workspace.quant.executor.executor_lane import check_portfolio_risk
        create_strategy(clean_root, "pr-001", actor="atlas")
        transition_strategy(clean_root, "pr-001", "CANDIDATE", actor="atlas")
        transition_strategy(clean_root, "pr-001", "VALIDATING", actor="sigma")
        transition_strategy(clean_root, "pr-001", "PROMOTED", actor="sigma")
        transition_strategy(clean_root, "pr-001", "PAPER_QUEUED", actor="kitt",
                            approval_ref="apr-001")
        transition_strategy(clean_root, "pr-001", "PAPER_ACTIVE", actor="executor")

        risk = check_portfolio_risk(clean_root)
        assert risk["ok"] is True
        assert risk["exposure"] == 1


# ---- Governor visibility ----

class TestGovernorVisibility:
    def test_governor_state_in_health(self, clean_root):
        from workspace.quant.shared.governor import evaluate_cycle, get_lane_params
        # Push atlas
        evaluate_cycle(clean_root, "atlas",
                       usefulness_score=0.7, efficiency_score=0.6,
                       health_score=0.9, confidence_score=0.7)
        params = get_lane_params(clean_root, "atlas")
        assert params["batch_size"] == 2

        # Verify atlas health summary includes governor action
        from workspace.quant.atlas.exploration_lane import emit_health_summary
        h = emit_health_summary(
            clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 5,
        )
        assert h.governor_action_taken in ("push", "hold", "backoff", "pause")

    def test_paused_lane_visible(self, clean_root):
        from workspace.quant.shared.governor import evaluate_cycle, get_lane_params
        evaluate_cycle(clean_root, "fish",
                       usefulness_score=0.1, efficiency_score=0.1,
                       health_score=0.1, confidence_score=0.1)
        params = get_lane_params(clean_root, "fish")
        assert params["paused"] is True


# ---- Final end-to-end acceptance ----

class TestFinalAcceptance:
    """Full pipeline proof: Atlas → Sigma → Atlas learns → Fish calibrates →
    TradeFloor synthesizes → Kitt surfaces → approval → executor preflight →
    health/risk/governor visible."""

    def test_full_pipeline(self, clean_root):
        from workspace.quant.atlas.exploration_lane import (
            generate_candidate, emit_failure_learning, emit_health_summary as atlas_health,
        )
        from workspace.quant.sigma.validation_lane import (
            validate_candidate, emit_health_summary as sigma_health,
        )
        from workspace.quant.fish.scenario_lane import (
            emit_forecast, calibrate, emit_risk_map,
            emit_health_summary as fish_health, build_calibration_state,
        )
        from workspace.quant.hermes.research_lane import emit_research
        from workspace.quant.tradefloor.synthesis_lane import (
            synthesize, emit_health_summary as tf_health,
        )
        from workspace.quant.kitt.brief_producer import produce_brief
        from workspace.quant.executor.executor_lane import (
            execute_paper_trade, check_portfolio_risk,
            emit_health_summary as exec_health,
        )
        from workspace.quant.shared.restart import check_stale_lanes, check_kill_switch

        # ---- Step 1: Hermes research ----
        research = emit_research(clean_root, "NQ bullish momentum research",
                                 source="vol-api", source_type="api")
        assert research is not None

        # ---- Step 2: Atlas proposes (first candidate) ----
        c1, fb1 = generate_candidate(clean_root, "acc-001", "NQ simple gap fade",
                                     evidence_refs=[research.packet_id])
        assert fb1["adapted"] is False

        # ---- Step 3: Sigma rejects ----
        transition_strategy(clean_root, "acc-001", "VALIDATING", actor="sigma")
        outcome1, rej_pkt = validate_candidate(
            clean_root, c1, profit_factor=0.7, sharpe=0.3,
            max_drawdown_pct=0.25, trade_count=8,
        )
        assert outcome1 == "rejected"
        s1 = get_strategy(clean_root, "acc-001")
        assert s1.lifecycle_state == "REJECTED"

        # ---- Step 4: Atlas learns from rejection ----
        emit_failure_learning(clean_root, rej_pkt, "Gap fade needs regime filter for OOS")
        c2, fb2 = generate_candidate(
            clean_root, "acc-002", "NQ robust breakout with regime filter and OOS validation",
            parent_id="acc-001",
        )
        assert fb2["adapted"] is True
        assert fb2["param_adjustments"] != {}

        # ---- Step 5: Sigma promotes ----
        transition_strategy(clean_root, "acc-002", "VALIDATING", actor="sigma")
        outcome2, promo_pkt = validate_candidate(
            clean_root, c2, profit_factor=1.8, sharpe=1.2,
            max_drawdown_pct=0.08, trade_count=45,
        )
        assert outcome2 == "promoted"
        s2 = get_strategy(clean_root, "acc-002")
        assert s2.lifecycle_state == "PROMOTED"

        # ---- Step 6: Fish calibrates ----
        f1 = emit_forecast(clean_root, "NQ bullish into FOMC", confidence=0.6,
                           forecast_value=18400.0, forecast_direction="bullish")
        cal1, r1 = calibrate(clean_root, f1, 18380.0, "bullish")
        assert r1["direction_correct"] is True

        f2 = emit_forecast(clean_root, "NQ continued upside", confidence=r1["adjusted_confidence"],
                           forecast_value=18500.0, forecast_direction="bullish")
        cal2, r2 = calibrate(clean_root, f2, 18200.0, "bearish")
        assert r2["direction_correct"] is False
        assert r2["adjusted_confidence"] < r1["adjusted_confidence"]

        cal_state = build_calibration_state(clean_root)
        assert cal_state["total_calibrations"] == 2
        assert cal_state["direction_hits"] == 1
        assert cal_state["direction_misses"] == 1

        # ---- Step 7: Fish risk map ----
        emit_risk_map(clean_root, "VIX elevated",
                      risk_zones={"vix_spike": {"level": "high", "trigger": "VIX > 28"}})

        # ---- Step 8: TradeFloor synthesizes ----
        # Seed kitt brief for synthesis
        store_packet(clean_root, make_packet(
            "brief_packet", "kitt", "Market bullish outlook, strong NQ setups",
            confidence=0.65))

        tf_pkt = synthesize(clean_root)
        assert validate_packet(tf_pkt) == []
        assert tf_pkt.agreement_tier is not None
        assert len(tf_pkt.evidence_refs) > 0
        # Risk zone should appear
        assert "vix_spike" in (tf_pkt.confidence_weighted_synthesis or "")

        # ---- Step 9: Kitt surfaces ----
        brief = produce_brief(clean_root)
        assert validate_packet(brief) == []
        assert "TRADEFLOOR" in (brief.notes or "")
        assert "PIPELINE" in (brief.notes or "")

        # ---- Step 10: Approval flow ----
        transition_strategy(clean_root, "acc-002", "PAPER_QUEUED", actor="kitt",
                            approval_ref="approval-test-001")
        appr = create_approval(
            clean_root, strategy_id="acc-002", approval_type="paper_trade",
            approved_actions=ApprovedActions(
                execution_mode="paper", symbols=["NQ"],
                max_position_size=2, max_loss_per_trade=500,
                max_total_drawdown=2000, slippage_tolerance=0.05,
            ),
        )
        assert appr.approval_ref.startswith("qpt_")

        # ---- Step 11: Executor preflight works ----
        exec_result = execute_paper_trade(
            clean_root, "acc-002", appr.approval_ref, "NQ", "long",
            quantity=1, simulated_price=18300.0,
        )
        assert exec_result["success"] is True
        assert exec_result["fill"] is not None
        s2_after = get_strategy(clean_root, "acc-002")
        assert s2_after.lifecycle_state == "PAPER_ACTIVE"

        # ---- Step 12: Portfolio risk visible ----
        risk = check_portfolio_risk(clean_root)
        assert risk["ok"] is True
        assert risk["exposure"] == 1

        # ---- Step 13: Kill switch check ----
        ks = check_kill_switch(clean_root)
        assert ks["engaged"] is False

        # ---- Step 14: Stale lane detection ----
        stale = check_stale_lanes(clean_root)
        # Lanes that produced packets should not be stale
        assert stale["hermes"]["stale"] is False
        assert stale["atlas"]["stale"] is False
        assert stale["sigma"]["stale"] is False
        assert stale["fish"]["stale"] is False

        # ---- Step 15: Health summaries for all lanes ----
        h_atlas = atlas_health(clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 5,
                               candidates_generated=2, rejections_ingested=1)
        h_sigma = sigma_health(clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 5,
                               validations_done=2, promotions=1, rejections=1)
        h_fish = fish_health(clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 4,
                             forecasts_emitted=2, calibrations_done=2)
        h_tf = tf_health(clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 1,
                         syntheses_run=1)
        h_exec = exec_health(clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 2,
                             executions_attempted=1, executions_filled=1)

        for h in [h_atlas, h_sigma, h_fish, h_tf, h_exec]:
            assert validate_packet(h) == []
            assert h.packet_type == "health_summary"
            assert h.governor_action_taken in ("push", "hold", "backoff", "pause")

        # ---- Step 16: Governor visible ----
        from workspace.quant.shared.governor import load_governor_state
        gov = load_governor_state(clean_root)
        # All lanes should have governor state after health summary emission
        for lane in ["atlas", "sigma", "fish", "tradefloor", "executor"]:
            assert lane in gov

    def test_kill_switch_blocks_during_pipeline(self, clean_root):
        """Kill switch engaged mid-pipeline blocks executor."""
        from workspace.quant.atlas.exploration_lane import generate_candidate
        from workspace.quant.sigma.validation_lane import validate_candidate
        from workspace.quant.executor.executor_lane import execute_paper_trade

        c1, _ = generate_candidate(clean_root, "ks-pipe-001", "NQ strategy")
        transition_strategy(clean_root, "ks-pipe-001", "VALIDATING", actor="sigma")
        validate_candidate(clean_root, c1, profit_factor=1.8, sharpe=1.2,
                           max_drawdown_pct=0.08, trade_count=45)
        transition_strategy(clean_root, "ks-pipe-001", "PAPER_QUEUED", actor="kitt",
                            approval_ref="apr-ks")
        create_approval(clean_root, strategy_id="ks-pipe-001", approval_type="paper_trade",
                        approved_actions=ApprovedActions(
                            execution_mode="paper", symbols=["NQ"],
                            max_position_size=2, max_loss_per_trade=500,
                            max_total_drawdown=2000, slippage_tolerance=0.05,
                        ))

        # Engage kill switch
        ks_path = clean_root / "workspace" / "quant" / "shared" / "config" / "kill_switch.json"
        ks_path.write_text(json.dumps({"engaged": True, "reason": "emergency"}),
                           encoding="utf-8")

        from workspace.quant.shared.registries.approval_registry import load_all_approvals
        appr = load_all_approvals(clean_root)[-1]
        result = execute_paper_trade(
            clean_root, "ks-pipe-001", appr.approval_ref, "NQ", "long",
        )
        assert result["success"] is False
        assert result["rejection_reason"] == "kill_switch_engaged"
