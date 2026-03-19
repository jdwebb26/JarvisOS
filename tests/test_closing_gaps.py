#!/usr/bin/env python3
"""Tests for the closing-gaps pass: configurable Sigma thresholds,
Hermes watchlist wiring, Kitt feedback-loop visibility, observability.

Proves:
  1. Sigma thresholds come from config and changing config changes behavior
  2. Hermes watchlist drives research work with dedup
  3. Kitt brief includes feedback-loop status
  4. Observability surface (load_thresholds, get_watchlist_status) returns truth
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet, validate_packet
from workspace.quant.shared.packet_store import store_packet
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy,
)


@pytest.fixture
def clean_root(tmp_path):
    """Provide a clean root directory for each test."""
    (tmp_path / "workspace" / "quant" / "shared" / "latest").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "registries").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "config").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "scheduler").mkdir(parents=True)
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
    return tmp_path


# ---- Sigma configurable thresholds ----

class TestSigmaConfigurableThresholds:
    def test_defaults_when_no_config(self, clean_root):
        from workspace.quant.sigma.validation_lane import load_thresholds
        t = load_thresholds(clean_root)
        assert t["validation"]["min_profit_factor"] == 1.3
        assert t["validation"]["min_sharpe"] == 0.8
        assert t["_source"] == "defaults"

    def test_loads_from_config_file(self, clean_root):
        from workspace.quant.sigma.validation_lane import load_thresholds
        cfg = {
            "validation": {"min_profit_factor": 1.5, "min_sharpe": 1.0,
                           "max_drawdown_pct": 0.10, "min_trades": 30},
            "paper_review": {"min_profit_factor": 1.5, "min_sharpe": 1.0,
                             "max_drawdown_pct": 0.10, "min_fill_rate": 0.95,
                             "max_correlation": 0.5},
        }
        path = clean_root / "workspace" / "quant" / "shared" / "config" / "review_thresholds.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        t = load_thresholds(clean_root)
        assert t["validation"]["min_profit_factor"] == 1.5
        assert t["paper_review"]["max_correlation"] == 0.5
        assert "review_thresholds.json" in t["_source"]

    def test_corrupt_config_falls_back(self, clean_root):
        from workspace.quant.sigma.validation_lane import load_thresholds
        path = clean_root / "workspace" / "quant" / "shared" / "config" / "review_thresholds.json"
        path.write_text("{invalid json", encoding="utf-8")
        t = load_thresholds(clean_root)
        assert t["validation"]["min_profit_factor"] == 1.3
        assert "corrupt" in t["_source"]

    def test_changing_config_changes_promotion(self, clean_root):
        """A strategy that passes default gates but fails stricter config."""
        from workspace.quant.atlas.exploration_lane import generate_candidate
        from workspace.quant.sigma.validation_lane import validate_candidate

        c, _ = generate_candidate(clean_root, "cfg-001", "Test strategy")
        transition_strategy(clean_root, "cfg-001", "VALIDATING", actor="sigma")

        # PF=1.4 passes default (1.3) but fails strict (1.5)
        outcome_default, _ = validate_candidate(
            clean_root, c, profit_factor=1.4, sharpe=0.9,
            max_drawdown_pct=0.10, trade_count=25,
        )
        assert outcome_default == "promoted"

        # Now write stricter config
        cfg = {
            "validation": {"min_profit_factor": 1.5, "min_sharpe": 1.0,
                           "max_drawdown_pct": 0.10, "min_trades": 30},
            "paper_review": {"min_profit_factor": 1.5, "min_sharpe": 1.0,
                             "max_drawdown_pct": 0.10, "min_fill_rate": 0.95,
                             "max_correlation": 0.5},
        }
        path = clean_root / "workspace" / "quant" / "shared" / "config" / "review_thresholds.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        c2, _ = generate_candidate(clean_root, "cfg-002", "Another test strategy")
        transition_strategy(clean_root, "cfg-002", "VALIDATING", actor="sigma")

        outcome_strict, _ = validate_candidate(
            clean_root, c2, profit_factor=1.4, sharpe=0.9,
            max_drawdown_pct=0.10, trade_count=25,
        )
        assert outcome_strict == "rejected"

    def test_changing_config_changes_paper_review(self, clean_root):
        from workspace.quant.sigma.validation_lane import review_paper_results

        # PF=1.4 passes default (1.3) review
        outcome1, _ = review_paper_results(
            clean_root, "pr-001", realized_pf=1.4, realized_sharpe=0.9,
            max_drawdown=0.10, avg_slippage=0.001, fill_rate=0.95,
            trade_count=30,
        )
        assert outcome1 == "advance_to_live"

        # Stricter config: PF must be 1.5
        cfg = {
            "validation": {"min_profit_factor": 1.5},
            "paper_review": {"min_profit_factor": 1.5, "min_sharpe": 1.0,
                             "max_drawdown_pct": 0.10, "min_fill_rate": 0.95,
                             "max_correlation": 0.5},
        }
        path = clean_root / "workspace" / "quant" / "shared" / "config" / "review_thresholds.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        outcome2, _ = review_paper_results(
            clean_root, "pr-002", realized_pf=1.4, realized_sharpe=0.9,
            max_drawdown=0.10, avg_slippage=0.001, fill_rate=0.95,
            trade_count=30,
        )
        assert outcome2 == "iterate"  # PF 1.4 < 1.5 now


# ---- Hermes watchlist wiring ----

class TestHermesWatchlist:
    def test_empty_watchlist(self, clean_root):
        from workspace.quant.hermes.research_lane import run_watchlist_batch
        packets, info = run_watchlist_batch(clean_root)
        assert info["watchlist_entries"] == 0

    def test_watchlist_generates_research(self, clean_root):
        from workspace.quant.hermes.research_lane import run_watchlist_batch
        wl = [
            {"topic": "NQ gap patterns", "symbol": "NQ", "source_type": "web", "active": True},
            {"topic": "VIX term structure", "symbol": "VIX", "source_type": "api", "active": True},
        ]
        path = clean_root / "workspace" / "quant" / "shared" / "config" / "watch_list.json"
        path.write_text(json.dumps(wl), encoding="utf-8")

        packets, info = run_watchlist_batch(clean_root)
        assert info["watchlist_entries"] == 2
        assert info["emitted"] >= 1
        assert len(packets) >= 1
        assert packets[0].packet_type == "research_packet"

    def test_watchlist_inactive_skipped(self, clean_root):
        from workspace.quant.hermes.research_lane import run_watchlist_batch
        wl = [
            {"topic": "Active topic", "symbol": "NQ", "active": True},
            {"topic": "Inactive topic", "symbol": "ES", "active": False},
        ]
        path = clean_root / "workspace" / "quant" / "shared" / "config" / "watch_list.json"
        path.write_text(json.dumps(wl), encoding="utf-8")

        packets, info = run_watchlist_batch(clean_root)
        assert info["watchlist_entries"] == 1  # Only active
        assert info["emitted"] == 1

    def test_watchlist_dedup_holds(self, clean_root):
        from workspace.quant.hermes.research_lane import run_watchlist_batch
        wl = [{"topic": "NQ gap patterns", "symbol": "NQ", "active": True}]
        path = clean_root / "workspace" / "quant" / "shared" / "config" / "watch_list.json"
        path.write_text(json.dumps(wl), encoding="utf-8")

        # First run
        packets1, info1 = run_watchlist_batch(clean_root)
        assert info1["emitted"] == 1

        # Second run — should dedup
        packets2, info2 = run_watchlist_batch(clean_root)
        assert info2["deduped"] == 1
        assert info2["emitted"] == 0

    def test_watchlist_status(self, clean_root):
        from workspace.quant.hermes.research_lane import get_watchlist_status
        wl = [
            {"topic": "Active", "active": True},
            {"topic": "Inactive", "active": False},
        ]
        path = clean_root / "workspace" / "quant" / "shared" / "config" / "watch_list.json"
        path.write_text(json.dumps(wl), encoding="utf-8")

        status = get_watchlist_status(clean_root)
        assert status["total"] == 2
        assert status["active"] == 1
        assert status["inactive"] == 1
        assert "Active" in status["topics"]

    def test_watchlist_missing_file(self, clean_root):
        from workspace.quant.hermes.research_lane import get_watchlist_status
        status = get_watchlist_status(clean_root)
        assert status["total"] == 0
        assert "missing" in status["_source"]


# ---- Kitt feedback-loop visibility ----

class TestKittFeedbackLoops:
    def test_brief_includes_feedback_loops_section(self, clean_root):
        from workspace.quant.kitt.brief_producer import produce_brief
        brief = produce_brief(clean_root)
        assert "FEEDBACK LOOPS" in (brief.notes or "")

    def test_brief_shows_atlas_learning(self, clean_root):
        from workspace.quant.atlas.exploration_lane import generate_candidate
        from workspace.quant.kitt.brief_producer import produce_brief

        generate_candidate(clean_root, "fb-001", "Test strategy")
        transition_strategy(clean_root, "fb-001", "VALIDATING", actor="sigma")
        rej = make_packet("strategy_rejection_packet", "sigma", "Rejected",
                          strategy_id="fb-001", rejection_reason="poor_oos",
                          rejection_detail="PF 0.8")
        store_packet(clean_root, rej)

        brief = produce_brief(clean_root)
        notes = brief.notes or ""
        assert "atlas" in notes.lower()
        assert "rejection" in notes.lower() or "adapted" in notes.lower()

    def test_brief_shows_fish_calibration(self, clean_root):
        from workspace.quant.fish.scenario_lane import emit_forecast, calibrate
        from workspace.quant.kitt.brief_producer import produce_brief

        f = emit_forecast(clean_root, "NQ bullish", confidence=0.6,
                          forecast_value=18000.0, forecast_direction="bullish")
        calibrate(clean_root, f, 18050.0, "bullish")

        brief = produce_brief(clean_root)
        notes = brief.notes or ""
        assert "fish" in notes.lower()
        assert "calibration" in notes.lower() or "hit_rate" in notes.lower()

    def test_brief_shows_sigma_pressure(self, clean_root):
        from workspace.quant.kitt.brief_producer import produce_brief

        store_packet(clean_root, make_packet(
            "promotion_packet", "sigma", "Promoted strategy", strategy_id="sig-001"))

        brief = produce_brief(clean_root)
        notes = brief.notes or ""
        assert "sigma" in notes.lower()
        assert "promoted" in notes.lower()

    def test_brief_shows_tradefloor_tier(self, clean_root):
        from workspace.quant.kitt.brief_producer import produce_brief

        store_packet(clean_root, make_packet(
            "tradefloor_packet", "tradefloor", "Tier 2 synthesis",
            agreement_tier=2, agreement_tier_reasoning="Strong alignment",
            notes="risk_zones=1"))

        brief = produce_brief(clean_root)
        notes = brief.notes or ""
        assert "floor" in notes.lower()
        assert "tier=2" in notes or "tier: 2" in notes or "Agreement tier: 2" in notes


# ---- Observability ----

class TestObservability:
    def test_load_thresholds_exposes_source(self, clean_root):
        from workspace.quant.sigma.validation_lane import load_thresholds
        t = load_thresholds(clean_root)
        assert "_source" in t

    def test_watchlist_status_exposes_source(self, clean_root):
        from workspace.quant.hermes.research_lane import get_watchlist_status
        s = get_watchlist_status(clean_root)
        assert "_source" in s
