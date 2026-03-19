#!/usr/bin/env python3
"""Tests proving TradeFloor synthesis is derived from real lane evidence.

Acceptance criteria:
  1. TradeFloor reads actual lane packets and computes agreement from them
  2. Agreement tier changes when upstream lane evidence changes
  3. Fish calibration state adjusts Fish confidence in synthesis
  4. Risk zones surface in synthesis output
  5. Evidence trail tracks which packets informed the synthesis
  6. Cadence + override + degraded mode work correctly
  7. Kitt brief reflects the real synthesis
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet, validate_packet
from workspace.quant.shared.packet_store import store_packet, get_latest
from workspace.quant.tradefloor.synthesis_lane import (
    synthesize, CadenceRefused,
    _extract_lane_positions, _build_agreement_matrix,
    _build_disagreement_matrix, _determine_agreement_tier,
    _apply_calibration_adjustments, _get_risk_context,
    _classify_direction, _build_synthesis_text,
)
from workspace.quant.kitt.brief_producer import produce_brief


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


def _seed_bullish(root):
    """Seed all lanes with bullish packets, all above confidence threshold."""
    store_packet(root, make_packet(
        "research_packet", "hermes", "NQ bullish momentum detected in research",
        confidence=0.65))
    store_packet(root, make_packet(
        "candidate_packet", "atlas", "NQ breakout strategy shows bullish edge",
        strategy_id="atlas-tf-001", confidence=0.65))
    store_packet(root, make_packet(
        "forecast_packet", "fish", "NQ bullish forecast: upside expected",
        confidence=0.65, notes="direction=bullish; target=18500"))
    store_packet(root, make_packet(
        "validation_packet", "sigma", "atlas-tf-001 validated, bullish setup confirmed",
        strategy_id="atlas-tf-001", confidence=0.7))
    store_packet(root, make_packet(
        "brief_packet", "kitt", "Market bullish, considering NQ long setups",
        confidence=0.65))


def _seed_mixed(root):
    """Seed lanes with mixed (disagreeing) signals."""
    store_packet(root, make_packet(
        "research_packet", "hermes", "NQ research shows bearish macro backdrop",
        confidence=0.6))
    store_packet(root, make_packet(
        "candidate_packet", "atlas", "NQ breakout strategy targeting upside",
        strategy_id="atlas-mix-001", confidence=0.5))
    store_packet(root, make_packet(
        "forecast_packet", "fish", "NQ bearish forecast: downside risk",
        confidence=0.55, notes="direction=bearish; target=17500"))
    store_packet(root, make_packet(
        "validation_packet", "sigma", "atlas-mix-001 validated with bullish bias",
        strategy_id="atlas-mix-001", confidence=0.6))
    store_packet(root, make_packet(
        "brief_packet", "kitt", "Market uncertain, mixed signals across lanes",
        confidence=0.5))


# ---- Direction classification ----

class TestDirectionClassification:
    def test_bullish_keywords(self):
        assert _classify_direction("NQ bullish breakout expected") == "bullish"

    def test_bearish_keywords(self):
        assert _classify_direction("NQ bearish breakdown likely") == "bearish"

    def test_neutral_no_keywords(self):
        assert _classify_direction("NQ range-bound consolidation") == "neutral"

    def test_notes_contribute(self):
        assert _classify_direction("NQ forecast", "direction=bullish") == "bullish"

    def test_mixed_signals_resolve_by_count(self):
        # "bullish breakout" has 2 bullish words, "short" has 1 bearish
        assert _classify_direction("NQ bullish breakout despite short-term risk") == "bullish"


# ---- Position extraction ----

class TestPositionExtraction:
    def test_extracts_positions_from_seeded_lanes(self, clean_root):
        _seed_bullish(clean_root)
        from workspace.quant.shared.packet_store import get_all_latest
        latest = get_all_latest(clean_root)
        positions = _extract_lane_positions(latest)

        assert "hermes" in positions
        assert "atlas" in positions
        assert "fish" in positions
        assert "sigma" in positions
        assert "kitt" in positions
        assert "tradefloor" not in positions  # Should exclude own lane

    def test_prefers_forecast_over_calibration_for_fish(self, clean_root):
        """Fish position should come from forecast, not calibration."""
        store_packet(clean_root, make_packet(
            "calibration_packet", "fish", "Calibration result: good score",
            confidence=0.7, notes="calibration_score=0.9"))
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bullish forecast",
            confidence=0.6, notes="direction=bullish"))

        from workspace.quant.shared.packet_store import get_all_latest
        latest = get_all_latest(clean_root)
        positions = _extract_lane_positions(latest)

        assert positions["fish"]["packet_type"] == "forecast_packet"

    def test_prefers_candidate_over_batch_for_atlas(self, clean_root):
        store_packet(clean_root, make_packet(
            "experiment_batch_packet", "atlas", "Batch completed",
            confidence=0.5))
        store_packet(clean_root, make_packet(
            "candidate_packet", "atlas", "NQ breakout bullish candidate",
            strategy_id="atlas-pref", confidence=0.6))

        from workspace.quant.shared.packet_store import get_all_latest
        latest = get_all_latest(clean_root)
        positions = _extract_lane_positions(latest)

        assert positions["atlas"]["packet_type"] == "candidate_packet"

    def test_prefers_promotion_over_rejection_for_sigma(self, clean_root):
        store_packet(clean_root, make_packet(
            "strategy_rejection_packet", "sigma", "Rejected: poor OOS",
            strategy_id="sigma-rej", rejection_reason="poor_oos",
            rejection_detail="PF 0.8", confidence=0.3))
        store_packet(clean_root, make_packet(
            "promotion_packet", "sigma", "Promoted: strong bullish candidate",
            strategy_id="sigma-prom", confidence=0.8))

        from workspace.quant.shared.packet_store import get_all_latest
        latest = get_all_latest(clean_root)
        positions = _extract_lane_positions(latest)

        assert positions["sigma"]["packet_type"] == "promotion_packet"


# ---- Agreement tier logic ----

class TestAgreementTier:
    def test_tier_0_no_data(self, clean_root):
        pkt = synthesize(clean_root)
        assert pkt.agreement_tier == 0

    def test_tier_0_single_lane(self, clean_root):
        store_packet(clean_root, make_packet(
            "research_packet", "hermes", "NQ research bullish", confidence=0.6))
        pkt = synthesize(clean_root)
        assert pkt.agreement_tier == 0

    def test_tier_1_two_lanes_agree(self, clean_root):
        store_packet(clean_root, make_packet(
            "research_packet", "hermes", "NQ bullish momentum detected", confidence=0.6))
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bullish forecast expected",
            confidence=0.55, notes="direction=bullish"))
        pkt = synthesize(clean_root)
        assert pkt.agreement_tier == 1

    def test_tier_2_kitt_sigma_plus_supporting(self, clean_root):
        store_packet(clean_root, make_packet(
            "brief_packet", "kitt", "Market bullish, strong setups forming",
            confidence=0.55))
        store_packet(clean_root, make_packet(
            "validation_packet", "sigma", "Validated bullish candidate",
            strategy_id="t2-001", confidence=0.55))
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bullish forecast: upside likely",
            confidence=0.55, notes="direction=bullish"))
        pkt = synthesize(clean_root)
        assert pkt.agreement_tier == 2

    def test_tier_3_high_conviction(self, clean_root):
        _seed_bullish(clean_root)
        pkt = synthesize(clean_root)
        assert pkt.agreement_tier == 3
        assert "high-conviction" in pkt.thesis.lower() or "tier 3" in pkt.thesis.lower()

    def test_tier_4_with_concrete_action(self, clean_root):
        _seed_bullish(clean_root)
        pkt = synthesize(clean_root, concrete_action="Paper-trade atlas-tf-001")
        assert pkt.agreement_tier == 4
        assert "actionable" in pkt.thesis.lower() or "tier 4" in pkt.thesis.lower()

    def test_tier_drops_when_confidence_below_threshold(self, clean_root):
        """Tier 3 requires all confidence >= 0.6. Below that → tier 2."""
        store_packet(clean_root, make_packet(
            "brief_packet", "kitt", "Market bullish outlook",
            confidence=0.65))
        store_packet(clean_root, make_packet(
            "validation_packet", "sigma", "Validated bullish candidate",
            strategy_id="low-conf", confidence=0.65))
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bullish forecast",
            confidence=0.45, notes="direction=bullish"))  # Below threshold
        pkt = synthesize(clean_root)
        assert pkt.agreement_tier == 2  # Strong but not high-conviction

    def test_disagreement_limits_tier(self, clean_root):
        """Active disagreement between lanes should prevent high tiers."""
        store_packet(clean_root, make_packet(
            "brief_packet", "kitt", "Market bullish",
            confidence=0.7))
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bearish breakdown expected",
            confidence=0.7, notes="direction=bearish"))
        pkt = synthesize(clean_root)
        # Fish bearish vs Kitt bullish: tier can't be high
        assert pkt.agreement_tier <= 1


# ---- Tier changes with evidence changes ----

class TestTierChangesWithEvidence:
    def test_tier_changes_when_bearish_lane_flips_bullish(self, clean_root):
        """Adding a bearish lane then flipping it bullish should change the tier."""
        # Start with bullish kitt + sigma
        store_packet(clean_root, make_packet(
            "brief_packet", "kitt", "Market bullish outlook",
            confidence=0.65))
        store_packet(clean_root, make_packet(
            "validation_packet", "sigma", "Validated bullish candidate",
            strategy_id="flip-001", confidence=0.65))
        # Fish starts bearish
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bearish, downside risk",
            confidence=0.7, notes="direction=bearish"))

        pkt1 = synthesize(clean_root)
        tier_with_disagreement = pkt1.agreement_tier

        # Fish flips bullish (latest overwrites)
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bullish, upside breakout",
            confidence=0.7, notes="direction=bullish"))

        pkt2 = synthesize(clean_root, override_reason="testing flip")
        tier_after_flip = pkt2.agreement_tier

        assert tier_after_flip > tier_with_disagreement

    def test_tier_changes_when_lane_added(self, clean_root):
        """Adding a new aligned lane should increase the tier."""
        store_packet(clean_root, make_packet(
            "research_packet", "hermes", "NQ bullish research", confidence=0.6))
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bullish forecast",
            confidence=0.6, notes="direction=bullish"))

        pkt1 = synthesize(clean_root)
        tier_two_lanes = pkt1.agreement_tier
        assert tier_two_lanes >= 1  # At least weak

        # Add kitt + sigma alignment
        store_packet(clean_root, make_packet(
            "brief_packet", "kitt", "Market bullish, strong setups",
            confidence=0.65))
        store_packet(clean_root, make_packet(
            "validation_packet", "sigma", "Validated bullish candidate",
            strategy_id="add-001", confidence=0.65))

        pkt2 = synthesize(clean_root, override_reason="testing add")
        tier_four_lanes = pkt2.agreement_tier
        assert tier_four_lanes > tier_two_lanes

    def test_tier_drops_when_supporting_lanes_go_neutral(self, clean_root):
        """If both supporting lanes go neutral, tier should drop below 3."""
        _seed_bullish(clean_root)
        pkt1 = synthesize(clean_root)
        high_tier = pkt1.agreement_tier
        assert high_tier >= 3

        # Both Fish and Atlas go neutral → no supporting lane for tier 3
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ range-bound, no clear direction",
            confidence=0.5, notes="direction=neutral"))
        store_packet(clean_root, make_packet(
            "candidate_packet", "atlas", "NQ consolidation, no directional edge",
            strategy_id="atlas-neutral", confidence=0.5))

        pkt2 = synthesize(clean_root, override_reason="testing neutral flip")
        lower_tier = pkt2.agreement_tier
        assert lower_tier < high_tier

    def test_tier_drops_when_confidence_decreases(self, clean_root):
        """Dropping a lane's confidence below threshold should lower tier."""
        _seed_bullish(clean_root)
        pkt1 = synthesize(clean_root)
        assert pkt1.agreement_tier >= 3

        # Drop atlas confidence below threshold
        store_packet(clean_root, make_packet(
            "candidate_packet", "atlas", "NQ breakout bullish but low confidence",
            strategy_id="low-001", confidence=0.3))
        # Drop fish confidence too
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bullish but uncertain",
            confidence=0.3, notes="direction=bullish"))

        pkt2 = synthesize(clean_root, override_reason="testing confidence drop")
        assert pkt2.agreement_tier < pkt1.agreement_tier


