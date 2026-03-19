#!/usr/bin/env python3
"""Tests proving Fish forecasts → outcomes → recalibration.

Acceptance criteria:
  1. Fish confidence changes based on realized outcomes
  2. Calibration state persists across calls
  3. Risk map becomes meaningful input for later synthesis
  4. Multi-step forecast → outcome → recalibration chains work
  5. Track record degrades after repeated wrong forecasts
  6. Track record improves after repeated correct forecasts
  7. Pending forecast tracking works
  8. Scenario history is queryable
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet, validate_packet
from workspace.quant.shared.packet_store import store_packet, list_lane_packets
from workspace.quant.fish.scenario_lane import (
    emit_scenario, emit_forecast, emit_regime, emit_risk_map,
    calibrate, run_scenario_batch, emit_health_summary,
    build_calibration_state, get_scenario_history,
    get_pending_forecasts, get_active_risk_zones,
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


# ---- Calibration state ----

class TestCalibrationState:
    def test_empty_state(self, clean_root):
        state = build_calibration_state(clean_root)
        assert state["total_calibrations"] == 0
        assert state["direction_hits"] == 0
        assert state["direction_misses"] == 0
        assert state["direction_hit_rate"] is None
        assert state["recent_scores"] == []
        assert state["streak"] == 0
        assert state["trend"] == "insufficient_data"

    def test_single_correct_calibration(self, clean_root):
        f = emit_forecast(clean_root, "NQ bullish", confidence=0.5,
                          forecast_value=18000.0, forecast_direction="bullish")
        calibrate(clean_root, f, 18050.0, "bullish")

        state = build_calibration_state(clean_root)
        assert state["total_calibrations"] == 1
        assert state["direction_hits"] == 1
        assert state["direction_misses"] == 0
        assert state["direction_hit_rate"] == 1.0
        assert len(state["recent_scores"]) == 1
        assert state["recent_scores"][0] > 0.8  # Correct direction + close value
        assert state["streak"] == 1

    def test_single_wrong_calibration(self, clean_root):
        f = emit_forecast(clean_root, "NQ bearish", confidence=0.6,
                          forecast_value=17500.0, forecast_direction="bearish")
        calibrate(clean_root, f, 18200.0, "bullish")

        state = build_calibration_state(clean_root)
        assert state["direction_hits"] == 0
        assert state["direction_misses"] == 1
        assert state["direction_hit_rate"] == 0.0
        assert state["streak"] == -1

    def test_state_accumulates(self, clean_root):
        for i in range(3):
            f = emit_forecast(clean_root, f"Forecast {i}", confidence=0.5,
                              forecast_value=18000.0, forecast_direction="bullish")
            calibrate(clean_root, f, 18050.0, "bullish")

        state = build_calibration_state(clean_root)
        assert state["total_calibrations"] == 3
        assert state["direction_hits"] == 3
        assert state["streak"] == 3
        assert state["direction_hit_rate"] == 1.0

    def test_streak_tracks_consecutive_misses(self, clean_root):
        # 2 hits then 3 misses
        for i in range(2):
            f = emit_forecast(clean_root, f"Hit {i}", confidence=0.5,
                              forecast_direction="bullish")
            calibrate(clean_root, f, 18000.0, "bullish")
        for i in range(3):
            f = emit_forecast(clean_root, f"Miss {i}", confidence=0.5,
                              forecast_direction="bullish")
            calibrate(clean_root, f, 17500.0, "bearish")

        state = build_calibration_state(clean_root)
        assert state["streak"] == -3
        assert state["direction_hits"] == 2
        assert state["direction_misses"] == 3

    def test_track_record_confidence_penalizes_cold_streak(self, clean_root):
        # Build a cold streak
        for i in range(4):
            f = emit_forecast(clean_root, f"Wrong {i}", confidence=0.5,
                              forecast_value=18000.0, forecast_direction="bullish")
            calibrate(clean_root, f, 17000.0, "bearish")

        state = build_calibration_state(clean_root)
        assert state["track_record_confidence"] < 0.3  # Should be low after 4 misses
        assert state["streak"] == -4

    def test_track_record_confidence_rewards_hot_streak(self, clean_root):
        for i in range(4):
            f = emit_forecast(clean_root, f"Right {i}", confidence=0.5,
                              forecast_value=18000.0, forecast_direction="bullish")
            calibrate(clean_root, f, 18020.0, "bullish")

        state = build_calibration_state(clean_root)
        assert state["track_record_confidence"] > 0.7  # Should be high after 4 hits
        assert state["streak"] == 4


# ---- Confidence adjustment ----

class TestConfidenceAdjustment:
    def test_correct_forecast_raises_confidence(self, clean_root):
        f = emit_forecast(clean_root, "NQ bullish", confidence=0.5,
                          forecast_value=18000.0, forecast_direction="bullish")
        cal, result = calibrate(clean_root, f, 18020.0, "bullish")
        assert result["adjusted_confidence"] > 0.5
        assert result["direction_correct"] is True
        assert result["calibration_score"] > 0.9

    def test_wrong_forecast_lowers_confidence(self, clean_root):
        f = emit_forecast(clean_root, "NQ bearish", confidence=0.6,
                          forecast_value=17500.0, forecast_direction="bearish")
        cal, result = calibrate(clean_root, f, 18500.0, "bullish")
        assert result["adjusted_confidence"] < 0.6
        assert result["direction_correct"] is False

    def test_repeated_wrong_forecasts_compound_reduction(self, clean_root):
        """Confidence should keep dropping with repeated failures."""
        confidences = []
        for i in range(5):
            conf = confidences[-1] if confidences else 0.6
            f = emit_forecast(clean_root, f"Wrong {i}", confidence=conf,
                              forecast_value=18000.0, forecast_direction="bullish")
            _, result = calibrate(clean_root, f, 17000.0, "bearish")
            confidences.append(result["adjusted_confidence"])

        # Each confidence should be lower than the previous
        for j in range(1, len(confidences)):
            assert confidences[j] < confidences[j - 1], (
                f"Confidence should decrease: {confidences}"
            )
        # After 5 wrong, confidence should be well below starting point
        assert confidences[-1] < 0.3

    def test_repeated_correct_forecasts_compound_increase(self, clean_root):
        """Confidence should keep rising with repeated successes."""
        confidences = []
        for i in range(5):
            conf = confidences[-1] if confidences else 0.4
            f = emit_forecast(clean_root, f"Right {i}", confidence=conf,
                              forecast_value=18000.0, forecast_direction="bullish")
            _, result = calibrate(clean_root, f, 18010.0, "bullish")
            confidences.append(result["adjusted_confidence"])

        # Each confidence should be higher than the previous
        for j in range(1, len(confidences)):
            assert confidences[j] > confidences[j - 1], (
                f"Confidence should increase: {confidences}"
            )
        # After 5 correct, confidence should be above starting point
        assert confidences[-1] > 0.6

    def test_recovery_after_cold_streak(self, clean_root):
        """Confidence recovers after switching from wrong to right."""
        # 3 wrong
        conf = 0.5
        for i in range(3):
            f = emit_forecast(clean_root, f"Wrong {i}", confidence=conf,
                              forecast_value=18000.0, forecast_direction="bullish")
            _, result = calibrate(clean_root, f, 17000.0, "bearish")
            conf = result["adjusted_confidence"]
        low_point = conf

        # 3 correct
        for i in range(3):
            f = emit_forecast(clean_root, f"Right {i}", confidence=conf,
                              forecast_value=18000.0, forecast_direction="bullish")
            _, result = calibrate(clean_root, f, 18010.0, "bullish")
            conf = result["adjusted_confidence"]

        assert conf > low_point, "Confidence should recover after correct forecasts"

    def test_track_record_feeds_into_confidence(self, clean_root):
        """After building a good track record, new forecasts start higher."""
        # Build good track record
        for i in range(5):
            f = emit_forecast(clean_root, f"Good {i}", confidence=0.5,
                              forecast_value=18000.0, forecast_direction="bullish")
            calibrate(clean_root, f, 18020.0, "bullish")

        # New calibration benefits from accumulated trust
        f_new = emit_forecast(clean_root, "New forecast", confidence=0.5,
                              forecast_value=18000.0, forecast_direction="bullish")
        _, result = calibrate(clean_root, f_new, 18010.0, "bullish")
        # Track record confidence should be high, pulling adjusted up
        assert result["track_record_confidence"] > 0.7
        assert result["adjusted_confidence"] > 0.6


# ---- Trend ----

class TestTrend:
    def test_improving_trend(self, clean_root):
        # 2 bad then 2 good
        f1 = emit_forecast(clean_root, "Bad 1", confidence=0.5,
                           forecast_value=18000.0, forecast_direction="bullish")
        calibrate(clean_root, f1, 17000.0, "bearish")
        f2 = emit_forecast(clean_root, "Bad 2", confidence=0.5,
                           forecast_value=18000.0, forecast_direction="bullish")
        calibrate(clean_root, f2, 17000.0, "bearish")
        f3 = emit_forecast(clean_root, "Good 1", confidence=0.5,
                           forecast_value=18000.0, forecast_direction="bullish")
        calibrate(clean_root, f3, 18010.0, "bullish")
        f4 = emit_forecast(clean_root, "Good 2", confidence=0.5,
                           forecast_value=18000.0, forecast_direction="bullish")
        _, result = calibrate(clean_root, f4, 18010.0, "bullish")
        assert result["trend"] == "improving"

    def test_degrading_trend(self, clean_root):
        # 2 good then 2 bad
        f1 = emit_forecast(clean_root, "Good 1", confidence=0.5,
                           forecast_value=18000.0, forecast_direction="bullish")
        calibrate(clean_root, f1, 18010.0, "bullish")
        f2 = emit_forecast(clean_root, "Good 2", confidence=0.5,
                           forecast_value=18000.0, forecast_direction="bullish")
        calibrate(clean_root, f2, 18010.0, "bullish")
        f3 = emit_forecast(clean_root, "Bad 1", confidence=0.5,
                           forecast_value=18000.0, forecast_direction="bullish")
        calibrate(clean_root, f3, 17000.0, "bearish")
        f4 = emit_forecast(clean_root, "Bad 2", confidence=0.5,
                           forecast_value=18000.0, forecast_direction="bullish")
        _, result = calibrate(clean_root, f4, 17000.0, "bearish")
        assert result["trend"] == "degrading"


# ---- Scenario history ----

class TestScenarioHistory:
    def test_empty_history(self, clean_root):
        history = get_scenario_history(clean_root)
        assert history == []

    def test_history_accumulates(self, clean_root):
        emit_scenario(clean_root, "Scenario A", symbol_scope="NQ")
        emit_scenario(clean_root, "Scenario B", symbol_scope="NQ")
        emit_scenario(clean_root, "Scenario C", symbol_scope="ES")

        history = get_scenario_history(clean_root)
        assert len(history) == 3

    def test_history_filter_by_symbol(self, clean_root):
        emit_scenario(clean_root, "NQ scenario", symbol_scope="NQ")
        emit_scenario(clean_root, "ES scenario", symbol_scope="ES")

        nq = get_scenario_history(clean_root, symbol_scope="NQ")
        assert len(nq) == 1
        assert nq[0]["symbol_scope"] == "NQ"

    def test_history_respects_limit(self, clean_root):
        for i in range(10):
            emit_scenario(clean_root, f"Scenario {i}")

        history = get_scenario_history(clean_root, limit=3)
        assert len(history) == 3

    def test_history_entries_have_expected_fields(self, clean_root):
        emit_scenario(clean_root, "Test scenario", symbol_scope="NQ",
                      timeframe_scope="1D", confidence=0.7)
        history = get_scenario_history(clean_root)
        entry = history[0]
        assert "packet_id" in entry
        assert entry["thesis"] == "Test scenario"
        assert entry["symbol_scope"] == "NQ"
        assert entry["confidence"] == 0.7


# ---- Pending forecasts ----

class TestPendingForecasts:
    def test_no_forecasts_no_pending(self, clean_root):
        assert get_pending_forecasts(clean_root) == []

    def test_uncalibrated_forecast_is_pending(self, clean_root):
        emit_forecast(clean_root, "Pending forecast", forecast_direction="bullish")
        pending = get_pending_forecasts(clean_root)
        assert len(pending) == 1

    def test_calibrated_forecast_not_pending(self, clean_root):
        f = emit_forecast(clean_root, "Will calibrate", forecast_direction="bullish",
                          forecast_value=18000.0)
        calibrate(clean_root, f, 18050.0, "bullish")
        pending = get_pending_forecasts(clean_root)
        assert len(pending) == 0

    def test_mix_of_pending_and_calibrated(self, clean_root):
        f1 = emit_forecast(clean_root, "Calibrated", forecast_direction="bullish",
                           forecast_value=18000.0)
        calibrate(clean_root, f1, 18050.0, "bullish")

        emit_forecast(clean_root, "Still pending 1", forecast_direction="bearish")
        emit_forecast(clean_root, "Still pending 2", forecast_direction="bullish")

        pending = get_pending_forecasts(clean_root)
        assert len(pending) == 2


# ---- Risk map aggregation ----

class TestRiskMapAggregation:
    def test_empty_risk_zones(self, clean_root):
        zones = get_active_risk_zones(clean_root)
        assert zones == {}

    def test_single_risk_map(self, clean_root):
        emit_risk_map(clean_root, "VIX risk",
                      risk_zones={"vix_spike": {"level": "high", "trigger": "VIX > 30"}},
                      confidence=0.7)
        zones = get_active_risk_zones(clean_root)
        assert "vix_spike" in zones
        assert zones["vix_spike"]["level"] == "high"
        assert zones["vix_spike"]["confidence"] == 0.7

    def test_multiple_maps_merge(self, clean_root):
        emit_risk_map(clean_root, "Risk map 1",
                      risk_zones={"vix_spike": {"level": "high", "trigger": "VIX > 30"}})
        emit_risk_map(clean_root, "Risk map 2",
                      risk_zones={"liquidity_gap": {"level": "medium", "trigger": "volume < 50pct"}})

        zones = get_active_risk_zones(clean_root)
        assert "vix_spike" in zones
        assert "liquidity_gap" in zones

    def test_newer_map_overwrites_same_zone(self, clean_root):
        emit_risk_map(clean_root, "Old map",
                      risk_zones={"vix_spike": {"level": "medium", "trigger": "VIX > 25"}},
                      confidence=0.5)
        emit_risk_map(clean_root, "New map",
                      risk_zones={"vix_spike": {"level": "high", "trigger": "VIX > 30"}},
                      confidence=0.8)

        zones = get_active_risk_zones(clean_root)
        assert zones["vix_spike"]["level"] == "high"
        assert zones["vix_spike"]["confidence"] == 0.8

    def test_limit_respected(self, clean_root):
        # Emit 3 maps, query with limit=1 → only latest
        emit_risk_map(clean_root, "Map 1",
                      risk_zones={"zone_a": {"level": "low", "trigger": "test"}})
        emit_risk_map(clean_root, "Map 2",
                      risk_zones={"zone_b": {"level": "medium", "trigger": "test"}})
        emit_risk_map(clean_root, "Map 3",
                      risk_zones={"zone_c": {"level": "high", "trigger": "test"}})

        zones = get_active_risk_zones(clean_root, limit=1)
        assert "zone_c" in zones
        assert "zone_a" not in zones

    def test_risk_map_without_zones_skipped(self, clean_root):
        emit_risk_map(clean_root, "No zones map", risk_zones=None)
        zones = get_active_risk_zones(clean_root)
        assert zones == {}


# ---- Health summary ----

class TestHealthSummaryWithCalibration:
    def test_health_includes_calibration_context(self, clean_root):
        # Build some calibration history
        for i in range(3):
            f = emit_forecast(clean_root, f"F{i}", confidence=0.5,
                              forecast_value=18000.0, forecast_direction="bullish")
            calibrate(clean_root, f, 18010.0, "bullish")

        # Leave one pending
        emit_forecast(clean_root, "Pending", forecast_direction="bearish")

        h = emit_health_summary(
            clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 7,
            scenarios_emitted=0, forecasts_emitted=4, calibrations_done=3,
        )
        assert validate_packet(h) == []
        assert "track_record" in (h.notable_events or "")
        assert "tr_confidence" in h.thesis
        assert "pending" in (h.notable_events or "").lower()

    def test_health_with_no_calibrations(self, clean_root):
        h = emit_health_summary(
            clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 2,
            scenarios_emitted=2,
        )
        assert validate_packet(h) == []
        assert h.governor_action_taken in ("push", "hold", "backoff", "pause")


# ---- End-to-end multi-step recalibration ----

class TestEndToEndRecalibration:
    def test_full_forecast_calibration_chain(self, clean_root):
        """Full chain: forecast → outcome → recalibrate → forecast → outcome → verify."""
        # Step 1: First forecast (correct)
        f1 = emit_forecast(clean_root, "NQ bullish week", confidence=0.5,
                           forecast_value=18000.0, forecast_direction="bullish")
        cal1, r1 = calibrate(clean_root, f1, 18050.0, "bullish")
        assert r1["direction_correct"] is True
        assert r1["adjusted_confidence"] > 0.5

        # Step 2: Second forecast using adjusted confidence (wrong)
        f2 = emit_forecast(clean_root, "NQ still bullish", confidence=r1["adjusted_confidence"],
                           forecast_value=18200.0, forecast_direction="bullish")
        cal2, r2 = calibrate(clean_root, f2, 17800.0, "bearish")
        assert r2["direction_correct"] is False
        assert r2["adjusted_confidence"] < r1["adjusted_confidence"]

        # Step 3: Third forecast (correct again)
        f3 = emit_forecast(clean_root, "NQ recovery", confidence=r2["adjusted_confidence"],
                           forecast_value=18000.0, forecast_direction="bullish")
        cal3, r3 = calibrate(clean_root, f3, 18020.0, "bullish")
        assert r3["direction_correct"] is True

        # Verify cumulative state
        state = build_calibration_state(clean_root)
        assert state["total_calibrations"] == 3
        assert state["direction_hits"] == 2
        assert state["direction_misses"] == 1
        assert state["direction_hit_rate"] == pytest.approx(2 / 3, abs=0.01)
        assert state["streak"] == 1  # Last result was correct

    def test_forecast_to_risk_map_to_synthesis(self, clean_root):
        """Forecast + calibration feeds risk map, risk map is queryable."""
        # Forecast wrong → high risk zone
        f = emit_forecast(clean_root, "NQ breakout expected", confidence=0.6,
                          forecast_value=18500.0, forecast_direction="bullish")
        _, result = calibrate(clean_root, f, 17800.0, "bearish")

        # Emit risk map reflecting the miss
        emit_risk_map(clean_root, "Elevated directional risk after miss",
                      risk_zones={
                          "directional_risk": {
                              "level": "high",
                              "trigger": f"Last forecast wrong (error={result['value_error']:.0f})",
                          },
                          "volatility_risk": {
                              "level": "medium",
                              "trigger": "Large realized vs forecast gap",
                          },
                      },
                      confidence=0.7)

        # Verify risk zones are queryable
        zones = get_active_risk_zones(clean_root)
        assert "directional_risk" in zones
        assert zones["directional_risk"]["level"] == "high"
        assert "volatility_risk" in zones

    def test_calibration_state_persists_across_calls(self, clean_root):
        """State builds up correctly across separate function calls."""
        # First batch
        for i in range(3):
            f = emit_forecast(clean_root, f"Batch1 {i}", confidence=0.5,
                              forecast_direction="bullish")
            calibrate(clean_root, f, 18000.0, "bullish")

        state1 = build_calibration_state(clean_root)
        assert state1["total_calibrations"] == 3

        # Second batch (different session/call)
        for i in range(2):
            f = emit_forecast(clean_root, f"Batch2 {i}", confidence=0.5,
                              forecast_direction="bearish")
            calibrate(clean_root, f, 18000.0, "bullish")  # Wrong

        state2 = build_calibration_state(clean_root)
        assert state2["total_calibrations"] == 5
        assert state2["direction_hits"] == 3
        assert state2["direction_misses"] == 2
        assert state2["streak"] == -2

    def test_no_regressions_existing_calibrate_api(self, clean_root):
        """Existing calibrate() API still works as before."""
        forecast = emit_forecast(
            clean_root, "NQ bullish", confidence=0.6,
            forecast_value=18400.0, forecast_direction="bullish",
        )
        cal_pkt, result = calibrate(clean_root, forecast,
                                    realized_value=18350.0,
                                    realized_direction="bullish")
        # Core API unchanged
        assert validate_packet(cal_pkt) == []
        assert result["direction_correct"] is True
        assert result["value_error"] == 50.0
        assert result["calibration_score"] > 0
        assert result["adjusted_confidence"] != forecast.confidence
        # New fields present
        assert "track_record_confidence" in result
        assert "direction_hit_rate" in result
        assert "streak" in result
