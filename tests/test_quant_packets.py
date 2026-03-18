#!/usr/bin/env python3
"""Tests for quant lane packet contracts."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import (
    make_packet, validate_packet, save_packet, load_packet,
    QuantPacket, CANONICAL_PACKET_TYPES, LANE_NAMES,
)


def test_make_packet_basic():
    p = make_packet("research_packet", "hermes", "test thesis")
    assert p.packet_type == "research_packet"
    assert p.lane == "hermes"
    assert p.thesis == "test thesis"
    assert p.packet_id.startswith("hermes-")
    assert p.created_at


def test_make_packet_rejects_unknown_type():
    with pytest.raises(ValueError, match="Unknown packet_type"):
        make_packet("bogus_packet", "hermes", "test")


def test_make_packet_rejects_unknown_lane():
    with pytest.raises(ValueError, match="Unknown lane"):
        make_packet("research_packet", "bogus_lane", "test")


def test_validate_core_fields():
    p = QuantPacket()  # empty
    errors = validate_packet(p)
    assert "packet_id is required" in errors
    assert "packet_type is required" in errors
    assert "lane is required" in errors
    assert "created_at is required" in errors
    assert "thesis is required" in errors


def test_validate_strategy_rejection():
    p = make_packet("strategy_rejection_packet", "sigma", "rejected",
                    strategy_id="test-001",
                    rejection_reason="curve_fit",
                    rejection_detail="Overfitted to in-sample")
    assert validate_packet(p) == []


def test_validate_strategy_rejection_missing_fields():
    p = make_packet("strategy_rejection_packet", "sigma", "rejected")
    errors = validate_packet(p)
    assert any("rejection_reason" in e for e in errors)
    assert any("strategy_id" in e for e in errors)


def test_validate_execution_packet_requires_approval():
    p = make_packet("execution_intent_packet", "executor", "intent",
                    strategy_id="test-001", execution_mode="paper")
    errors = validate_packet(p)
    assert any("approval_ref" in e for e in errors)


def test_validate_execution_packet_passes():
    p = make_packet("execution_intent_packet", "executor", "intent",
                    strategy_id="test-001", execution_mode="paper",
                    approval_ref="approval-2026-03-18-001")
    assert validate_packet(p) == []


def test_packet_serialization(tmp_path):
    p = make_packet("research_packet", "hermes", "test thesis", confidence=0.7)
    path = save_packet(p, tmp_path)
    loaded = load_packet(path)
    assert loaded.packet_id == p.packet_id
    assert loaded.confidence == 0.7


def test_packet_to_dict_drops_none():
    p = make_packet("research_packet", "hermes", "test")
    d = p.to_dict()
    assert "rejection_reason" not in d
    assert "execution_mode" not in d


def test_all_canonical_types_present():
    assert len(CANONICAL_PACKET_TYPES) >= 30
    assert "research_packet" in CANONICAL_PACKET_TYPES
    assert "brief_packet" in CANONICAL_PACKET_TYPES
    assert "health_summary" in CANONICAL_PACKET_TYPES


def test_paper_review_iterate_requires_guidance():
    p = make_packet("paper_review_packet", "sigma", "review",
                    strategy_id="test-001", outcome="iterate")
    errors = validate_packet(p)
    assert any("iteration_guidance" in e for e in errors)