# ---- Fish calibration integration ----

class TestFishCalibrationIntegration:
    def test_fish_confidence_adjusted_by_calibration(self, clean_root):
        """Fish confidence should be penalized when calibration track record is poor."""
        from workspace.quant.fish.scenario_lane import emit_forecast, calibrate

        # Build poor calibration history (4 wrong forecasts)
        for i in range(4):
            f = emit_forecast(clean_root, f"Wrong {i}", confidence=0.5,
                              forecast_value=18000.0, forecast_direction="bullish")
            calibrate(clean_root, f, 17000.0, "bearish")

        # Seed a bullish fish forecast for TradeFloor
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bullish forecast",
            confidence=0.7, notes="direction=bullish"))

        from workspace.quant.shared.packet_store import get_all_latest
        latest = get_all_latest(clean_root)
        positions = _extract_lane_positions(latest)
        original_conf = positions["fish"]["confidence"]

        adjusted = _apply_calibration_adjustments(clean_root, positions)
        assert adjusted["fish"]["calibration_adjusted"] is True
        assert adjusted["fish"]["confidence"] < original_conf
        assert adjusted["fish"]["original_confidence"] == original_conf

    def test_good_calibration_preserves_confidence(self, clean_root):
        """Good track record should not penalize Fish confidence."""
        from workspace.quant.fish.scenario_lane import emit_forecast, calibrate

        # Build good calibration history
        for i in range(4):
            f = emit_forecast(clean_root, f"Right {i}", confidence=0.5,
                              forecast_value=18000.0, forecast_direction="bullish")
            calibrate(clean_root, f, 18010.0, "bullish")

        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bullish forecast",
            confidence=0.7, notes="direction=bullish"))

        from workspace.quant.shared.packet_store import get_all_latest
        latest = get_all_latest(clean_root)
        positions = _extract_lane_positions(latest)

        adjusted = _apply_calibration_adjustments(clean_root, positions)
        # Good track record: adjusted confidence should be close to original
        assert adjusted["fish"]["confidence"] >= 0.6

    def test_calibration_can_lower_tier(self, clean_root):
        """Poor Fish calibration should lower tier by reducing Fish confidence."""
        from workspace.quant.fish.scenario_lane import emit_forecast, calibrate

        # Build poor calibration
        for i in range(5):
            f = emit_forecast(clean_root, f"Wrong {i}", confidence=0.5,
                              forecast_value=18000.0, forecast_direction="bullish")
            calibrate(clean_root, f, 17000.0, "bearish")

        # Seed high-tier-eligible packets
        store_packet(clean_root, make_packet(
            "brief_packet", "kitt", "Market bullish outlook", confidence=0.65))
        store_packet(clean_root, make_packet(
            "validation_packet", "sigma", "Validated bullish candidate",
            strategy_id="cal-tier", confidence=0.65))
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bullish forecast",
            confidence=0.65, notes="direction=bullish"))

        pkt = synthesize(clean_root)
        # Fish confidence penalized → may not meet 0.6 threshold → tier < 3
        assert pkt.agreement_tier < 3


