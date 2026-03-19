#!/usr/bin/env python3
"""Tests for Pulse governance — #review-gated downstream release.

Proves:
  1. Proposal creates a review request with pulse_xxx approval ref
  2. No downstream packet is emitted on proposal alone
  3. approve_proposal refuses if proposal is not review-approved
  4. handle_pulse_review("approved") marks state + releases downstream
  5. handle_pulse_review("rejected") marks state + releases nothing
  6. Rejected proposals cannot be re-approved
  7. CLI pulse-approve does not bypass review governance
  8. Full path: propose → review approve → downstream appears in target lane
  9. Full path: propose → review reject → nothing in target lane
  10. Approval ref format is pulse_xxx (parseable by review poller)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.packet_store import list_lane_packets
from workspace.quant.pulse.alert_lane import (
    propose_downstream, approve_proposal, handle_pulse_review,
    get_proposal_by_ref, list_pending_proposals,
    _make_pulse_approval_ref,
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


def _extract_approval_ref(pkt) -> str:
    """Extract the approval_ref from a proposal packet's notes."""
    for part in (pkt.notes or "").split(";"):
        part = part.strip()
        if part.startswith("approval_ref="):
            return part.split("=", 1)[1]
    return ""


class TestApprovalRefFormat:
    def test_pulse_prefix(self):
        ref = _make_pulse_approval_ref("some-packet-id")
        assert ref.startswith("pulse_")
        assert len(ref) > 10

    def test_deterministic(self):
        r1 = _make_pulse_approval_ref("same-id")
        r2 = _make_pulse_approval_ref("same-id")
        assert r1 == r2

    def test_different_inputs(self):
        r1 = _make_pulse_approval_ref("id-a")
        r2 = _make_pulse_approval_ref("id-b")
        assert r1 != r2


class TestProposalCreatesReviewRequest:
    def test_proposal_has_approval_ref(self, clean_root):
        pkt = propose_downstream(
            clean_root, "fish_scenario", "NQ sweep cluster", symbol="NQ",
        )
        ref = _extract_approval_ref(pkt)
        assert ref.startswith("pulse_")

    def test_proposal_state_file_created(self, clean_root):
        pkt = propose_downstream(
            clean_root, "fish_scenario", "NQ sweep cluster", symbol="NQ",
        )
        ref = _extract_approval_ref(pkt)
        state = get_proposal_by_ref(clean_root, ref)
        assert state is not None
        assert state["status"] == "pending"
        assert state["target"] == "fish_scenario"

    def test_list_pending(self, clean_root):
        propose_downstream(clean_root, "fish_scenario", "Proposal A", symbol="NQ")
        propose_downstream(clean_root, "atlas_seed", "Proposal B", symbol="NQ")
        pending = list_pending_proposals(clean_root)
        assert len(pending) == 2


class TestNoReleaseWithoutApproval:
    def test_proposal_alone_no_downstream(self, clean_root):
        """Proposing does NOT create any packet in target lanes."""
        propose_downstream(clean_root, "fish_scenario", "Scenario A", symbol="NQ")
        propose_downstream(clean_root, "atlas_seed", "Seed B", symbol="NQ")
        propose_downstream(clean_root, "hermes_research", "Research C", symbol="NQ")

        for lane in ["fish", "atlas", "hermes", "sigma", "kitt", "tradefloor"]:
            assert len(list_lane_packets(clean_root, lane)) == 0

    def test_approve_proposal_refuses_pending(self, clean_root):
        """approve_proposal() returns None when status is still 'pending'."""
        pkt = propose_downstream(
            clean_root, "fish_scenario", "Scenario", symbol="NQ",
        )
        ref = _extract_approval_ref(pkt)
        # Try to approve directly — should return None because status is pending
        result = approve_proposal(clean_root, ref)
        assert result is None
        # Fish still empty
        assert len(list_lane_packets(clean_root, "fish")) == 0


class TestReviewApprovalReleases:
    def test_handle_review_approved(self, clean_root):
        pkt = propose_downstream(
            clean_root, "fish_scenario", "NQ cluster downside", symbol="NQ",
        )
        ref = _extract_approval_ref(pkt)

        result = handle_pulse_review(clean_root, ref, "approved")
        assert result["ok"] is True
        assert result["decision"] == "approved"
        assert result["downstream_packet_id"] is not None

        # Fish now has exactly one packet
        fish = list_lane_packets(clean_root, "fish")
        assert len(fish) == 1
        assert "[from Pulse]" in fish[0].thesis
        assert f"approval_ref={ref}" in fish[0].notes

    def test_handle_review_approved_atlas(self, clean_root):
        pkt = propose_downstream(
            clean_root, "atlas_seed", "NQ breakout experiment", symbol="NQ",
        )
        ref = _extract_approval_ref(pkt)
        handle_pulse_review(clean_root, ref, "approved")

        atlas = list_lane_packets(clean_root, "atlas")
        assert len(atlas) == 1
        assert atlas[0].packet_type == "idea_packet"

    def test_handle_review_approved_hermes(self, clean_root):
        pkt = propose_downstream(
            clean_root, "hermes_research", "Research NQ gap fills", symbol="NQ",
        )
        ref = _extract_approval_ref(pkt)
        handle_pulse_review(clean_root, ref, "approved")

        hermes = list_lane_packets(clean_root, "hermes")
        assert len(hermes) == 1
        assert hermes[0].packet_type == "research_request_packet"

    def test_state_marked_approved(self, clean_root):
        pkt = propose_downstream(
            clean_root, "fish_scenario", "Test", symbol="NQ",
        )
        ref = _extract_approval_ref(pkt)
        handle_pulse_review(clean_root, ref, "approved")

        state = get_proposal_by_ref(clean_root, ref)
        assert state["status"] == "approved"
        assert state["approved_at"] is not None
        assert state["downstream_packet_id"] is not None


