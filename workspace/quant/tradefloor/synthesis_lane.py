#!/usr/bin/env python3
"""Quant Lanes — TradeFloor Synthesis.

Per spec §6: invoked synthesis workflow. Routes through Kitt.

TradeFloor is a premium signal, not a chatbot. Sparse from day one.
Max once per 6 hours unless operator/Kitt override.

Input: latest from each lane + strategy registry + approval registry snapshot.
Output: tradefloor_packet with agreement tier (0-4), routed to Kitt.

TradeFloor reads confidence from each lane's latest packet and uses them
to weight synthesis. TradeFloor does not invent its own confidence.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import make_packet, QuantPacket
from workspace.quant.shared.packet_store import store_packet, get_latest, get_all_latest
from workspace.quant.shared.registries.strategy_registry import load_all_strategies


# Agreement tier thresholds per spec §8
CONFIDENCE_THRESHOLD = 0.6


def _extract_lane_positions(latest: dict[str, QuantPacket]) -> dict[str, dict]:
    """Extract each lane's current position/thesis from latest packets.

    Returns {lane: {thesis, confidence, direction, packet_id}}.
    """
    positions: dict[str, dict] = {}

    for key, pkt in latest.items():
        lane = pkt.lane
        if lane in positions:
            # Keep highest-priority packet per lane
            if pkt.priority in ("critical", "high") and positions[lane].get("priority") not in ("critical", "high"):
                pass  # will overwrite below
            else:
                continue

        # Infer direction from thesis keywords
        thesis_lower = pkt.thesis.lower()
        direction = "neutral"
        if any(w in thesis_lower for w in ("bullish", "long", "breakout", "upside")):
            direction = "bullish"
        elif any(w in thesis_lower for w in ("bearish", "short", "breakdown", "downside")):
            direction = "bearish"

        positions[lane] = {
            "thesis": pkt.thesis,
            "confidence": pkt.confidence or 0.5,
            "direction": direction,
            "packet_id": pkt.packet_id,
            "packet_type": pkt.packet_type,
            "priority": pkt.priority,
        }

    return positions


def _build_agreement_matrix(positions: dict[str, dict]) -> dict:
    """Build agreement matrix: which lanes align on direction."""
    directions: dict[str, list[str]] = {}
    for lane, pos in positions.items():
        d = pos["direction"]
        directions.setdefault(d, []).append(lane)
    return directions


def _build_disagreement_matrix(positions: dict[str, dict]) -> dict:
    """Build disagreement matrix: where lanes diverge."""
    disagreements = {}
    lanes = list(positions.keys())
    for i, lane_a in enumerate(lanes):
        for lane_b in lanes[i+1:]:
            dir_a = positions[lane_a]["direction"]
            dir_b = positions[lane_b]["direction"]
            if dir_a != dir_b and dir_a != "neutral" and dir_b != "neutral":
                key = f"{lane_a}_vs_{lane_b}"
                disagreements[key] = {
                    lane_a: {"direction": dir_a, "confidence": positions[lane_a]["confidence"]},
                    lane_b: {"direction": dir_b, "confidence": positions[lane_b]["confidence"]},
                }
    return disagreements


def _determine_agreement_tier(
    positions: dict[str, dict],
    agreement_matrix: dict,
    disagreement_matrix: dict,
    has_concrete_action: bool = False,
) -> tuple[int, str]:
    """Determine agreement tier per spec §8.

    Tier 0: No agreement — lanes diverge or insufficient data
    Tier 1: Weak — 2+ lanes align, no strong objection
    Tier 2: Strong — kitt + sigma align, plus atlas or fish
    Tier 3: High-conviction — kitt + sigma + atlas/fish, all confidence > threshold
    Tier 4: Actionable — high-conviction + concrete recommended action
    """
    if len(positions) < 2:
        return 0, "Insufficient lane data for agreement assessment"

    # Find largest alignment group
    largest_group = []
    largest_direction = "neutral"
    for direction, lanes in agreement_matrix.items():
        if direction != "neutral" and len(lanes) > len(largest_group):
            largest_group = lanes
            largest_direction = direction

    # Check for active objections
    has_objections = len(disagreement_matrix) > 0

    # Tier checks (highest first)
    kitt_aligned = "kitt" in largest_group
    sigma_aligned = "sigma" in largest_group
    atlas_aligned = "atlas" in largest_group
    fish_aligned = "fish" in largest_group
    supporting_lane = atlas_aligned or fish_aligned

    # Check confidence threshold
    all_above_threshold = all(
        positions[lane]["confidence"] >= CONFIDENCE_THRESHOLD
        for lane in largest_group
        if lane in positions
    )

    if kitt_aligned and sigma_aligned and supporting_lane and all_above_threshold:
        if has_concrete_action:
            return 4, f"Actionable: kitt + sigma + {'atlas' if atlas_aligned else 'fish'} align {largest_direction} with concrete action, all confidence >= {CONFIDENCE_THRESHOLD}"
        return 3, f"High-conviction: kitt + sigma + {'atlas' if atlas_aligned else 'fish'} align {largest_direction}, all confidence >= {CONFIDENCE_THRESHOLD}"

    if kitt_aligned and sigma_aligned and supporting_lane:
        return 2, f"Strong: kitt + sigma + {'atlas' if atlas_aligned else 'fish'} align {largest_direction}"

    if len(largest_group) >= 2 and not has_objections:
        return 1, f"Weak: {', '.join(largest_group)} align {largest_direction}"

    if len(largest_group) >= 2:
        return 1, f"Weak: {', '.join(largest_group)} align {largest_direction} (with some disagreement)"

    return 0, "No meaningful agreement across lanes"


def _pipeline_snapshot(root: Path) -> dict:
    """Build pipeline snapshot from strategy registry."""
    strategies = load_all_strategies(root)
    by_state: dict[str, int] = {}
    for s in strategies.values():
        by_state[s.lifecycle_state] = by_state.get(s.lifecycle_state, 0) + 1
    return {
        "total_strategies": len(strategies),
        "by_state": by_state,
    }


def synthesize(
    root: Path,
    concrete_action: Optional[str] = None,
    override_reason: Optional[str] = None,
) -> QuantPacket:
    """Run TradeFloor synthesis: read all latest packets, compute agreement, emit tradefloor_packet.

    concrete_action: if provided, enables Tier 4 (actionable) assessment
    override_reason: if provided, logs that the 6h cap was overridden

    Returns the tradefloor_packet.
    """
    latest = get_all_latest(root)
    positions = _extract_lane_positions(latest)
    agreement_matrix = _build_agreement_matrix(positions)
    disagreement_matrix = _build_disagreement_matrix(positions)

    has_action = concrete_action is not None
    tier, tier_reasoning = _determine_agreement_tier(
        positions, agreement_matrix, disagreement_matrix, has_action,
    )

    # Confidence-weighted synthesis
    total_weight = 0.0
    weighted_theses = []
    for lane, pos in positions.items():
        conf = pos["confidence"]
        total_weight += conf
        weighted_theses.append(f"[{lane} c={conf:.2f}] {pos['thesis'][:80]}")
    synthesis_text = " | ".join(weighted_theses) if weighted_theses else "No lane data"

    pipeline = _pipeline_snapshot(root)

    # Next actions
    next_actions = []
    if tier >= 3 and concrete_action:
        next_actions.append({"action": concrete_action, "assigned_lane": "kitt"})
    if any(s == "PROMOTED" for s in pipeline.get("by_state", {}).keys()):
        next_actions.append({"action": "Review promoted strategies for paper trade", "assigned_lane": "kitt"})

    # Operator recommendation
    if tier >= 4:
        op_rec = "notify"
        op_reason = f"Tier 4 actionable agreement: {tier_reasoning}"
    elif tier >= 3:
        op_rec = "notify"
        op_reason = f"Tier 3 high-conviction: {tier_reasoning}"
    elif tier >= 2:
        op_rec = "skip"
        op_reason = f"Tier 2 strong agreement — notable but not actionable"
    else:
        op_rec = "skip"
        op_reason = f"Tier {tier}: {tier_reasoning}"

    # Determine escalation level based on tier
    if tier >= 3:
        escalation = "operator_review"
    elif tier >= 2:
        escalation = "kitt_only"
    else:
        escalation = "team_only"

    thesis = f"TradeFloor synthesis: tier {tier} ({['no agreement', 'weak', 'strong', 'high-conviction', 'actionable'][tier]})"
    if override_reason:
        thesis += f" [override: {override_reason}]"

    pkt = make_packet(
        "tradefloor_packet", "tradefloor",
        thesis,
        priority="high" if tier >= 3 else "medium",
        agreement_tier=tier,
        agreement_tier_reasoning=tier_reasoning,
        agreement_matrix=agreement_matrix,
        disagreement_matrix=disagreement_matrix,
        confidence_weighted_synthesis=synthesis_text,
        pipeline_snapshot=pipeline,
        next_actions=next_actions,
        deferred_questions=[],
        operator_recommendation=op_rec,
        operator_recommendation_reasoning=op_reason,
        degraded=False,
        escalation_level=escalation,
    )
    store_packet(root, pkt)
    return pkt