# ---- Risk zone integration ----

class TestRiskZoneIntegration:
    def test_risk_zones_surface_in_synthesis(self, clean_root):
        from workspace.quant.fish.scenario_lane import emit_risk_map

        emit_risk_map(clean_root, "Elevated VIX risk",
                      risk_zones={"vix_spike": {"level": "high", "trigger": "VIX > 30"}})

        _seed_bullish(clean_root)
        pkt = synthesize(clean_root)

        assert "vix_spike" in (pkt.confidence_weighted_synthesis or "")
        # Should have risk-driven next action
        risk_actions = [a for a in (pkt.next_actions or []) if "risk" in a.get("action", "").lower()]
        assert len(risk_actions) > 0

    def test_no_risk_zones_no_risk_action(self, clean_root):
        _seed_bullish(clean_root)
        pkt = synthesize(clean_root)
        risk_actions = [a for a in (pkt.next_actions or []) if "risk" in a.get("action", "").lower()]
        assert len(risk_actions) == 0


# ---- Evidence trail ----

class TestEvidenceTrail:
    def test_synthesis_includes_evidence_refs(self, clean_root):
        _seed_bullish(clean_root)
        pkt = synthesize(clean_root)
        assert len(pkt.evidence_refs) >= 3  # At least hermes, atlas, fish, sigma, kitt
        # Each evidence ref should be a real packet ID
        for ref in pkt.evidence_refs:
            assert ref.startswith(("hermes-", "atlas-", "fish-", "sigma-", "kitt-"))

    def test_evidence_refs_change_with_new_packets(self, clean_root):
        store_packet(clean_root, make_packet(
            "research_packet", "hermes", "First research", confidence=0.5))
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "First forecast", confidence=0.5))
        pkt1 = synthesize(clean_root)
        refs1 = set(pkt1.evidence_refs)

        # Add new packet from atlas
        store_packet(clean_root, make_packet(
            "candidate_packet", "atlas", "New candidate",
            strategy_id="ev-001", confidence=0.5))
        pkt2 = synthesize(clean_root, override_reason="testing evidence")
        refs2 = set(pkt2.evidence_refs)

        # New synthesis should include the atlas packet
        atlas_refs = [r for r in refs2 if r.startswith("atlas-")]
        assert len(atlas_refs) > 0
        assert refs2 != refs1


