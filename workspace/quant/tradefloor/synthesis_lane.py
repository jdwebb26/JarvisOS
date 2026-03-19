#!/usr/bin/env python3
"""Quant Lanes — TradeFloor Synthesis.

Per spec §6: invoked synthesis workflow. Routes through Kitt.

TradeFloor is a premium signal, not a chatbot. Sparse from day one.
Max once per 6 hours unless operator/Kitt override with logged justification.

Input: latest from each lane + strategy registry + approval registry snapshot.
Output: tradefloor_packet with agreement tier (0-4), routed to Kitt.

TradeFloor reads confidence from each lane's latest packet and uses them
to weight synthesis. TradeFloor does not invent its own confidence.

Host placement: strongest available primary, cloud overflow (spec §2).
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
from workspace.quant.shared.scheduler.scheduler import heavy_job_slot, check_capacity

LANE = "tradefloor"
CONFIDENCE_THRESHOLD = 0.6
CADENCE_SECONDS = 6 * 3600  # 6 hours


class CadenceRefused(Exception):
    """Raised when TradeFloor is invoked too soon without override."""
    pass


def _cadence_state_path(root: Path) -> Path:
    d = root / "workspace" / "quant" / "shared" / "scheduler"
    d.mkdir(parents=True, exist_ok=True)
    return d / "tradefloor_cadence.json"


def _load_cadence_state(root: Path) -> dict:
    path = _cadence_state_path(root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return {}


def _save_cadence_state(root: Path, state: dict):
    path = _cadence_state_path(root)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def check_cadence(root: Path) -> tuple[bool, float]:
    """Check if TradeFloor can run (6h since last invocation).

    Returns (can_run, seconds_remaining).
    """
    state = _load_cadence_state(root)
    last_run = state.get("last_run_at")
    if not last_run:
        return True, 0.0

    try:
        last_dt = datetime.fromisoformat(last_run)
    except (ValueError, TypeError):
        return True, 0.0

    now = datetime.now(timezone.utc)
    elapsed = (now - last_dt).total_seconds()
    remaining = max(0.0, CADENCE_SECONDS - elapsed)
    return remaining <= 0, remaining


def _record_invocation(root: Path, override_reason: Optional[str] = None):
    """Record that TradeFloor was invoked."""
    state = _load_cadence_state(root)
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    state["last_override_reason"] = override_reason
    _save_cadence_state(root, state)


def _extract_lane_positions(latest: dict[str, QuantPacket]) -> dict[str, dict]:
    """Extract each lane's current position/thesis from latest packets."""
    positions: dict[str, dict] = {}

    for key, pkt in latest.items():
        lane = pkt.lane
        if lane in positions:
            if pkt.priority in ("critical", "high") and positions[lane].get("priority") not in ("critical", "high"):
                pass
            else:
                continue

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
    directions: dict[str, list[str]] = {}
    for lane, pos in positions.items():
        d = pos["direction"]
        directions.setdefault(d, []).append(lane)
    return directions


def _build_disagreement_matrix(positions: dict[str, dict]) -> dict:
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
    """Determine agreement tier per spec §8 (0-4)."""
    if len(positions) < 2:
        return 0, "Insufficient lane data for agreement assessment"

    largest_group = []
    largest_direction = "neutral"
    for direction, lanes in agreement_matrix.items():
        if direction != "neutral" and len(lanes) > len(largest_group):
            largest_group = lanes
            largest_direction = direction

    has_objections = len(disagreement_matrix) > 0

    kitt_aligned = "kitt" in largest_group
    sigma_aligned = "sigma" in largest_group
    atlas_aligned = "atlas" in largest_group
    fish_aligned = "fish" in largest_group
    supporting_lane = atlas_aligned or fish_aligned

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
    """Run TradeFloor synthesis with cadence enforcement and scheduler awareness.

    Raises CadenceRefused if invoked within 6h of last run and no override_reason.

    concrete_action: if provided, enables Tier 4 (actionable) assessment
    override_reason: if provided, overrides the 6h cap (must be logged)
    """
    # Cadence enforcement
    can_run, remaining = check_cadence(root)
    if not can_run and not override_reason:
        raise CadenceRefused(
            f"TradeFloor invoked too soon. {remaining:.0f}s remaining until next allowed run. "
            f"Provide override_reason to bypass."
        )

    # Scheduler check — TradeFloor is synthesis-heavy
    with heavy_job_slot(root, LANE) as slot:
        if not slot.acquired:
            # Still emit a degraded packet rather than silently failing
            pkt = make_packet(
                "tradefloor_packet", "tradefloor",
                f"TradeFloor synthesis deferred: scheduler capacity ({slot.wait_reason})",
                priority="low",
                agreement_tier=0,
                agreement_tier_reasoning=f"Deferred due to scheduler: {slot.wait_reason}",
                agreement_matrix={},
                disagreement_matrix={},
                confidence_weighted_synthesis="Deferred",
                pipeline_snapshot=_pipeline_snapshot(root),
                next_actions=[],
                deferred_questions=[],
                operator_recommendation="skip",
                operator_recommendation_reasoning="Synthesis deferred due to host pressure",
                degraded=True,
                escalation_level="none",
            )
            store_packet(root, pkt)
            return pkt

        # Record invocation (inside slot so we only record if we actually run)
        _record_invocation(root, override_reason)

        latest = get_all_latest(root)
        positions = _extract_lane_positions(latest)
        agreement_matrix = _build_agreement_matrix(positions)
        disagreement_matrix = _build_disagreement_matrix(positions)

        has_action = concrete_action is not None
        tier, tier_reasoning = _determine_agreement_tier(
            positions, agreement_matrix, disagreement_matrix, has_action,
        )

        # Confidence-weighted synthesis
        weighted_theses = []
        for lane, pos in positions.items():
            conf = pos["confidence"]
            weighted_theses.append(f"[{lane} c={conf:.2f}] {pos['thesis'][:80]}")
        synthesis_text = " | ".join(weighted_theses) if weighted_theses else "No lane data"

        pipeline = _pipeline_snapshot(root)

        next_actions = []
        if tier >= 3 and concrete_action:
            next_actions.append({"action": concrete_action, "assigned_lane": "kitt"})
        if any(s == "PROMOTED" for s in pipeline.get("by_state", {}).keys()):
            next_actions.append({"action": "Review promoted strategies for paper trade", "assigned_lane": "kitt"})

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
            notes=f"host={slot.host}" + (f"; override={override_reason}" if override_reason else ""),
        )
        store_packet(root, pkt)
        return pkt
