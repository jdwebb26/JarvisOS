#!/usr/bin/env python3
"""Tests for Pulse discretionary alert lane.

Proves:
  1. Loose alert parsing works (level-only, note-based, freeform)
  2. Clustering and dedup work
  3. Cooldown prevents spam
  4. Learning accumulates from outcomes
  5. Review-gated downstream proposals work
  6. Downstream caps prevent spam
  7. Core quant lanes remain autonomous (Pulse cannot inject without approval)
  8. Kitt brief separates Pulse from core lanes
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet, validate_packet
from workspace.quant.shared.packet_store import store_packet, list_lane_packets
from workspace.quant.pulse.alert_lane import (
    parse_alert, ingest_alert, cluster_alerts, check_alert_cooldown,
    record_outcome, build_learning_state,
    propose_downstream, approve_proposal,
    emit_health_summary, PROPOSAL_TARGETS,
    _MAX_PROPOSALS_PER_CLUSTER_24H, _MAX_ATLAS_SEEDS_24H, _MAX_FISH_INJECTIONS_24H,
)


@pytest.fixture
def clean_root(tmp_path):
    (tmp_path / "workspace" / "quant" / "shared" / "latest").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "registries").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "config").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "scheduler").mkdir(parents=True)
    for lane in ["atlas", "fish", "hermes", "sigma", "kitt", "tradefloor", "executor", "pulse"]:
        (tmp_path / "workspace" / "quant" / lane).mkdir(parents=True)
    return tmp_path


# ---- Alert parsing ----

class TestAlertParsing:
    def test_level_only(self):
        r = parse_alert("18450")
        assert r["level"] == 18450.0
        assert r["symbol"] == "NQ"

    def test_level_with_note(self):
        r = parse_alert("18450 liquidity sweep")
        assert r["level"] == 18450.0
        assert "liquidity" in r["tags"]
        assert "sweep" in r["tags"]

    def test_freeform_with_level(self):
        r = parse_alert("NQ reclaimed session high, watching 18500")
        assert r["level"] == 18500.0
        assert "reclaim" in r["tags"]
        assert "session" in r["tags"]
        assert r["symbol"] == "NQ"

    def test_direction_inferred(self):
        r = parse_alert("bullish breakout above 18400")
        assert r["direction"] == "bullish"
        assert "breakout" in r["tags"]

    def test_bearish_direction(self):
        r = parse_alert("rejection at resistance 18600")
        assert r["direction"] == "bearish"
        assert "rejection" in r["tags"]
        assert "resistance" in r["tags"]

    def test_symbol_inferred_from_text(self):
        r = parse_alert("ES gap fill at 5500")
        assert r["symbol"] == "ES"
        assert r["level"] == 5500.0

    def test_no_level_no_crash(self):
        r = parse_alert("market looks choppy")
        assert r["level"] is None
        assert r["note"] is not None

    def test_empty_text(self):
        r = parse_alert("")
        assert r["level"] is None
        assert r["tags"] == []

    def test_explicit_level_overrides(self):
        r = parse_alert("some note", level=18300.0)
        assert r["level"] == 18300.0

    def test_explicit_direction_overrides(self):
        r = parse_alert("bearish note", direction="bullish")
        assert r["direction"] == "bullish"

    def test_vwap_tag(self):
        r = parse_alert("VWAP reclaim at 18200")
        assert "vwap" in r["tags"]
        assert "reclaim" in r["tags"]

    def test_gap_tag(self):
        r = parse_alert("FVG fill at 18100")
        assert "gap" in r["tags"]


# ---- Alert ingestion ----

class TestAlertIngestion:
    def test_ingest_creates_packet(self, clean_root):
        pkt, parsed = ingest_alert(clean_root, "18450 liquidity sweep")
        assert validate_packet(pkt) == []
        assert pkt.packet_type == "pulse_alert_packet"
        assert pkt.lane == "pulse"
        assert "level=18450" in pkt.notes

    def test_ingest_level_only(self, clean_root):
        pkt, parsed = ingest_alert(clean_root, "18300")
        assert validate_packet(pkt) == []
        assert parsed["level"] == 18300.0

    def test_ingest_stores_to_pulse_lane(self, clean_root):
        ingest_alert(clean_root, "18450")
        packets = list_lane_packets(clean_root, "pulse", "pulse_alert_packet")
        assert len(packets) == 1


# ---- Clustering ----

class TestClustering:
    def test_nearby_alerts_cluster(self, clean_root):
        ingest_alert(clean_root, "18450")
        ingest_alert(clean_root, "18455")
        clusters = cluster_alerts(clean_root)
        # Should cluster together (within 10 points)
        big = [c for c in clusters if c["count"] >= 2]
        assert len(big) == 1
        assert big[0]["count"] == 2

    def test_distant_alerts_separate(self, clean_root):
        ingest_alert(clean_root, "18450")
        ingest_alert(clean_root, "18600")
        clusters = cluster_alerts(clean_root)
        assert len(clusters) == 2
        assert all(c["count"] == 1 for c in clusters)

    def test_cluster_emits_packet(self, clean_root):
        ingest_alert(clean_root, "18450")
        ingest_alert(clean_root, "18455")
        cluster_alerts(clean_root)
        cpkts = list_lane_packets(clean_root, "pulse", "pulse_cluster_packet")
        assert len(cpkts) >= 1

    def test_cluster_tags_merged(self, clean_root):
        ingest_alert(clean_root, "18450 liquidity")
        ingest_alert(clean_root, "18455 sweep")
        clusters = cluster_alerts(clean_root)
        big = [c for c in clusters if c["count"] >= 2]
        assert "liquidity" in big[0]["tags"]
        assert "sweep" in big[0]["tags"]


# ---- Cooldown / anti-spam ----

class TestCooldown:
    def test_cooldown_blocks_rapid_duplicates(self, clean_root):
        ingest_alert(clean_root, "18450")
        assert check_alert_cooldown(clean_root, "NQ", 18450.0) is True

    def test_different_level_not_blocked(self, clean_root):
        ingest_alert(clean_root, "18450")
        assert check_alert_cooldown(clean_root, "NQ", 18600.0) is False

    def test_different_symbol_not_blocked(self, clean_root):
        ingest_alert(clean_root, "18450")
        assert check_alert_cooldown(clean_root, "ES", 18450.0) is False


# ---- Learning ----

class TestLearning:
    def test_empty_learning(self, clean_root):
        state = build_learning_state(clean_root)
        assert state["total_outcomes"] == 0
        assert state["hit_rate"] is None

    def test_outcome_recorded(self, clean_root):
        pkt, _ = ingest_alert(clean_root, "18450 liquidity sweep")
        record_outcome(clean_root, pkt.packet_id, hit=True)
        state = build_learning_state(clean_root)
        assert state["total_outcomes"] == 1
        assert state["hits"] == 1
        assert state["hit_rate"] == 1.0

    def test_mixed_outcomes(self, clean_root):
        p1, _ = ingest_alert(clean_root, "18450 support")
        p2, _ = ingest_alert(clean_root, "18600 resistance")
        record_outcome(clean_root, p1.packet_id, hit=True)
        record_outcome(clean_root, p2.packet_id, hit=False)
        state = build_learning_state(clean_root)
        assert state["total_outcomes"] == 2
        assert state["hits"] == 1
        assert state["misses"] == 1
        assert state["hit_rate"] == 0.5

    def test_per_tag_rates(self, clean_root):
        p1, _ = ingest_alert(clean_root, "18450 liquidity sweep")
        p2, _ = ingest_alert(clean_root, "18600 breakout")
        record_outcome(clean_root, p1.packet_id, hit=True)
        record_outcome(clean_root, p2.packet_id, hit=False)
        state = build_learning_state(clean_root)
        assert state["per_tag_rate"].get("liquidity", 0) > 0
        assert state["per_tag_rate"].get("breakout", 0) == 0

    def test_noise_detection(self, clean_root):
        ingest_alert(clean_root, "18450")
        ingest_alert(clean_root, "18600")
        # No outcomes recorded → both are noise
        state = build_learning_state(clean_root)
        assert state["noise_alerts"] == 2

    def test_learning_emits_packet(self, clean_root):
        p1, _ = ingest_alert(clean_root, "18450")
        record_outcome(clean_root, p1.packet_id, hit=True)
        build_learning_state(clean_root)
        lpkts = list_lane_packets(clean_root, "pulse", "pulse_learning_packet")
        assert len(lpkts) >= 1


# ---- Review-gated downstream proposals ----

class TestReviewGatedProposals:
    def test_propose_creates_review_packet(self, clean_root):
        pkt = propose_downstream(
            clean_root, "fish_scenario",
            "NQ liquidity sweep cluster suggests downside scenario",
            symbol="NQ", cluster_level=18450.0,
        )
        assert pkt is not None
        assert pkt.packet_type == "pulse_review_proposal_packet"
        assert "target=fish_scenario" in pkt.notes
        assert pkt.escalation_level == "operator_review"

    def test_proposal_does_not_create_downstream(self, clean_root):
        """Proposal alone must NOT create a fish/atlas/hermes packet."""
        propose_downstream(
            clean_root, "fish_scenario", "Test proposal", symbol="NQ",
        )
        fish_pkts = list_lane_packets(clean_root, "fish")
        assert len(fish_pkts) == 0

    def test_approve_creates_downstream(self, clean_root):
        proposal = propose_downstream(
            clean_root, "fish_scenario",
            "NQ sweep cluster downside scenario", symbol="NQ",
        )
        downstream = approve_proposal(clean_root, proposal.packet_id)
        assert downstream is not None
        assert downstream.packet_type == "scenario_packet"
        assert downstream.lane == "fish"
        assert "[from Pulse]" in downstream.thesis
        assert "source=pulse_approved" in downstream.notes

    def test_approve_hermes_research(self, clean_root):
        proposal = propose_downstream(
            clean_root, "hermes_research",
            "Research NQ gap fill patterns", symbol="NQ",
        )
        downstream = approve_proposal(clean_root, proposal.packet_id)
        assert downstream.packet_type == "research_request_packet"
        assert downstream.lane == "hermes"

    def test_approve_atlas_seed(self, clean_root):
        proposal = propose_downstream(
            clean_root, "atlas_seed",
            "Seed NQ liquidity sweep strategy", symbol="NQ",
        )
        downstream = approve_proposal(clean_root, proposal.packet_id)
        assert downstream.packet_type == "idea_packet"
        assert downstream.lane == "atlas"

    def test_invalid_target_raises(self, clean_root):
        with pytest.raises(ValueError):
            propose_downstream(clean_root, "invalid_target", "Test")


# ---- Downstream caps / anti-spam ----

class TestDownstreamCaps:
    def test_per_cluster_cap(self, clean_root):
        for i in range(_MAX_PROPOSALS_PER_CLUSTER_24H):
            pkt = propose_downstream(
                clean_root, "fish_scenario", f"Proposal {i}",
                symbol="NQ", cluster_level=18450.0,
            )
            assert pkt is not None

        # Next one should be rate-limited
        blocked = propose_downstream(
            clean_root, "fish_scenario", "Should be blocked",
            symbol="NQ", cluster_level=18450.0,
        )
        assert blocked is None

    def test_atlas_seed_cap(self, clean_root):
        for i in range(_MAX_ATLAS_SEEDS_24H):
            pkt = propose_downstream(
                clean_root, "atlas_seed", f"Atlas seed {i}", symbol="NQ",
            )
            assert pkt is not None

        blocked = propose_downstream(
            clean_root, "atlas_seed", "Should be blocked", symbol="NQ",
        )
        assert blocked is None

    def test_fish_injection_cap(self, clean_root):
        for i in range(_MAX_FISH_INJECTIONS_24H):
            pkt = propose_downstream(
                clean_root, "fish_scenario", f"Fish injection {i}", symbol="NQ",
            )
            assert pkt is not None

        blocked = propose_downstream(
            clean_root, "fish_scenario", "Should be blocked", symbol="NQ",
        )
        assert blocked is None

    def test_different_clusters_not_rate_limited(self, clean_root):
        for i in range(_MAX_PROPOSALS_PER_CLUSTER_24H):
            propose_downstream(
                clean_root, "fish_scenario", f"Cluster A prop {i}",
                symbol="NQ", cluster_level=18450.0,
            )

        # Different cluster should still work
        pkt = propose_downstream(
            clean_root, "fish_scenario", "Cluster B",
            symbol="NQ", cluster_level=18600.0,
        )
        assert pkt is not None


# ---- Core quant autonomy ----

class TestCoreQuantAutonomy:
    def test_pulse_packets_stay_in_pulse_lane(self, clean_root):
        """Pulse ingestion must not create packets in other lanes."""
        ingest_alert(clean_root, "18450 liquidity sweep")
        ingest_alert(clean_root, "18455 session reclaim")
        cluster_alerts(clean_root)

        for lane in ["fish", "atlas", "hermes", "sigma", "kitt", "tradefloor"]:
            pkts = list_lane_packets(clean_root, lane)
            assert len(pkts) == 0, f"Pulse leaked into {lane}"

    def test_proposal_without_approval_stays_in_pulse(self, clean_root):
        propose_downstream(
            clean_root, "fish_scenario", "Proposed scenario", symbol="NQ",
        )
        propose_downstream(
            clean_root, "atlas_seed", "Proposed atlas seed", symbol="NQ",
        )
        propose_downstream(
            clean_root, "hermes_research", "Proposed research", symbol="NQ",
        )

        for lane in ["fish", "atlas", "hermes"]:
            pkts = list_lane_packets(clean_root, lane)
            assert len(pkts) == 0, f"Unapproved proposal leaked into {lane}"

    def test_only_approval_releases_downstream(self, clean_root):
        """Only approve_proposal should create packets in target lanes."""
        proposal = propose_downstream(
            clean_root, "fish_scenario", "Scenario test", symbol="NQ",
        )
        # Before approval: fish is empty
        assert len(list_lane_packets(clean_root, "fish")) == 0

        # After approval: fish has exactly one packet
        approve_proposal(clean_root, proposal.packet_id)
        assert len(list_lane_packets(clean_root, "fish")) == 1


# ---- Kitt integration ----

class TestKittIntegration:
    def test_brief_separates_pulse_from_core(self, clean_root):
        from workspace.quant.kitt.brief_producer import produce_brief

        ingest_alert(clean_root, "18450 liquidity sweep")
        propose_downstream(
            clean_root, "fish_scenario", "Test proposal", symbol="NQ",
        )

        brief = produce_brief(clean_root)
        notes = brief.notes or ""

        # Pulse section must be separate
        assert "PULSE (discretionary)" in notes
        # Core feedback loops must also be present
        assert "FEEDBACK LOOPS" in notes

    def test_brief_shows_pending_proposals(self, clean_root):
        from workspace.quant.kitt.brief_producer import produce_brief

        ingest_alert(clean_root, "18450")
        propose_downstream(
            clean_root, "fish_scenario", "Awaiting review", symbol="NQ",
        )

        brief = produce_brief(clean_root)
        notes = brief.notes or ""
        assert "proposal" in notes.lower() or "review" in notes.lower()


# ---- Health summary ----

class TestPulseHealth:
    def test_health_summary_valid(self, clean_root):
        ingest_alert(clean_root, "18450")
        h = emit_health_summary(clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z")
        assert validate_packet(h) == []
        assert h.lane == "pulse"
        assert "1 alerts" in h.thesis


# ---- End-to-end proof ----

class TestEndToEnd:
    def test_full_pulse_lifecycle(self, clean_root):
        """TradingView alert → Pulse intake → learning/proposal →
        #review approval gate → downstream release."""
        # Step 1: Operator sends TradingView alerts
        a1, _ = ingest_alert(clean_root, "NQ 18450 liquidity sweep at session low")
        a2, _ = ingest_alert(clean_root, "18455 another sweep same area")
        a3, _ = ingest_alert(clean_root, "ES 5500 breakout above resistance")

        # Step 2: Cluster
        clusters = cluster_alerts(clean_root)
        nq_clusters = [c for c in clusters if c["symbol"] == "NQ" and c["count"] >= 2]
        assert len(nq_clusters) == 1

        # Step 3: Record outcomes
        record_outcome(clean_root, a1.packet_id, hit=True, realized_move=25.0)
        record_outcome(clean_root, a3.packet_id, hit=False)

        # Step 4: Build learning
        state = build_learning_state(clean_root)
        assert state["total_outcomes"] == 2
        assert state["hits"] == 1
        assert state["noise_alerts"] == 1  # a2 has no outcome

        # Step 5: Propose downstream (review-gated)
        proposal = propose_downstream(
            clean_root, "fish_scenario",
            "NQ liquidity sweep cluster at 18450 suggests downside risk",
            symbol="NQ", cluster_level=18450.0,
            evidence_refs=[a1.packet_id, a2.packet_id],
        )
        assert proposal is not None
        assert proposal.escalation_level == "operator_review"

        # Step 6: Verify nothing leaked to Fish yet
        assert len(list_lane_packets(clean_root, "fish")) == 0

        # Step 7: Operator approves via #review
        downstream = approve_proposal(clean_root, proposal.packet_id)
        assert downstream is not None
        assert downstream.lane == "fish"
        assert downstream.packet_type == "scenario_packet"
        assert "[from Pulse]" in downstream.thesis

        # Step 8: Fish now has exactly one packet (from approved proposal)
        fish_pkts = list_lane_packets(clean_root, "fish")
        assert len(fish_pkts) == 1
        assert "pulse_approved" in fish_pkts[0].notes

        # Step 9: Verify Kitt brief shows Pulse separately
        from workspace.quant.kitt.brief_producer import produce_brief
        brief = produce_brief(clean_root)
        assert "PULSE (discretionary)" in brief.notes
        assert "FEEDBACK LOOPS" in brief.notes
