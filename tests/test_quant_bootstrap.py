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


# ---------------------------------------------------------------------------
# Config-driven cycle runtime (not hardcoded stubs)
# ---------------------------------------------------------------------------

class TestCycleRuntimeInputs:
    """Prove normal Lane B cycle uses config-driven inputs, not hardcoded stubs."""

    def test_atlas_cycle_input_from_config(self, clean_root):
        """Atlas cycle input thesis comes from atlas_sources.json, not hardcoded."""
        from workspace.quant.run_lane_b_cycle import _build_atlas_cycle_input

        # Needs Hermes evidence (config has require_hermes_evidence=false for tests)
        result = _build_atlas_cycle_input(clean_root)
        assert len(result) > 0, "Atlas should produce input from config"

        config_path = clean_root / "workspace" / "quant" / "shared" / "config" / "atlas_sources.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config_theses = {t["thesis"] for t in config["seed_themes"]}

        thesis = result[0]["thesis"]
        assert thesis in config_theses, f"Thesis '{thesis}' not in config themes"

    def test_atlas_cycle_input_links_hermes(self, clean_root):
        """Atlas cycle input has evidence_refs to Hermes when available."""
        from workspace.quant.run_lane_b_cycle import _build_atlas_cycle_input

        # Bootstrap Hermes first
        bootstrap_hermes(clean_root)

        # Now update atlas config to require hermes evidence
        config_path = clean_root / "workspace" / "quant" / "shared" / "config" / "atlas_sources.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["require_hermes_evidence"] = True
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        result = _build_atlas_cycle_input(clean_root)
        assert len(result) > 0
        refs = result[0].get("evidence_refs") or []
        assert len(refs) > 0, "Should link Hermes evidence"
        assert all(r.startswith("hermes-") for r in refs)

    def test_atlas_cycle_input_skips_without_hermes_when_required(self, clean_root):
        """Atlas returns [] when hermes evidence is required but absent."""
        from workspace.quant.run_lane_b_cycle import _build_atlas_cycle_input

        config_path = clean_root / "workspace" / "quant" / "shared" / "config" / "atlas_sources.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["require_hermes_evidence"] = True
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        result = _build_atlas_cycle_input(clean_root)
        assert result == [], "No Hermes evidence → no Atlas input"

    def test_atlas_cycle_input_empty_without_config(self, clean_root):
        """Atlas returns [] when atlas_sources.json is missing."""
        from workspace.quant.run_lane_b_cycle import _build_atlas_cycle_input
        (clean_root / "workspace" / "quant" / "shared" / "config" / "atlas_sources.json").unlink()
        assert _build_atlas_cycle_input(clean_root) == []

    def test_fish_cycle_input_from_config(self, clean_root):
        """Fish cycle input thesis comes from fish_bootstrap.json, not hardcoded."""
        from workspace.quant.run_lane_b_cycle import _build_fish_cycle_input

        result = _build_fish_cycle_input(clean_root)
        assert len(result) > 0, "Fish should produce input from config"

        config_path = clean_root / "workspace" / "quant" / "shared" / "config" / "fish_bootstrap.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config_theses = {s["thesis"] for s in config["seed_scenarios"]}

        # Strip any [regime: ...] suffix
        thesis = result[0]["thesis"].split(" [regime:")[0]
        assert thesis in config_theses, f"Thesis '{thesis}' not in config scenarios"

    def test_fish_cycle_input_enriched_with_regime(self, clean_root):
        """Fish cycle input incorporates current regime context when available."""
        from workspace.quant.run_lane_b_cycle import _build_fish_cycle_input
        from workspace.quant.fish.scenario_lane import emit_regime

        emit_regime(clean_root, "NQ trending bull", regime_label="trending_bull")

        result = _build_fish_cycle_input(clean_root)
        assert len(result) > 0
        thesis = result[0]["thesis"]
        assert "[regime: trending_bull]" in thesis

    def test_fish_cycle_input_empty_without_config(self, clean_root):
        """Fish returns [] when fish_bootstrap.json is missing."""
        from workspace.quant.run_lane_b_cycle import _build_fish_cycle_input
        (clean_root / "workspace" / "quant" / "shared" / "config" / "fish_bootstrap.json").unlink()
        assert _build_fish_cycle_input(clean_root) == []

    def test_full_cycle_produces_config_driven_packets(self, clean_root):
        """Full run_cycle produces Atlas/Fish packets from config sources."""
        from workspace.quant.run_lane_b_cycle import run_cycle

        summary = run_cycle(clean_root, verbose=False)

        # No errors
        assert summary["errors"] == [], f"Cycle errors: {summary['errors']}"

        # Atlas should have generated (or been bounded/deduped)
        # Fish should have emitted scenarios
        # Brief should have been produced
        assert summary["brief"] is True

        # Check that Atlas candidates on disk come from config themes
        config_path = clean_root / "workspace" / "quant" / "shared" / "config" / "atlas_sources.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config_theses = {t["thesis"] for t in config["seed_themes"]}

        atlas_pkts = list_lane_packets(clean_root, "atlas", "candidate_packet")
        for pkt in atlas_pkts:
            # Strip enrichment annotations: [adapted: ...], [mkt: ...], etc.
            import re
            base = re.sub(r"\s*\[(?:adapted|mkt|regime):.*?\]", "", pkt.thesis)
            assert base in config_theses, f"Atlas thesis not from config: {pkt.thesis[:60]}"

    def test_cycle_atlas_fish_bounded(self, clean_root):
        """Cycle produces at most 1 Atlas candidate and 1 Fish scenario per run."""
        from workspace.quant.run_lane_b_cycle import run_cycle

        summary = run_cycle(clean_root, verbose=False)

        # Atlas: at most governor batch_size (3 in fixture) but builder sends 1
        assert summary["atlas"]["generated"] <= 1

        # Fish: at most governor batch_size but builder sends 1
        assert summary["fish"]["emitted"] <= 1

    def test_cycle_dedup_safe_on_repeat(self, clean_root):
        """Running cycle twice does not create duplicate Hermes research packets."""
        from workspace.quant.run_lane_b_cycle import run_cycle

        s1 = run_cycle(clean_root, verbose=False)
        hermes_after_1 = len(list_lane_packets(clean_root, "hermes", "research_packet"))

        s2 = run_cycle(clean_root, verbose=False)
        hermes_after_2 = len(list_lane_packets(clean_root, "hermes", "research_packet"))

        # Second run should dedup Hermes (same watchlist sources within 24h)
        assert s2["hermes"]["deduped"] >= 0
        assert hermes_after_2 == hermes_after_1, (
            f"Hermes duplicated: {hermes_after_1} -> {hermes_after_2}"
        )

    def test_tradefloor_changes_with_upstream(self, clean_root):
        """TradeFloor synthesis output reflects actual upstream lane content."""
        from workspace.quant.tradefloor.synthesis_lane import synthesize

        # Seed with bullish Hermes + Fish
        store_packet(clean_root, make_packet(
            "research_packet", "hermes", "NQ bullish momentum detected",
            confidence=0.6))
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bullish upside expected",
            confidence=0.6, notes="direction=bullish"))

        tf1 = synthesize(clean_root)
        text1 = tf1.confidence_weighted_synthesis or ""

        # Change Fish to bearish
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bearish downside risk",
            confidence=0.7, notes="direction=bearish"))

        tf2 = synthesize(clean_root, override_reason="test")
        text2 = tf2.confidence_weighted_synthesis or ""

        # Synthesis text must differ when upstream changes
        assert text1 != text2, "TradeFloor should change when Fish changes direction"