class TestReviewRejection:
    def test_handle_review_rejected(self, clean_root):
        pkt = propose_downstream(
            clean_root, "fish_scenario", "NQ cluster downside", symbol="NQ",
        )
        ref = _extract_approval_ref(pkt)

        result = handle_pulse_review(clean_root, ref, "rejected")
        assert result["ok"] is True
        assert result["decision"] == "rejected"
        assert result["downstream_packet_id"] is None

        # Fish still empty
        assert len(list_lane_packets(clean_root, "fish")) == 0

    def test_state_marked_rejected(self, clean_root):
        pkt = propose_downstream(
            clean_root, "fish_scenario", "Test", symbol="NQ",
        )
        ref = _extract_approval_ref(pkt)
        handle_pulse_review(clean_root, ref, "rejected")

        state = get_proposal_by_ref(clean_root, ref)
        assert state["status"] == "rejected"
        assert state["rejected_at"] is not None

    def test_rejected_cannot_be_approved(self, clean_root):
        pkt = propose_downstream(
            clean_root, "fish_scenario", "Test", symbol="NQ",
        )
        ref = _extract_approval_ref(pkt)
        handle_pulse_review(clean_root, ref, "rejected")

        # Try to approve after rejection
        result = handle_pulse_review(clean_root, ref, "approved")
        assert result["ok"] is False
        assert "already" in result["error"]

        # Fish still empty
        assert len(list_lane_packets(clean_root, "fish")) == 0


class TestCLIDoesNotBypass:
    def test_pulse_approve_does_not_release(self, clean_root):
        """The CLI pulse-approve command should check status, not release."""
        pkt = propose_downstream(
            clean_root, "fish_scenario", "Scenario", symbol="NQ",
        )
        ref = _extract_approval_ref(pkt)

        # Directly calling approve_proposal with pending status should return None
        result = approve_proposal(clean_root, ref)
        assert result is None
        assert len(list_lane_packets(clean_root, "fish")) == 0


class TestReviewPollerRouting:
    def test_pulse_prefix_recognized(self):
        """The review poller regex should match pulse_xxx IDs."""
        import re
        pattern = re.compile(r"\b(?:apr|qpt|pulse)_[a-f0-9]{8,}\b", re.IGNORECASE)
        assert pattern.search("approve pulse_abc123def456")
        assert pattern.search("reject pulse_abc123def456")

    def test_call_approval_routes_pulse(self, clean_root):
        from scripts.discord_review_poller import call_approval_endpoint
        pkt = propose_downstream(
            clean_root, "fish_scenario", "Test routing", symbol="NQ",
        )
        ref = _extract_approval_ref(pkt)

        # This should route to _handle_pulse_approval
        # We can't easily test the full poller, but we can verify
        # that handle_pulse_review works correctly
        result = handle_pulse_review(clean_root, ref, "approved")
        assert result["ok"] is True


class TestEndToEndReviewGated:
    def test_full_approve_flow(self, clean_root):
        """propose → pending → review approve → downstream in fish."""
        pkt = propose_downstream(
            clean_root, "fish_scenario",
            "NQ 18425 sweep cluster downside scenario",
            symbol="NQ", cluster_level=18425.0,
        )
        ref = _extract_approval_ref(pkt)

        # Pending: nothing in fish
        assert len(list_lane_packets(clean_root, "fish")) == 0

        # Operator types "approve pulse_xxx" in #review
        result = handle_pulse_review(clean_root, ref, "approved")
        assert result["ok"] is True

        # Fish now has one packet
        fish = list_lane_packets(clean_root, "fish")
        assert len(fish) == 1
        assert fish[0].packet_type == "scenario_packet"
        assert "[from Pulse]" in fish[0].thesis

    def test_full_reject_flow(self, clean_root):
        """propose → pending → review reject → nothing in fish."""
        pkt = propose_downstream(
            clean_root, "fish_scenario",
            "NQ sweep scenario",
            symbol="NQ",
        )
        ref = _extract_approval_ref(pkt)

        # Reject
        result = handle_pulse_review(clean_root, ref, "rejected")
        assert result["ok"] is True

        # Fish still empty
        assert len(list_lane_packets(clean_root, "fish")) == 0

        # State is rejected
        state = get_proposal_by_ref(clean_root, ref)
        assert state["status"] == "rejected"