# ---- Synthesis text ----

class TestSynthesisText:
    def test_synthesis_ordered_by_confidence(self, clean_root):
        positions = {
            "fish": {"thesis": "NQ bullish", "confidence": 0.8, "direction": "bullish",
                     "packet_id": "test", "packet_type": "forecast_packet", "priority": "medium"},
            "hermes": {"thesis": "Research neutral", "confidence": 0.3, "direction": "neutral",
                       "packet_id": "test2", "packet_type": "research_packet", "priority": "medium"},
        }
        text = _build_synthesis_text(positions, {})
        # Higher confidence lane should appear first
        fish_pos = text.index("fish")
        hermes_pos = text.index("hermes")
        assert fish_pos < hermes_pos

    def test_synthesis_includes_calibration_marker(self, clean_root):
        positions = {
            "fish": {"thesis": "NQ bullish", "confidence": 0.6, "direction": "bullish",
                     "packet_id": "test", "packet_type": "forecast_packet", "priority": "medium",
                     "calibration_adjusted": True, "track_record_confidence": 0.75},
        }
        text = _build_synthesis_text(positions, {})
        assert "cal=" in text

    def test_synthesis_includes_high_risk_zones(self, clean_root):
        positions = {
            "fish": {"thesis": "NQ bullish", "confidence": 0.6, "direction": "bullish",
                     "packet_id": "test", "packet_type": "forecast_packet", "priority": "medium"},
        }
        risk_zones = {"vix_spike": {"level": "high", "trigger": "VIX > 30"}}
        text = _build_synthesis_text(positions, risk_zones)
        assert "RISK" in text
        assert "vix_spike" in text


