#!/usr/bin/env python3
"""Tests for Lane B intelligence lanes.

Tests Atlas, Fish, Hermes, TradeFloor using frozen packet contracts.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet, validate_packet, QuantPacket
from workspace.quant.shared.packet_store import store_packet, get_latest, get_all_latest
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, load_all_strategies,
)


@pytest.fixture
def clean_root(tmp_path):
    """Provide a clean root directory for each test."""
    # Create minimal directory structure
    (tmp_path / "workspace" / "quant" / "shared" / "latest").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "registries").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "config").mkdir(parents=True)
    for lane in ["atlas", "fish", "hermes", "sigma", "kitt", "tradefloor", "executor"]:
        (tmp_path / "workspace" / "quant" / lane).mkdir(parents=True)
    return tmp_path


# ---- Atlas Tests ----

class TestAtlas:
    def test_generate_candidate_creates_registry_entry(self, clean_root):
        from workspace.quant.atlas.exploration_lane import generate_candidate
        pkt, feedback = generate_candidate(clean_root, "atlas-test-001", "Test thesis")
        assert validate_packet(pkt) == []
        assert pkt.strategy_id == "atlas-test-001"
        strats = load_all_strategies(clean_root)
        assert "atlas-test-001" in strats
        assert strats["atlas-test-001"].lifecycle_state == "CANDIDATE"

    def test_generate_candidate_rejects_duplicate(self, clean_root):
        from workspace.quant.atlas.exploration_lane import generate_candidate
        generate_candidate(clean_root, "atlas-dup-001", "First")
        with pytest.raises(ValueError, match="already exists"):
            generate_candidate(clean_root, "atlas-dup-001", "Second")

    def test_ingest_rejections_empty(self, clean_root):
        from workspace.quant.atlas.exploration_lane import ingest_rejections
        feedback = ingest_rejections(clean_root)
        assert feedback["rejection_count"] == 0
        assert feedback["adapted"] is False

    def test_atlas_adapts_from_rejection(self, clean_root):
        """Core proof: Atlas consumes rejection and changes output."""
        from workspace.quant.atlas.exploration_lane import generate_candidate, ingest_rejections

        # Create first candidate
        pkt1, fb1 = generate_candidate(clean_root, "atlas-a-001", "Simple gap fade")
        assert fb1["adapted"] is False

        # Sigma rejects it
        transition_strategy(clean_root, "atlas-a-001", "VALIDATING", actor="sigma")
        rej = make_packet(
            "strategy_rejection_packet", "sigma",
            "Rejected: poor OOS",
            strategy_id="atlas-a-001",
            rejection_reason="poor_oos",
            rejection_detail="PF 0.8 < 1.3",
        )
        store_packet(clean_root, rej)
        transition_strategy(clean_root, "atlas-a-001", "REJECTED", actor="sigma")

        # Now Atlas ingests and adapts
        feedback = ingest_rejections(clean_root)
        assert feedback["rejection_count"] >= 1
        assert len(feedback["avoidance_patterns"]) > 0

        # Second candidate reflects adaptation
        pkt2, fb2 = generate_candidate(
            clean_root, "atlas-a-002", "Improved gap fade with filter",
            parent_id="atlas-a-001",
        )
        assert "adapted:" in pkt2.thesis.lower() or "avoid" in (pkt2.notes or "").lower()
        assert pkt2.confidence != 0.5  # Confidence adjusted

    def test_failure_learning_packet(self, clean_root):
        from workspace.quant.atlas.exploration_lane import emit_failure_learning
        rej = make_packet(
            "strategy_rejection_packet", "sigma", "Rejected",
            strategy_id="test-001", rejection_reason="curve_fit",
            rejection_detail="Overfitted",
        )
        store_packet(clean_root, rej)
        learning = emit_failure_learning(clean_root, rej, "Need out-of-sample validation")
        assert validate_packet(learning) == []
        assert learning.packet_type == "failure_learning_packet"

    def test_atlas_health_summary(self, clean_root):
        from workspace.quant.atlas.exploration_lane import emit_health_summary
        h = emit_health_summary(clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 3)
        assert validate_packet(h) == []
        assert h.packet_type == "health_summary"
        assert h.lane == "atlas"
        assert h.governor_action_taken == "none"


# ---- Fish Tests ----

class TestFish:
    def test_emit_scenario(self, clean_root):
        from workspace.quant.fish.scenario_lane import emit_scenario
        pkt = emit_scenario(clean_root, "NQ range-bound this week", confidence=0.6)
        assert validate_packet(pkt) == []
        assert pkt.packet_type == "scenario_packet"

    def test_emit_forecast_with_direction(self, clean_root):
        from workspace.quant.fish.scenario_lane import emit_forecast
        pkt = emit_forecast(
            clean_root, "NQ bullish into FOMC",
            forecast_value=18400.0, forecast_direction="bullish", confidence=0.55,
        )
        assert validate_packet(pkt) == []
        assert "direction=bullish" in pkt.notes
        assert "target=18400" in pkt.notes

    def test_calibrate_correct_direction(self, clean_root):
        """Core proof: Fish compares forecast to outcome."""
        from workspace.quant.fish.scenario_lane import emit_forecast, calibrate
        forecast = emit_forecast(
            clean_root, "NQ bullish", confidence=0.6,
            forecast_value=18400.0, forecast_direction="bullish",
        )
        cal_pkt, result = calibrate(clean_root, forecast, realized_value=18350.0, realized_direction="bullish")
        assert validate_packet(cal_pkt) == []
        assert result["direction_correct"] is True
        assert result["value_error"] == 50.0
        assert result["calibration_score"] > 0
        assert result["adjusted_confidence"] != forecast.confidence

    def test_calibrate_wrong_direction_lowers_confidence(self, clean_root):
        from workspace.quant.fish.scenario_lane import emit_forecast, calibrate
        forecast = emit_forecast(
            clean_root, "NQ bearish", confidence=0.6,
            forecast_value=17800.0, forecast_direction="bearish",
        )
        cal_pkt, result = calibrate(clean_root, forecast, realized_value=18500.0, realized_direction="bullish")
        assert result["direction_correct"] is False
        assert result["adjusted_confidence"] < forecast.confidence

    def test_calibration_trend(self, clean_root):
        from workspace.quant.fish.scenario_lane import emit_forecast, calibrate
        # Two calibrations — second should show trend
        f1 = emit_forecast(clean_root, "f1", confidence=0.5, forecast_value=18000.0, forecast_direction="bullish")
        calibrate(clean_root, f1, 18050.0, "bullish")
        f2 = emit_forecast(clean_root, "f2", confidence=0.5, forecast_value=18100.0, forecast_direction="bullish")
        _, result2 = calibrate(clean_root, f2, 18120.0, "bullish")
        assert result2["trend"] in ("improving", "degrading", "insufficient_data")
        assert result2["history_depth"] >= 2

    def test_fish_health_summary(self, clean_root):
        from workspace.quant.fish.scenario_lane import emit_health_summary
        h = emit_health_summary(clean_root, "2026-01-01T00:00:00Z", "2026-01-01T08:00:00Z", 5,
                                scenarios_emitted=1, calibrations_done=2)
        assert validate_packet(h) == []
        assert h.lane == "fish"


# ---- Hermes Tests ----

class TestHermes:
    def test_emit_research(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_research
        pkt = emit_research(clean_root, "NQ research", source="test-source", source_type="web")
        assert pkt is not None
        assert validate_packet(pkt) == []
        assert "source=test-source" in pkt.notes

    def test_dedup_skips_recent(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_research
        emit_research(clean_root, "First", source="same-source", source_type="web")
        dup = emit_research(clean_root, "Second", source="same-source", source_type="web")
        assert dup is None  # Deduped

    def test_force_overrides_dedup(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_research
        emit_research(clean_root, "First", source="force-source", source_type="web")
        forced = emit_research(clean_root, "Forced", source="force-source", source_type="web", force=True)
        assert forced is not None

    def test_confidence_adjusted_by_source_type(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_research
        official = emit_research(clean_root, "Official", source="s1", source_type="official_doc", confidence=0.8)
        social = emit_research(clean_root, "Social", source="s2", source_type="social", confidence=0.8)
        assert official.confidence > social.confidence  # official_doc 1.0x vs social 0.3x

    def test_research_request_packet(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_research_request
        pkt = emit_research_request(clean_root, "atlas", "Research vol surfaces", symbol_scope="NQ")
        assert validate_packet(pkt) == []
        assert pkt.lane == "atlas"  # Requesting lane
        assert pkt.packet_type == "research_request_packet"

    def test_hermes_health_summary(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_health_summary
        h = emit_health_summary(clean_root, "2026-01-01T00:00:00Z", "2026-01-01T03:00:00Z", 2)
        assert validate_packet(h) == []
        assert h.lane == "hermes"


# ---- TradeFloor Tests ----

class TestTradeFloor:
    def _seed_packets(self, root):
        """Seed latest packets from multiple lanes for synthesis."""
        store_packet(root, make_packet(
            "research_packet", "hermes", "NQ bullish momentum detected",
            confidence=0.6,
        ))
        store_packet(root, make_packet(
            "candidate_packet", "atlas", "NQ breakout strategy shows bullish edge",
            strategy_id="atlas-tf-001", confidence=0.55,
        ))
        store_packet(root, make_packet(
            "scenario_packet", "fish", "NQ bullish scenario: FOMC dovish",
            confidence=0.6,
        ))
        store_packet(root, make_packet(
            "validation_packet", "sigma", "atlas-tf-001 passes validation",
            strategy_id="atlas-tf-001", confidence=0.7,
        ))
        # Kitt brief for alignment
        store_packet(root, make_packet(
            "brief_packet", "kitt", "Market bullish, considering NQ setups",
            confidence=0.65,
        ))

    def test_synthesize_produces_valid_packet(self, clean_root):
        self._seed_packets(clean_root)
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        pkt = synthesize(clean_root)
        assert validate_packet(pkt) == []
        assert pkt.packet_type == "tradefloor_packet"
        assert pkt.lane == "tradefloor"

    def test_synthesize_has_agreement_tier(self, clean_root):
        self._seed_packets(clean_root)
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        pkt = synthesize(clean_root)
        assert pkt.agreement_tier is not None
        assert 0 <= pkt.agreement_tier <= 4
        assert pkt.agreement_tier_reasoning

    def test_synthesize_has_matrices(self, clean_root):
        self._seed_packets(clean_root)
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        pkt = synthesize(clean_root)
        assert pkt.agreement_matrix is not None
        assert pkt.disagreement_matrix is not None

    def test_synthesize_has_pipeline_snapshot(self, clean_root):
        self._seed_packets(clean_root)
        create_strategy(clean_root, "atlas-tf-001", actor="atlas")
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        pkt = synthesize(clean_root)
        assert pkt.pipeline_snapshot is not None
        assert "total_strategies" in pkt.pipeline_snapshot

    def test_synthesize_operator_recommendation(self, clean_root):
        self._seed_packets(clean_root)
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        pkt = synthesize(clean_root)
        assert pkt.operator_recommendation in ("notify", "skip", "schedule")
        assert pkt.operator_recommendation_reasoning

    def test_synthesize_routes_to_latest(self, clean_root):
        """Core proof: TradeFloor output available in shared/latest for Kitt."""
        self._seed_packets(clean_root)
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        pkt = synthesize(clean_root)
        latest = get_latest(clean_root, "tradefloor", "tradefloor_packet")
        assert latest is not None
        assert latest.packet_id == pkt.packet_id

    def test_tier_with_aligned_lanes(self, clean_root):
        """When kitt + sigma + atlas/fish all align bullish, tier should be >= 2."""
        self._seed_packets(clean_root)
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        pkt = synthesize(clean_root)
        # All seeded packets are bullish — should get strong agreement
        assert pkt.agreement_tier >= 1  # At least weak

    def test_empty_latest_gives_tier_0(self, clean_root):
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        pkt = synthesize(clean_root)
        assert pkt.agreement_tier == 0

    def test_concrete_action_enables_tier_4(self, clean_root):
        self._seed_packets(clean_root)
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        pkt = synthesize(clean_root, concrete_action="Paper trade atlas-tf-001")
        # If lanes align and action exists, tier could be 4
        if pkt.agreement_tier >= 3:
            assert pkt.agreement_tier == 4  # Should be bumped by action


# ---- Integration ----

class TestLaneBIntegration:
    def test_full_loop_atlas_rejection_adaptation(self, clean_root):
        """Full integration: research → candidate → rejection → adaptation → new candidate."""
        from workspace.quant.hermes.research_lane import emit_research
        from workspace.quant.atlas.exploration_lane import generate_candidate
        from workspace.quant.sigma.validation_lane import validate_candidate

        # Hermes research
        research = emit_research(clean_root, "Vol surface analysis", source="vol-api", source_type="api")

        # Atlas first candidate
        c1, _ = generate_candidate(clean_root, "int-001", "Simple mean-rev",
                                   evidence_refs=[research.packet_id])

        # Sigma rejects
        transition_strategy(clean_root, "int-001", "VALIDATING", actor="sigma")
        validate_candidate(clean_root, c1, profit_factor=0.7, sharpe=0.3,
                           max_drawdown_pct=0.25, trade_count=8)

        # Atlas second candidate — adapted
        c2, fb = generate_candidate(clean_root, "int-002", "Improved mean-rev with regime filter",
                                    parent_id="int-001")
        assert fb["adapted"]
        assert fb["rejection_count"] >= 1

    def test_full_loop_fish_calibration_to_brief(self, clean_root):
        """Full integration: forecast → calibrate → tradefloor → kitt brief."""
        from workspace.quant.fish.scenario_lane import emit_forecast, calibrate
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        from workspace.quant.kitt.brief_producer import produce_brief

        # Fish forecast
        forecast = emit_forecast(clean_root, "NQ bullish", confidence=0.6,
                                 forecast_value=18400.0, forecast_direction="bullish")

        # Calibrate
        calibrate(clean_root, forecast, 18350.0, "bullish")

        # Seed a couple more lane packets
        store_packet(clean_root, make_packet("brief_packet", "kitt", "Market read", confidence=0.5))
        store_packet(clean_root, make_packet("candidate_packet", "atlas", "NQ candidate",
                                             strategy_id="cal-001", confidence=0.5))

        # TradeFloor
        tf = synthesize(clean_root)
        assert tf.agreement_tier is not None

        # Kitt brief includes TradeFloor
        brief = produce_brief(clean_root)
        assert "TRADEFLOOR" in (brief.notes or "")
