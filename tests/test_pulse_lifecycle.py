#!/usr/bin/env python3
"""Tests proving Pulse proposal lifecycle visibility in operator surfaces.

Acceptance criteria:
  1. Operator surfaces reflect pending / approved / rejected states
  2. Downstream release is visible after approval
  3. Rejected proposals remain visible as rejected and never release
  4. Kitt brief shows Pulse lifecycle status cleanly
  5. Governance is preserved: no CLI bypass
  6. list_all_proposals returns all states from state files
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
    ingest_alert, propose_downstream, handle_pulse_review,
    list_pending_proposals, list_all_proposals, get_proposal_by_ref,
    _proposals_state_path,
)


@pytest.fixture
def clean_root(tmp_path):
    """Provide a clean root directory for each test."""
    (tmp_path / "workspace" / "quant" / "shared" / "latest").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "registries").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "config").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "scheduler").mkdir(parents=True)
    for lane in ["atlas", "fish", "hermes", "sigma", "kitt", "tradefloor", "executor", "pulse"]:
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

    return tmp_path


def _make_proposal(root, target="fish_scenario", thesis="NQ test scenario from Pulse"):
    """Helper: create a proposal and return its state dict."""
    pkt = propose_downstream(root, target=target, thesis=thesis, symbol="NQ")
    assert pkt is not None
    # Find the approval_ref from the packet notes
    for part in (pkt.notes or "").split(";"):
        part = part.strip()
        if part.startswith("approval_ref="):
            ref = part.split("=", 1)[1]
            return get_proposal_by_ref(root, ref)
    raise AssertionError("No approval_ref in proposal packet notes")


# ---------------------------------------------------------------------------
# list_all_proposals / list_pending_proposals
# ---------------------------------------------------------------------------

class TestProposalListing:
    def test_empty_returns_empty(self, clean_root):
        assert list_all_proposals(clean_root) == []
        assert list_pending_proposals(clean_root) == []

    def test_new_proposal_is_pending(self, clean_root):
        state = _make_proposal(clean_root)
        assert state["status"] == "pending"
        assert state["approved_at"] is None
        assert state["rejected_at"] is None
        assert state["downstream_packet_id"] is None

        all_p = list_all_proposals(clean_root)
        assert len(all_p) == 1
        assert all_p[0]["status"] == "pending"

        pending = list_pending_proposals(clean_root)
        assert len(pending) == 1

    def test_approved_proposal_in_all_not_pending(self, clean_root):
        state = _make_proposal(clean_root)
        ref = state["approval_ref"]

        result = handle_pulse_review(clean_root, ref, "approved")
        assert result["ok"] is True

        all_p = list_all_proposals(clean_root)
        assert len(all_p) == 1
        assert all_p[0]["status"] == "approved"
        assert all_p[0]["approved_at"] is not None
        assert all_p[0]["downstream_packet_id"] is not None

        pending = list_pending_proposals(clean_root)
        assert len(pending) == 0

    def test_rejected_proposal_in_all_not_pending(self, clean_root):
        state = _make_proposal(clean_root)
        ref = state["approval_ref"]

        result = handle_pulse_review(clean_root, ref, "rejected")
        assert result["ok"] is True

        all_p = list_all_proposals(clean_root)
        assert len(all_p) == 1
        assert all_p[0]["status"] == "rejected"
        assert all_p[0]["rejected_at"] is not None
        assert all_p[0]["downstream_packet_id"] is None

        pending = list_pending_proposals(clean_root)
        assert len(pending) == 0

    def test_mixed_lifecycle_states(self, clean_root):
        """Multiple proposals in different states all visible."""
        s1 = _make_proposal(clean_root, thesis="Proposal A — will be approved")
        s2 = _make_proposal(clean_root, thesis="Proposal B — will be rejected")
        s3 = _make_proposal(clean_root, thesis="Proposal C — stays pending")

        handle_pulse_review(clean_root, s1["approval_ref"], "approved")
        handle_pulse_review(clean_root, s2["approval_ref"], "rejected")

        all_p = list_all_proposals(clean_root)
        assert len(all_p) == 3

        statuses = {p["approval_ref"]: p["status"] for p in all_p}
        assert statuses[s1["approval_ref"]] == "approved"
        assert statuses[s2["approval_ref"]] == "rejected"
        assert statuses[s3["approval_ref"]] == "pending"


# ---------------------------------------------------------------------------
# Downstream release visibility
# ---------------------------------------------------------------------------

class TestDownstreamVisibility:
    def test_approved_creates_downstream_packet(self, clean_root):
        """Approval creates a real downstream packet in the target lane."""
        state = _make_proposal(clean_root, target="fish_scenario",
                               thesis="NQ VWAP bounce scenario from Pulse")
        ref = state["approval_ref"]

        result = handle_pulse_review(clean_root, ref, "approved")
        assert result["ok"]
        ds_id = result["downstream_packet_id"]
        assert ds_id is not None

        # Verify the downstream packet actually exists in Fish lane
        fish_pkts = list_lane_packets(clean_root, "fish", "scenario_packet")
        ds_pkt = [p for p in fish_pkts if p.packet_id == ds_id]
        assert len(ds_pkt) == 1
        assert "[from Pulse]" in ds_pkt[0].thesis
        assert f"approval_ref={ref}" in (ds_pkt[0].notes or "")

    def test_approved_state_records_downstream_id(self, clean_root):
        """Proposal state file records downstream_packet_id after approval."""
        state = _make_proposal(clean_root)
        ref = state["approval_ref"]
        handle_pulse_review(clean_root, ref, "approved")

        updated = get_proposal_by_ref(clean_root, ref)
        assert updated["downstream_packet_id"] is not None
        assert updated["downstream_packet_id"].startswith("fish-")

    def test_hermes_target_creates_research_request(self, clean_root):
        state = _make_proposal(clean_root, target="hermes_research",
                               thesis="Research NQ overnight gap edge")
        handle_pulse_review(clean_root, state["approval_ref"], "approved")
        updated = get_proposal_by_ref(clean_root, state["approval_ref"])
        assert updated["downstream_packet_id"].startswith("hermes-")

    def test_atlas_target_creates_idea_packet(self, clean_root):
        state = _make_proposal(clean_root, target="atlas_seed",
                               thesis="Explore NQ momentum breakout variant")
        handle_pulse_review(clean_root, state["approval_ref"], "approved")
        updated = get_proposal_by_ref(clean_root, state["approval_ref"])
        assert updated["downstream_packet_id"].startswith("atlas-")


# ---------------------------------------------------------------------------
# Rejected proposals never release
# ---------------------------------------------------------------------------

class TestRejectionGovernance:
    def test_rejected_has_no_downstream(self, clean_root):
        state = _make_proposal(clean_root)
        handle_pulse_review(clean_root, state["approval_ref"], "rejected")
        updated = get_proposal_by_ref(clean_root, state["approval_ref"])
        assert updated["status"] == "rejected"
        assert updated["downstream_packet_id"] is None

    def test_rejected_cannot_be_re_approved(self, clean_root):
        """Once rejected, re-approving fails."""
        state = _make_proposal(clean_root)
        handle_pulse_review(clean_root, state["approval_ref"], "rejected")
        result = handle_pulse_review(clean_root, state["approval_ref"], "approved")
        assert result["ok"] is False
        assert "already rejected" in result["error"]

    def test_approved_cannot_be_re_rejected(self, clean_root):
        """Once approved, re-rejecting fails."""
        state = _make_proposal(clean_root)
        handle_pulse_review(clean_root, state["approval_ref"], "approved")
        result = handle_pulse_review(clean_root, state["approval_ref"], "rejected")
        assert result["ok"] is False
        assert "already approved" in result["error"]

    def test_no_downstream_packets_in_target_lane_after_rejection(self, clean_root):
        """Rejected Fish proposal leaves zero scenario_packets from Pulse."""
        state = _make_proposal(clean_root, target="fish_scenario",
                               thesis="Rejected scenario from Pulse")
        handle_pulse_review(clean_root, state["approval_ref"], "rejected")
        fish_pkts = list_lane_packets(clean_root, "fish", "scenario_packet")
        pulse_fish = [p for p in fish_pkts if "[from Pulse]" in p.thesis]
        assert len(pulse_fish) == 0


# ---------------------------------------------------------------------------
# Kitt brief Pulse section
# ---------------------------------------------------------------------------

class TestKittBriefPulseSection:
    def test_brief_shows_pending_proposal(self, clean_root):
        """Kitt brief Pulse section shows pending proposals."""
        from workspace.quant.kitt.brief_producer import _pulse_section
        _make_proposal(clean_root, thesis="NQ scenario from Pulse alert")

        text = _pulse_section(clean_root)
        assert text is not None
        assert "1 pending" in text
        assert "awaiting:" in text

    def test_brief_shows_approved_release(self, clean_root):
        """After approval, brief shows released downstream packet."""
        from workspace.quant.kitt.brief_producer import _pulse_section
        state = _make_proposal(clean_root, thesis="NQ scenario approved")
        handle_pulse_review(clean_root, state["approval_ref"], "approved")

        text = _pulse_section(clean_root)
        assert text is not None
        assert "1 approved" in text
        assert "released:" in text

    def test_brief_shows_rejected(self, clean_root):
        """After rejection, brief shows rejected count."""
        from workspace.quant.kitt.brief_producer import _pulse_section
        state = _make_proposal(clean_root, thesis="NQ scenario rejected")
        handle_pulse_review(clean_root, state["approval_ref"], "rejected")

        text = _pulse_section(clean_root)
        assert text is not None
        assert "1 rejected" in text

    def test_brief_pulse_separate_from_feedback_loops(self, clean_root):
        """Pulse section is separate from FEEDBACK LOOPS in full brief."""
        from workspace.quant.kitt.brief_producer import produce_brief
        # Create some Pulse activity
        ingest_alert(clean_root, text="NQ 18500 liquidity sweep", source="test")
        _make_proposal(clean_root, thesis="NQ sweep scenario")

        brief = produce_brief(clean_root, market_read="Test.")
        notes = brief.notes or ""

        # Pulse section is under its own header, not mixed into FEEDBACK LOOPS
        assert "PULSE (discretionary)" in notes
        feedback_pos = notes.find("FEEDBACK LOOPS")
        pulse_pos = notes.find("PULSE (discretionary)")
        # They should be separate sections
        assert feedback_pos > 0
        assert pulse_pos > 0
        assert abs(feedback_pos - pulse_pos) > 20  # Not interleaved


# ---------------------------------------------------------------------------
# Proposal state file audit trail
# ---------------------------------------------------------------------------

class TestAuditTrail:
    def test_state_file_has_all_fields(self, clean_root):
        """Proposal state file has all required audit fields."""
        state = _make_proposal(clean_root)
        required = [
            "approval_ref", "proposal_packet_id", "target", "thesis",
            "symbol", "confidence", "status", "created_at",
            "approved_at", "rejected_at", "downstream_packet_id",
        ]
        for field in required:
            assert field in state, f"Missing field: {field}"

    def test_state_file_updated_on_approve(self, clean_root):
        """State file records approved_at and downstream_packet_id on approval."""
        state = _make_proposal(clean_root)
        ref = state["approval_ref"]
        handle_pulse_review(clean_root, ref, "approved")
        updated = get_proposal_by_ref(clean_root, ref)
        assert updated["approved_at"] is not None
        assert updated["downstream_packet_id"] is not None
        assert updated["rejected_at"] is None

    def test_state_file_updated_on_reject(self, clean_root):
        """State file records rejected_at on rejection."""
        state = _make_proposal(clean_root)
        ref = state["approval_ref"]
        handle_pulse_review(clean_root, ref, "rejected")
        updated = get_proposal_by_ref(clean_root, ref)
        assert updated["rejected_at"] is not None
        assert updated["approved_at"] is None
        assert updated["downstream_packet_id"] is None

    def test_state_file_persists_on_disk(self, clean_root):
        """State files are real JSON on disk, not in-memory."""
        state = _make_proposal(clean_root)
        ref = state["approval_ref"]

        state_path = _proposals_state_path(clean_root) / f"{ref}.json"
        assert state_path.exists()

        on_disk = json.loads(state_path.read_text(encoding="utf-8"))
        assert on_disk["approval_ref"] == ref
        assert on_disk["status"] == "pending"
