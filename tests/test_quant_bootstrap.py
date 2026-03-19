#!/usr/bin/env python3
"""Tests proving quant lane bootstrap / cold-start behavior.

Acceptance criteria:
  1. Hermes can cold-start from its configured watchlist
  2. Fish can cold-start with believable regimes/scenarios without fake history
  3. Atlas can cold-start from seed themes without junk explosion
  4. Bootstrap commands are idempotent (repeat runs don't duplicate)
  5. TradeFloor does not synthesize from empty/insufficient upstream
  6. Bootstrap status reports truth about lane state
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet, validate_packet
from workspace.quant.shared.packet_store import store_packet, list_lane_packets
from workspace.quant.bootstrap import (
    bootstrap_hermes, bootstrap_fish, bootstrap_atlas,
    bootstrap_tradefloor, bootstrap_all,
    get_lane_bootstrap_status, get_all_bootstrap_status,
    _load_bootstrap_state,
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
        "batch_size": 3, "max_iterations": 5, "cooldown_interval": 0,
        "cloud_burst_allowed": False, "escalation_threshold": 0.6,
        "cadence_multiplier": 1.0, "consecutive_backoff_cycles": 0, "paused": False,
    } for lane in ["atlas", "fish", "hermes", "tradefloor", "kitt", "sigma", "executor"]}
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "governor_state.json").write_text(
        json.dumps(gov, indent=2), encoding="utf-8"
    )

    # Install watchlist
    watchlist = [
        {"topic": "NQ overnight gap patterns", "symbol": "NQ", "source_type": "web", "active": True},
        {"topic": "VIX term structure", "symbol": "VIX", "source_type": "api", "active": True},
        {"topic": "Fed funds rate", "symbol": "NQ", "source_type": "official_doc", "active": True},
    ]
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "watch_list.json").write_text(
        json.dumps(watchlist, indent=2), encoding="utf-8"
    )

    # Install fish bootstrap config
    fish_config = {
        "seed_regimes": [
            {"label": "trending_bull", "thesis": "NQ in sustained uptrend", "confidence": 0.4},
            {"label": "range_bound", "thesis": "NQ consolidating in range", "confidence": 0.5},
        ],
        "seed_scenarios": [
            {"thesis": "NQ overnight gap reversal", "symbol_scope": "NQ",
             "timeframe_scope": "1D", "confidence": 0.4},
            {"thesis": "NQ mean-reversion at VWAP", "symbol_scope": "NQ",
             "timeframe_scope": "4H", "confidence": 0.4},
        ],
        "seed_risk_zones": {
            "vix_elevation": {"level": "medium", "trigger": "VIX > 20"},
        },
    }
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "fish_bootstrap.json").write_text(
        json.dumps(fish_config, indent=2), encoding="utf-8"
    )

    # Install atlas sources config
    atlas_config = {
        "seed_themes": [
            {"thesis": "NQ overnight gap fade strategy", "symbol_scope": "NQ",
             "timeframe_scope": "15m", "confidence": 0.4, "strategy_prefix": "atlas-gap"},
            {"thesis": "NQ VWAP reversion strategy", "symbol_scope": "NQ",
             "timeframe_scope": "15m", "confidence": 0.4, "strategy_prefix": "atlas-vwap"},
        ],
        "max_bootstrap_candidates": 2,
        "require_hermes_evidence": False,
    }
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "atlas_sources.json").write_text(
        json.dumps(atlas_config, indent=2), encoding="utf-8"
    )

    return tmp_path


# ---------------------------------------------------------------------------
# Hermes bootstrap
# ---------------------------------------------------------------------------

class TestHermesBootstrap:
    def test_cold_start_from_watchlist(self, clean_root):
        """Hermes produces research packets from its watchlist on cold start."""
        result = bootstrap_hermes(clean_root)
        assert result["emitted"] > 0
        assert result["watchlist_entries"] == 3

        # Verify packets were actually created
        packets = list_lane_packets(clean_root, "hermes", "research_packet")
        assert len(packets) == result["emitted"]
        for pkt in packets:
            errors = validate_packet(pkt)
            assert errors == [], f"Packet validation errors: {errors}"

    def test_idempotent_repeat_run(self, clean_root):
        """Second run deduplicates — does not produce duplicate packets."""
        r1 = bootstrap_hermes(clean_root)
        assert r1["emitted"] > 0
        first_count = r1["emitted"]

        r2 = bootstrap_hermes(clean_root)
        # All should be deduped on second run
        assert r2["deduped"] >= first_count or r2["already_bootstrapped"]
        assert r2["emitted"] == 0

    def test_empty_watchlist_produces_nothing(self, clean_root):
        """Empty watchlist produces nothing, no errors."""
        (clean_root / "workspace" / "quant" / "shared" / "config" / "watch_list.json").write_text(
            "[]", encoding="utf-8"
        )
        result = bootstrap_hermes(clean_root)
        assert result["emitted"] == 0
        assert result["watchlist_entries"] == 0

    def test_governor_paused_skips(self, clean_root):
        """Governor-paused Hermes skips bootstrap."""
        gov_path = clean_root / "workspace" / "quant" / "shared" / "config" / "governor_state.json"
        gov = json.loads(gov_path.read_text(encoding="utf-8"))
        gov["hermes"]["paused"] = True
        gov_path.write_text(json.dumps(gov, indent=2), encoding="utf-8")

        result = bootstrap_hermes(clean_root)
        assert result["emitted"] == 0
        assert result.get("skipped_reason") == "governor_paused"


# ---------------------------------------------------------------------------
# Fish bootstrap
# ---------------------------------------------------------------------------

class TestFishBootstrap:
    def test_cold_start_creates_regimes_scenarios_riskmap(self, clean_root):
        """Fish produces seed regimes, scenarios, and risk map from config."""
        result = bootstrap_fish(clean_root)
        assert result["regimes_emitted"] == 2
        assert result["scenarios_emitted"] == 2
        assert result["risk_maps_emitted"] == 1

        # Verify packets
        regimes = list_lane_packets(clean_root, "fish", "regime_packet")
        scenarios = list_lane_packets(clean_root, "fish", "scenario_packet")
        risk_maps = list_lane_packets(clean_root, "fish", "risk_map_packet")
        assert len(regimes) == 2
        assert len(scenarios) == 2
        assert len(risk_maps) == 1

    def test_no_fake_calibration_history(self, clean_root):
        """Bootstrap does NOT create fake calibration data."""
        result = bootstrap_fish(clean_root)
        cal = result.get("calibration_state", {})
        assert cal["total_calibrations"] == 0
        assert cal["trend"] == "insufficient_data"

        # Verify: no calibration packets exist
        calibrations = list_lane_packets(clean_root, "fish", "calibration_packet")
        assert len(calibrations) == 0

    def test_idempotent_repeat_run(self, clean_root):
        """Second run detects existing scenarios and skips."""
        r1 = bootstrap_fish(clean_root)
        assert r1["scenarios_emitted"] > 0

        r2 = bootstrap_fish(clean_root)
        assert r2["already_bootstrapped"] is True
        assert r2["scenarios_emitted"] == 0
        assert r2["regimes_emitted"] == 0

    def test_no_config_skips(self, clean_root):
        """Missing fish_bootstrap.json skips gracefully."""
        (clean_root / "workspace" / "quant" / "shared" / "config" / "fish_bootstrap.json").unlink()
        result = bootstrap_fish(clean_root)
        assert result.get("skipped_reason") == "no_config"

    def test_regime_labels_are_meaningful(self, clean_root):
        """Seed regimes have real labels, not placeholder junk."""
        bootstrap_fish(clean_root)
        regimes = list_lane_packets(clean_root, "fish", "regime_packet")
        labels = set()
        for r in regimes:
            notes = r.notes or ""
            for part in notes.split(";"):
                part = part.strip()
                if part.startswith("regime="):
                    labels.add(part.split("=", 1)[1])
        assert len(labels) > 0
        for label in labels:
            assert len(label) > 3  # Not empty junk
            assert label != "unknown"


# ---------------------------------------------------------------------------
# Atlas bootstrap
# ---------------------------------------------------------------------------

class TestAtlasBootstrap:
    def test_cold_start_generates_candidates(self, clean_root):
        """Atlas generates bounded candidates from seed themes."""
        result = bootstrap_atlas(clean_root)
        assert result["candidates_generated"] > 0
        assert result["candidates_generated"] <= 2  # max_bootstrap_candidates

        # Verify strategies exist and are valid
        from workspace.quant.shared.registries.strategy_registry import load_all_strategies
        strategies = load_all_strategies(clean_root)
        real = {sid: s for sid, s in strategies.items()
                if not any(m in sid.lower() for m in ("proof", "smoke", "test-", "phase0"))}
        assert len(real) == result["candidates_generated"]

    def test_bounded_candidate_count(self, clean_root):
        """Atlas does not exceed max_bootstrap_candidates."""
        result = bootstrap_atlas(clean_root)
        assert result["candidates_generated"] <= 2

    def test_idempotent_repeat_run(self, clean_root):
        """Second run detects existing strategies and skips."""
        r1 = bootstrap_atlas(clean_root)
        assert r1["candidates_generated"] > 0

        r2 = bootstrap_atlas(clean_root)
        assert r2["already_bootstrapped"] is True
        assert r2["candidates_generated"] == 0

    def test_requires_hermes_evidence_when_configured(self, clean_root):
        """Atlas skips when require_hermes_evidence=True and no Hermes packets."""
        config_path = clean_root / "workspace" / "quant" / "shared" / "config" / "atlas_sources.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["require_hermes_evidence"] = True
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        result = bootstrap_atlas(clean_root)
        assert result.get("skipped_reason") == "no_hermes_evidence"
        assert result["candidates_generated"] == 0

    def test_links_hermes_evidence_when_available(self, clean_root):
        """Atlas links to Hermes research packets as evidence."""
        # First bootstrap Hermes
        bootstrap_hermes(clean_root)

        # Enable require_hermes_evidence
        config_path = clean_root / "workspace" / "quant" / "shared" / "config" / "atlas_sources.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["require_hermes_evidence"] = True
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        result = bootstrap_atlas(clean_root)
        assert result["candidates_generated"] > 0

        # Verify evidence refs point to Hermes packets
        candidates = list_lane_packets(clean_root, "atlas", "candidate_packet")
        for c in candidates:
            assert len(c.evidence_refs) > 0
            for ref in c.evidence_refs:
                assert ref.startswith("hermes-")


# ---------------------------------------------------------------------------
# TradeFloor bootstrap
# ---------------------------------------------------------------------------

class TestTradeFloorBootstrap:
    def test_empty_upstream_does_not_synthesize(self, clean_root):
        """TradeFloor refuses to synthesize from nothing."""
        result = bootstrap_tradefloor(clean_root)
        assert result["can_synthesize"] is False
        assert result["synthesized"] is False
        assert len(result["upstream_lanes"]) < 2

    def test_single_lane_insufficient(self, clean_root):
        """One upstream lane is not enough for TradeFloor."""
        store_packet(clean_root, make_packet(
            "research_packet", "hermes", "NQ research", confidence=0.5))
        result = bootstrap_tradefloor(clean_root)
        assert result["can_synthesize"] is False
        assert len(result["upstream_lanes"]) == 1

    def test_two_lanes_allows_synthesis(self, clean_root):
        """Two upstream lanes is enough for TradeFloor to synthesize."""
        store_packet(clean_root, make_packet(
            "research_packet", "hermes", "NQ bullish research", confidence=0.5))
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bullish forecast",
            confidence=0.5, notes="direction=bullish"))
        result = bootstrap_tradefloor(clean_root)
        assert result["can_synthesize"] is True
        assert result["synthesized"] is True
        assert result["tier"] is not None

    def test_synthesize_after_full_bootstrap(self, clean_root):
        """After Hermes+Fish bootstrap, TradeFloor can synthesize."""
        bootstrap_hermes(clean_root)
        bootstrap_fish(clean_root)

        result = bootstrap_tradefloor(clean_root)
        assert result["can_synthesize"] is True
        assert len(result["upstream_lanes"]) >= 2


# ---------------------------------------------------------------------------
# Bootstrap all (dependency order)
# ---------------------------------------------------------------------------

class TestBootstrapAll:
    def test_bootstrap_all_produces_real_packets(self, clean_root):
        """bootstrap_all runs lanes in order and produces packets."""
        results = bootstrap_all(clean_root)

        assert results["hermes"]["emitted"] > 0
        assert results["fish"]["scenarios_emitted"] > 0
        assert results["atlas"]["candidates_generated"] > 0
        assert "tradefloor" in results

    def test_bootstrap_all_idempotent(self, clean_root):
        """Repeat bootstrap_all does not duplicate."""
        r1 = bootstrap_all(clean_root)
        r2 = bootstrap_all(clean_root)

        # Second run should recognize everything as already bootstrapped
        assert r2["hermes"]["emitted"] == 0
        assert r2["fish"].get("already_bootstrapped") or r2["fish"]["scenarios_emitted"] == 0
        assert r2["atlas"].get("already_bootstrapped") or r2["atlas"]["candidates_generated"] == 0


# ---------------------------------------------------------------------------
# Bootstrap status reporting
# ---------------------------------------------------------------------------

class TestBootstrapStatus:
    def test_empty_state_is_not_started(self, clean_root):
        """Lane with no packets and no bootstrap record is not_started."""
        status = get_lane_bootstrap_status(clean_root, "hermes")
        assert status == "not_started"

    def test_after_bootstrap_is_active(self, clean_root):
        """After bootstrap, lane with recent packets is active."""
        bootstrap_hermes(clean_root)
        status = get_lane_bootstrap_status(clean_root, "hermes")
        assert status == "active"

    def test_all_status_returns_all_lanes(self, clean_root):
        """get_all_bootstrap_status returns status for all quant lanes."""
        status = get_all_bootstrap_status(clean_root)
        assert "hermes" in status
        assert "fish" in status
        assert "atlas" in status
        assert "tradefloor" in status

    def test_status_tracks_bootstrap_record(self, clean_root):
        """Bootstrap state file records when lanes were bootstrapped."""
        bootstrap_fish(clean_root)
        state = _load_bootstrap_state(clean_root)
        assert "fish" in state
        assert "bootstrapped_at" in state["fish"]
        assert state["fish"]["packets_emitted"] > 0


# ---------------------------------------------------------------------------
# Integration: bootstrap to normal cycle transition
# ---------------------------------------------------------------------------

class TestBootstrapToCycleTransition:
    def test_hermes_bootstrap_then_cycle_deduplicates(self, clean_root):
        """After bootstrap, normal watchlist batch deduplicates cleanly."""
        from workspace.quant.hermes.research_lane import run_watchlist_batch

        r_boot = bootstrap_hermes(clean_root)
        assert r_boot["emitted"] > 0

        # Normal cycle run — should dedup everything
        packets, info = run_watchlist_batch(clean_root)
        assert info["deduped"] >= r_boot["emitted"]
        assert info["emitted"] == 0

    def test_fish_bootstrap_then_cycle_adds_to_history(self, clean_root):
        """After bootstrap, normal Fish cycle can add scenarios on top."""
        from workspace.quant.fish.scenario_lane import emit_scenario, get_scenario_history

        bootstrap_fish(clean_root)
        before = len(get_scenario_history(clean_root))

        emit_scenario(clean_root, "NQ post-FOMC volatility expansion",
                      symbol_scope="NQ", confidence=0.45)
        after = len(get_scenario_history(clean_root))
        assert after == before + 1