# ---- Kitt brief integration ----

class TestKittBriefIntegration:
    def test_brief_reflects_synthesis(self, clean_root):
        _seed_bullish(clean_root)
        tf_pkt = synthesize(clean_root)

        brief = produce_brief(clean_root)
        assert "TRADEFLOOR" in (brief.notes or "")
        assert str(tf_pkt.agreement_tier) in (brief.notes or "")

    def test_brief_shows_tier_change(self, clean_root):
        """Brief should reflect updated tier after evidence changes."""
        store_packet(clean_root, make_packet(
            "research_packet", "hermes", "NQ neutral research", confidence=0.5))
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ neutral forecast",
            confidence=0.5))
        tf1 = synthesize(clean_root)
        brief1 = produce_brief(clean_root)

        # Add aligned packets → higher tier
        store_packet(clean_root, make_packet(
            "brief_packet", "kitt", "Market bullish", confidence=0.7))
        store_packet(clean_root, make_packet(
            "validation_packet", "sigma", "Validated bullish",
            strategy_id="brief-001", confidence=0.7))
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bullish upside expected",
            confidence=0.7, notes="direction=bullish"))
        store_packet(clean_root, make_packet(
            "research_packet", "hermes", "NQ bullish momentum in research",
            confidence=0.7))

        tf2 = synthesize(clean_root, override_reason="testing brief update")
        brief2 = produce_brief(clean_root)

        # Brief should now show higher tier
        assert tf2.agreement_tier > tf1.agreement_tier
        assert str(tf2.agreement_tier) in (brief2.notes or "")


