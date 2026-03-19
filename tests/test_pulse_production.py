#!/usr/bin/env python3
"""Tests for Pulse production seams: Discord routing, CLI, webhook normalization,
review-gated downstream release, no-leak behavior.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet, validate_packet
from workspace.quant.shared.packet_store import store_packet, list_lane_packets


@pytest.fixture
def clean_root(tmp_path):
    (tmp_path / "workspace" / "quant" / "shared" / "latest").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "registries").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "config").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "scheduler").mkdir(parents=True)
    for lane in ["atlas", "fish", "hermes", "sigma", "kitt", "tradefloor", "executor", "pulse"]:
        (tmp_path / "workspace" / "quant" / lane).mkdir(parents=True)
    return tmp_path


# ---- Discord routing ----

class TestPulseDiscordRouting:
    def test_pulse_event_mapping_exists(self):
        from workspace.quant.shared.discord_bridge import _PACKET_TO_EVENT_KIND
        assert "pulse_alert_packet" in _PACKET_TO_EVENT_KIND
        assert "pulse_cluster_packet" in _PACKET_TO_EVENT_KIND
        assert "pulse_review_proposal_packet" in _PACKET_TO_EVENT_KIND
        assert "pulse_learning_packet" in _PACKET_TO_EVENT_KIND

    def test_pulse_lane_routing(self):
        from workspace.quant.shared.discord_bridge import _LANE_TO_AGENT_ID
        assert _LANE_TO_AGENT_ID.get("pulse") == "pulse"

    def test_pulse_in_delivery_health(self):
        from workspace.quant.shared.discord_bridge import _QUANT_DELIVERY_CHANNELS
        assert "pulse" in _QUANT_DELIVERY_CHANNELS
        assert _QUANT_DELIVERY_CHANNELS["pulse"] == "JARVIS_DISCORD_WEBHOOK_PULSE"

    def test_delivery_health_reports_pulse_missing(self):
        from workspace.quant.shared.discord_bridge import check_delivery_health
        health = check_delivery_health()
        # Pulse webhook isn't set, so it should be missing
        assert "pulse" in health

    def test_pulse_emoji_registered(self):
        from runtime.core.discord_event_router import _EMOJI
        assert "quant_pulse_alert" in _EMOJI
        assert "quant_pulse_proposal" in _EMOJI


# ---- Webhook normalization ----

class TestWebhookNormalization:
    def test_plain_level(self):
        from scripts.pulse_webhook import normalize_tv_payload
        r = normalize_tv_payload(b"18450")
        assert r["text"] == "18450"
        assert r["symbol"] == "NQ"

    def test_level_with_note(self):
        from scripts.pulse_webhook import normalize_tv_payload
        r = normalize_tv_payload(b"18450 liquidity sweep")
        assert "18450" in r["text"]
        assert "liquidity" in r["text"]

    def test_json_payload(self):
        from scripts.pulse_webhook import normalize_tv_payload
        payload = json.dumps({"level": 18450, "note": "sweep", "symbol": "NQ"}).encode()
        r = normalize_tv_payload(payload)
        assert r["level"] == 18450
        assert r["symbol"] == "NQ"
        assert "sweep" in r["text"]

    def test_json_with_text_field(self):
        from scripts.pulse_webhook import normalize_tv_payload
        payload = json.dumps({"text": "NQ reclaim at 18500", "direction": "bullish"}).encode()
        r = normalize_tv_payload(payload)
        assert "reclaim" in r["text"]
        assert r["direction"] == "bullish"

    def test_json_with_ticker(self):
        from scripts.pulse_webhook import normalize_tv_payload
        payload = json.dumps({"ticker": "ES", "price": 5500}).encode()
        r = normalize_tv_payload(payload)
        assert r["symbol"] == "ES"
        assert r["level"] == 5500

    def test_empty_payload(self):
        from scripts.pulse_webhook import normalize_tv_payload
        r = normalize_tv_payload(b"")
        assert r["text"] == ""
        assert r["symbol"] == "NQ"

    def test_malformed_json_falls_back_to_text(self):
        from scripts.pulse_webhook import normalize_tv_payload
        r = normalize_tv_payload(b"{bad json")
        assert "{bad json" in r["text"]


# ---- Review-gated downstream ----

class TestReviewGatedDownstream:
    def test_proposal_emits_review_level_escalation(self, clean_root):
        from workspace.quant.pulse.alert_lane import propose_downstream
        pkt = propose_downstream(
            clean_root, "fish_scenario", "NQ cluster downside", symbol="NQ",
        )
        assert pkt.escalation_level == "operator_review"
        assert "target=fish_scenario" in pkt.notes
        assert "status=pending" in pkt.notes

    def test_unapproved_proposal_no_leak(self, clean_root):
        from workspace.quant.pulse.alert_lane import propose_downstream
        propose_downstream(clean_root, "fish_scenario", "Scenario A", symbol="NQ")
        propose_downstream(clean_root, "atlas_seed", "Seed B", symbol="NQ")
        propose_downstream(clean_root, "hermes_research", "Research C", symbol="NQ")

        for lane in ["fish", "atlas", "hermes", "sigma", "kitt", "tradefloor"]:
            assert len(list_lane_packets(clean_root, lane)) == 0

    def test_approved_proposal_releases(self, clean_root):
        from workspace.quant.pulse.alert_lane import propose_downstream, approve_proposal
        proposal = propose_downstream(
            clean_root, "fish_scenario", "NQ downside", symbol="NQ",
        )
        downstream = approve_proposal(clean_root, proposal.packet_id)
        assert downstream is not None
        assert downstream.lane == "fish"
        assert len(list_lane_packets(clean_root, "fish")) == 1

    def test_approve_nonexistent_returns_none(self, clean_root):
        from workspace.quant.pulse.alert_lane import approve_proposal
        assert approve_proposal(clean_root, "nonexistent-id") is None


# ---- End-to-end: webhook → ingest → proposal → approval → downstream ----

class TestEndToEndWebhookToDownstream:
    def test_full_flow(self, clean_root):
        from scripts.pulse_webhook import normalize_tv_payload
        from workspace.quant.pulse.alert_lane import (
            ingest_alert, propose_downstream, approve_proposal,
        )

        # Step 1: TV webhook payload arrives
        payload = json.dumps({"level": 18450, "note": "liquidity sweep", "symbol": "NQ"}).encode()
        kwargs = normalize_tv_payload(payload)
        assert kwargs["level"] == 18450

        # Step 2: Ingest
        pkt, parsed = ingest_alert(
            clean_root, text=kwargs["text"], symbol=kwargs["symbol"],
            level=kwargs["level"], source="tradingview",
        )
        assert pkt.lane == "pulse"
        assert validate_packet(pkt) == []

        # Step 3: Propose downstream
        proposal = propose_downstream(
            clean_root, "fish_scenario",
            f"NQ sweep cluster at {parsed['level']}",
            symbol="NQ", cluster_level=parsed["level"],
            evidence_refs=[pkt.packet_id],
        )
        assert proposal is not None

        # Step 4: Verify nothing leaked
        assert len(list_lane_packets(clean_root, "fish")) == 0

        # Step 5: Approve
        downstream = approve_proposal(clean_root, proposal.packet_id)
        assert downstream.lane == "fish"
        assert "[from Pulse]" in downstream.thesis

        # Step 6: Verify fish now has exactly one packet
        assert len(list_lane_packets(clean_root, "fish")) == 1


# ---- Kitt visibility ----

class TestKittPulseVisibility:
    def test_kitt_brief_pulse_section_present(self, clean_root):
        from workspace.quant.pulse.alert_lane import ingest_alert
        from workspace.quant.kitt.brief_producer import produce_brief

        ingest_alert(clean_root, "18450 liquidity sweep")
        brief = produce_brief(clean_root)
        notes = brief.notes or ""
        assert "PULSE (discretionary)" in notes
        assert "FEEDBACK LOOPS" in notes  # Core section still separate


# ---- Outbox sender mapping ----

class TestOutboxSenderMapping:
    def test_pulse_channel_mapped_in_sender(self):
        from runtime.core.discord_outbox_sender import CHANNEL_WEBHOOK_ENV
        pulse_ch = "1484088366155698176"
        assert pulse_ch in CHANNEL_WEBHOOK_ENV
        assert CHANNEL_WEBHOOK_ENV[pulse_ch] == "JARVIS_DISCORD_WEBHOOK_PULSE"

    def test_pulse_channel_not_null_in_config(self):
        import json
        from pathlib import Path
        config_path = Path(__file__).resolve().parents[1] / "config" / "agent_channel_map.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        pulse = data["agents"]["pulse"]
        assert pulse["channel_id"] is not None
        assert pulse["channel_id"] == "1484088366155698176"


# ---- Discord emission on ingest ----

class TestDiscordEmissionOnIngest:
    def test_ingest_creates_outbox_entry(self, clean_root):
        """Ingesting an alert should attempt Discord emission (outbox entry)."""
        from workspace.quant.pulse.alert_lane import ingest_alert

        # Set up state/discord_outbox so emit_event can write
        (clean_root / "state" / "discord_outbox").mkdir(parents=True, exist_ok=True)
        (clean_root / "state" / "dispatch_events").mkdir(parents=True, exist_ok=True)
        # Need agent_channel_map for routing
        import json, shutil
        src = Path(__file__).resolve().parents[1] / "config" / "agent_channel_map.json"
        dst = clean_root / "config" / "agent_channel_map.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

        pkt, parsed = ingest_alert(clean_root, "18450 liquidity sweep")

        # Check that a dispatch event was created
        dispatch_dir = clean_root / "state" / "dispatch_events"
        dispatch_files = list(dispatch_dir.glob("*.json"))
        assert len(dispatch_files) >= 1

        # Verify the dispatch event is for pulse
        found_pulse = False
        for f in dispatch_files:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("kind") == "quant_pulse_alert":
                found_pulse = True
                break
        assert found_pulse, "No dispatch event with kind=quant_pulse_alert found"


# ---- Approval path isolation ----

class TestApprovalPathIsolation:
    def test_pulse_approve_only_path(self, clean_root):
        """Verify approve_proposal is the ONLY path from Pulse to other lanes."""
        from workspace.quant.pulse.alert_lane import (
            ingest_alert, cluster_alerts, propose_downstream, approve_proposal,
            record_outcome, build_learning_state,
        )

        # Full lifecycle without approval
        a1, _ = ingest_alert(clean_root, "18450 liquidity sweep")
        a2, _ = ingest_alert(clean_root, "18455 sweep again")
        cluster_alerts(clean_root)
        record_outcome(clean_root, a1.packet_id, hit=True)
        build_learning_state(clean_root)
        propose_downstream(clean_root, "fish_scenario", "Scenario from cluster", symbol="NQ")
        propose_downstream(clean_root, "atlas_seed", "Seed from cluster", symbol="NQ")

        # Nothing in any other lane
        for lane in ["fish", "atlas", "hermes", "sigma", "kitt", "tradefloor"]:
            assert len(list_lane_packets(clean_root, lane)) == 0, f"Leaked to {lane}"

        # Now approve one — only that target gets a packet
        proposals = list_lane_packets(clean_root, "pulse", "pulse_review_proposal_packet")
        fish_proposal = [p for p in proposals if "fish_scenario" in (p.notes or "")][0]
        downstream = approve_proposal(clean_root, fish_proposal.packet_id)
        assert downstream.lane == "fish"
        assert len(list_lane_packets(clean_root, "fish")) == 1
        # Atlas still empty (that proposal wasn't approved)
        assert len(list_lane_packets(clean_root, "atlas")) == 0