# ---------------------------------------------------------------------------
# Market context ingestion seam
# ---------------------------------------------------------------------------

class TestMarketContext:
    """Prove the market context reader produces structured provenance-tagged snapshots."""

    def _write_test_csv(self, root, rows):
        """Write a test NQ_daily.csv with given rows."""
        data_dir = root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        lines = ["open,high,low,close,volume,vix"]
        for r in rows:
            lines.append(",".join(str(v) for v in r))
        (data_dir / "NQ_daily.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_test_metadata(self, root, updated_at="2026-03-19T05:00:00+00:00"):
        data_dir = root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "last_updated": updated_at,
            "sources": {"nq_daily": {"source": "yfinance", "symbol": "NQ=F", "bars": 5}},
        }
        (data_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    def test_no_data_returns_none(self, clean_root):
        """No CSV file → returns None, does not crash."""
        from workspace.quant.shared.market_context import read_market_snapshot
        assert read_market_snapshot(clean_root) is None

    def test_reads_real_snapshot(self, clean_root):
        """With CSV data, produces a structured snapshot."""
        from workspace.quant.shared.market_context import read_market_snapshot
        self._write_test_csv(clean_root, [
            (24000, 24200, 23900, 24100, 500000, 20.0),
            (24100, 24300, 24000, 24200, 510000, 19.5),
            (24200, 24400, 24100, 24300, 520000, 21.0),
            (24300, 24500, 24200, 24400, 530000, 22.0),
            (24400, 24600, 24300, 24500, 540000, 23.5),
        ])
        self._write_test_metadata(clean_root)
        snap = read_market_snapshot(clean_root)
        assert snap is not None
        assert snap["symbol"] == "NQ"
        assert snap["last_close"] == 24500.0
        assert snap["prev_close"] == 24400.0
        assert snap["vix"] == 23.5
        assert snap["trend_5d"] == "up"  # 24100 → 24500 is up
        assert snap["data_source"].startswith("yfinance")
        assert snap["snapshot_at"]  # ISO timestamp present

    def test_provenance_fields(self, clean_root):
        """Snapshot includes provenance: source, file path, update time."""
        from workspace.quant.shared.market_context import read_market_snapshot
        self._write_test_csv(clean_root, [
            (24000, 24200, 23900, 24100, 500000, 20.0),
            (24100, 24300, 24000, 24200, 510000, 19.5),
        ])
        self._write_test_metadata(clean_root, "2026-03-19T05:00:00+00:00")
        snap = read_market_snapshot(clean_root)
        assert snap is not None
        assert "data_source" in snap
        assert "data_file" in snap
        assert "data_updated_at" in snap
        assert "data_freshness_hours" in snap
        assert snap["data_freshness_hours"] is not None

    def test_trend_detection(self, clean_root):
        """Trend detection: up, down, flat."""
        from workspace.quant.shared.market_context import read_market_snapshot

        # Up trend
        self._write_test_csv(clean_root, [
            (24000, 24200, 23900, 24100, 500000, 20.0),
            (24100, 24500, 24000, 24400, 510000, 19.5),
        ])
        assert read_market_snapshot(clean_root)["trend_5d"] == "up"

        # Down trend
        self._write_test_csv(clean_root, [
            (24400, 24500, 24000, 24400, 500000, 20.0),
            (24300, 24400, 23900, 24000, 510000, 19.5),
        ])
        assert read_market_snapshot(clean_root)["trend_5d"] == "down"

        # Flat
        self._write_test_csv(clean_root, [
            (24000, 24200, 23900, 24100, 500000, 20.0),
            (24100, 24200, 24000, 24100, 510000, 19.5),
        ])
        assert read_market_snapshot(clean_root)["trend_5d"] == "flat"

    def test_format_market_read(self, clean_root):
        """format_market_read produces phone-scannable string."""
        from workspace.quant.shared.market_context import read_market_snapshot, format_market_read
        self._write_test_csv(clean_root, [
            (24000, 24200, 23900, 24100, 500000, 20.0),
            (24100, 24300, 24000, 24250, 510000, 22.5),
        ])
        self._write_test_metadata(clean_root)
        snap = read_market_snapshot(clean_root)
        text = format_market_read(snap)
        assert "NQ last" in text
        assert "VIX" in text
        assert "Source:" in text

    def test_format_market_read_none(self):
        from workspace.quant.shared.market_context import format_market_read
        text = format_market_read(None)
        assert "No market data" in text

    def test_atlas_enriched_with_market(self, clean_root):
        """Atlas builder enriches thesis with market context when available."""
        from workspace.quant.run_lane_b_cycle import _build_atlas_cycle_input
        market = {"vix": 25.0, "trend_5d": "down", "daily_change_pct": -1.2}
        result = _build_atlas_cycle_input(clean_root, market=market)
        assert len(result) > 0
        assert "[mkt:" in result[0]["thesis"]
        assert "VIX=25" in result[0]["thesis"]
        assert "5d-trend=down" in result[0]["thesis"]

    def test_atlas_no_market_no_enrichment(self, clean_root):
        """Atlas builder produces plain config thesis without market context."""
        from workspace.quant.run_lane_b_cycle import _build_atlas_cycle_input
        result = _build_atlas_cycle_input(clean_root, market=None)
        assert len(result) > 0
        assert "[mkt:" not in result[0]["thesis"]

    def test_fish_enriched_with_market(self, clean_root):
        """Fish builder enriches thesis with market context when available."""
        from workspace.quant.run_lane_b_cycle import _build_fish_cycle_input
        market = {"last_close": 24500.0, "vix": 22.0, "range_5d_pct": 3.5}
        result = _build_fish_cycle_input(clean_root, market=market)
        assert len(result) > 0
        assert "[mkt:" in result[0]["thesis"]
        assert "NQ=24500" in result[0]["thesis"]
        assert "VIX=22" in result[0]["thesis"]

    def test_high_vix_reduces_atlas_confidence(self, clean_root):
        """High VIX reduces Atlas candidate confidence."""
        from workspace.quant.run_lane_b_cycle import _build_atlas_cycle_input
        low_vix = _build_atlas_cycle_input(clean_root, market={"vix": 12.0})[0]["confidence"]
        high_vix = _build_atlas_cycle_input(clean_root, market={"vix": 35.0})[0]["confidence"]
        assert high_vix < low_vix, f"High VIX ({high_vix}) should < low VIX ({low_vix})"

    def test_hermes_ingests_market_as_dataset(self, clean_root):
        """Hermes emits a dataset_packet from market context with provenance."""
        from workspace.quant.hermes.research_lane import emit_dataset
        market = {
            "last_close": 24500.0,
            "daily_change_pct": -0.5,
            "vix": 22.0,
            "trend_5d": "down",
            "range_5d_pct": 3.2,
            "data_updated_at": "2026-03-19T05:00:00+00:00",
        }
        ds_source = f"cron-ohlcv-{market['data_updated_at'][:10]}"
        pkt = emit_dataset(
            clean_root,
            thesis=f"NQ daily: close={market['last_close']:.0f} VIX={market['vix']:.1f}",
            dataset_name="NQ_daily_ohlcv_vix",
            source=ds_source,
            source_type="api",
            symbol_scope="NQ",
            confidence=0.8,
        )
        assert pkt is not None
        assert "source=cron-ohlcv-2026-03-19" in pkt.notes
        assert "dataset=NQ_daily_ohlcv_vix" in pkt.notes
        assert pkt.packet_type == "dataset_packet"
        assert pkt.lane == "hermes"

    def test_market_dataset_dedup_via_research_source(self, clean_root):
        """If a research_packet already exists for the same source, dataset deduplicates."""
        from workspace.quant.hermes.research_lane import emit_research, emit_dataset
        # Create a research_packet with matching source key
        emit_research(clean_root, thesis="test", source="cron-ohlcv-2026-03-19",
                      source_type="api", symbol_scope="NQ")
        # Now dataset with same source key should dedup
        pkt = emit_dataset(clean_root, thesis="same source",
                           dataset_name="test", source="cron-ohlcv-2026-03-19")
        assert pkt is None, "Should dedup when research_packet has same source"