# ---- Operator recommendation ----

class TestOperatorRecommendation:
    def test_tier_3_notifies_operator(self, clean_root):
        _seed_bullish(clean_root)
        pkt = synthesize(clean_root)
        assert pkt.agreement_tier >= 3
        assert pkt.operator_recommendation == "notify"
        assert pkt.escalation_level == "operator_review"

    def test_tier_0_skips_notification(self, clean_root):
        pkt = synthesize(clean_root)
        assert pkt.agreement_tier == 0
        assert pkt.operator_recommendation == "skip"
        assert pkt.escalation_level == "team_only"

    def test_tier_2_kitt_only(self, clean_root):
        store_packet(clean_root, make_packet(
            "brief_packet", "kitt", "Market bullish outlook",
            confidence=0.55))
        store_packet(clean_root, make_packet(
            "validation_packet", "sigma", "Validated bullish candidate",
            strategy_id="t2-001", confidence=0.55))
        store_packet(clean_root, make_packet(
            "forecast_packet", "fish", "NQ bullish forecast",
            confidence=0.55, notes="direction=bullish"))
        pkt = synthesize(clean_root)
        assert pkt.agreement_tier == 2
        assert pkt.operator_recommendation == "skip"
        assert pkt.escalation_level == "kitt_only"


# ---- Packet validity ----

class TestPacketValidity:
    def test_synthesis_packet_validates(self, clean_root):
        _seed_bullish(clean_root)
        pkt = synthesize(clean_root)
        errors = validate_packet(pkt)
        assert errors == []
        assert pkt.packet_type == "tradefloor_packet"
        assert pkt.lane == "tradefloor"

    def test_degraded_packet_validates(self, clean_root):
        from workspace.quant.shared.scheduler.scheduler import register_heavy_job
        register_heavy_job(clean_root, "a", "NIMO")
        register_heavy_job(clean_root, "b", "SonLM")
        register_heavy_job(clean_root, "c", "NIMO")
        pkt = synthesize(clean_root)
        errors = validate_packet(pkt)
        assert errors == []
        assert pkt.degraded is True

    def test_override_packet_validates(self, clean_root):
        _seed_bullish(clean_root)
        synthesize(clean_root)
        pkt = synthesize(clean_root, override_reason="urgent regime shift")
        errors = validate_packet(pkt)
        assert errors == []
        assert "override" in pkt.thesis
