#!/usr/bin/env python3
"""Quant Lanes — TradeFloor Synthesis.

Per spec §6: invoked synthesis workflow. Routes through Kitt.

TradeFloor is a premium signal, not a chatbot. Sparse from day one.
Max once per 6 hours unless operator/Kitt override with logged justification.

Input: latest from each lane + strategy registry + approval registry snapshot.
Output: tradefloor_packet with agreement tier (0-4), routed to Kitt.

TradeFloor reads confidence from each lane's latest packet and uses them
to weight synthesis. TradeFloor does not invent its own confidence.

Per spec §9: Fish confidence is adjusted by calibration track record.

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

# Packet types per lane, in preference order for position extraction.
# TradeFloor picks the first available type per lane.
_LANE_PACKET_PREFERENCE = {
    "fish": ["forecast_packet", "scenario_packet", "regime_packet", "risk_map_packet",
             "calibration_packet", "health_summary"],
    "atlas": ["candidate_packet", "idea_packet", "experiment_batch_packet",
              "failure_learning_packet", "health_summary"],
    "sigma": ["promotion_packet", "validation_packet", "strategy_rejection_packet",
              "paper_review_packet", "papertrade_candidate_packet", "health_summary"],
    "hermes": ["theme_packet", "research_packet", "dataset_packet", "repo_packet",
               "research_request_packet", "health_summary"],
    "kitt": ["brief_packet", "setup_packet", "alert_packet", "health_summary"],
    "executor": ["execution_status_packet", "fill_packet", "execution_intent_packet",
                 "execution_rejection_packet", "position_update_packet",
                 "kill_switch_event", "health_summary"],
}


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


# ---------------------------------------------------------------------------
# Position extraction — pick most representative packet per lane
# ---------------------------------------------------------------------------

def _classify_direction(thesis: str, notes: Optional[str] = None) -> str:
    """Extract directional stance from thesis and notes text."""
    text = thesis.lower()
    if notes:
        text += " " + notes.lower()

    bullish_signals = ("bullish", "long", "breakout", "upside", "rally",
                       "recovery", "support holding")
    bearish_signals = ("bearish", "short", "breakdown", "downside", "selloff",
                       "decline", "resistance holding")

    bull = sum(1 for w in bullish_signals if w in text)
    bear = sum(1 for w in bearish_signals if w in text)

    if bull > bear:
        return "bullish"
    elif bear > bull:
        return "bearish"
    return "neutral"


def _extract_lane_positions(latest: dict[str, QuantPacket]) -> dict[str, dict]:
    """Extract each lane's current position from latest packets.

    Uses packet type preference to pick the most representative packet per lane.
    Returns {lane: {thesis, confidence, direction, packet_id, packet_type, priority}}.
    """
    # Group packets by lane
    by_lane: dict[str, list[QuantPacket]] = {}
    for key, pkt in latest.items():
        by_lane.setdefault(pkt.lane, []).append(pkt)

    positions: dict[str, dict] = {}
    for lane, pkts in by_lane.items():
        # Skip tradefloor's own packets
        if lane == "tradefloor":
            continue

        # Pick best packet by preference order
        chosen = None
        prefs = _LANE_PACKET_PREFERENCE.get(lane, [])
        for ptype in prefs:
            for pkt in pkts:
                if pkt.packet_type == ptype:
                    chosen = pkt
                    break
            if chosen:
                break

        # Fallback: highest priority, most recent
        if not chosen:
            chosen = max(pkts, key=lambda p: (
                p.priority in ("critical", "high"),
                p.created_at,
            ))

        direction = _classify_direction(chosen.thesis, chosen.notes)

        positions[lane] = {
            "thesis": chosen.thesis,
            "confidence": chosen.confidence or 0.5,
            "direction": direction,
            "packet_id": chosen.packet_id,
            "packet_type": chosen.packet_type,
            "priority": chosen.priority,
        }

    return positions


# ---------------------------------------------------------------------------
# Fish calibration confidence adjustment (spec §9)
# ---------------------------------------------------------------------------

def _apply_calibration_adjustments(root: Path, positions: dict[str, dict]) -> dict[str, dict]:
    """Adjust Fish confidence based on calibration track record per spec §9.

    Reads Fish calibration state. If track record is weak, penalize
    Fish's confidence in the synthesis. If strong, leave it alone.
    """
    if "fish" not in positions:
        return positions

    try:
        from workspace.quant.fish.scenario_lane import build_calibration_state
        cal_state = build_calibration_state(root)
    except Exception:
        return positions

    if cal_state["total_calibrations"] == 0:
        return positions

    tr_conf = cal_state["track_record_confidence"]
    original_conf = positions["fish"]["confidence"]

    # Blend Fish's stated confidence with its track record.
    # Good track record (>0.6) preserves or boosts; bad (<0.4) penalizes.
    adjusted = 0.6 * original_conf + 0.4 * tr_conf
    adjusted = max(0.05, min(0.95, adjusted))

    positions["fish"] = {
        **positions["fish"],
        "confidence": adjusted,
        "calibration_adjusted": True,
        "original_confidence": original_conf,
        "track_record_confidence": tr_conf,
        "calibration_trend": cal_state["trend"],
    }

    return positions


# ---------------------------------------------------------------------------
# Risk zone integration
# ---------------------------------------------------------------------------

def _get_risk_context(root: Path) -> dict:
    """Read Fish active risk zones for synthesis context.

    Returns {zone_name: {level, trigger, ...}} or empty dict.
    """
    try:
        from workspace.quant.fish.scenario_lane import get_active_risk_zones
        return get_active_risk_zones(root)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Agreement computation
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Pipeline snapshot
# ---------------------------------------------------------------------------

def _pipeline_snapshot(root: Path) -> dict:
    strategies = load_all_strategies(root)
    by_state: dict[str, int] = {}
    for s in strategies.values():
        by_state[s.lifecycle_state] = by_state.get(s.lifecycle_state, 0) + 1
    return {
        "total_strategies": len(strategies),
        "by_state": by_state,
    }


# ---------------------------------------------------------------------------
# Synthesis text
# ---------------------------------------------------------------------------

def _build_synthesis_text(
    positions: dict[str, dict],
    risk_zones: dict,
) -> str:
    """Build confidence-weighted synthesis text from lane positions."""
    parts = []
    for lane, pos in sorted(positions.items(), key=lambda x: -x[1]["confidence"]):
        conf = pos["confidence"]
        cal_marker = ""
        if pos.get("calibration_adjusted"):
            cal_marker = f" cal={pos.get('track_record_confidence', '?'):.2f}"
        parts.append(f"[{lane} c={conf:.2f}{cal_marker} {pos['direction']}] {pos['thesis'][:80]}")

    if risk_zones:
        high_zones = [z for z, d in risk_zones.items() if d.get("level") == "high"]
        if high_zones:
            parts.append(f"[RISK] High zones active: {', '.join(high_zones)}")

    return " | ".join(parts) if parts else "No lane data"


# ---------------------------------------------------------------------------
# Main synthesis
# ---------------------------------------------------------------------------

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

        # Apply Fish calibration adjustment per spec §9
        positions = _apply_calibration_adjustments(root, positions)

        # Read risk context
        risk_zones = _get_risk_context(root)

        agreement_matrix = _build_agreement_matrix(positions)
        disagreement_matrix = _build_disagreement_matrix(positions)

        has_action = concrete_action is not None
        tier, tier_reasoning = _determine_agreement_tier(
            positions, agreement_matrix, disagreement_matrix, has_action,
        )

        # Build synthesis text
        synthesis_text = _build_synthesis_text(positions, risk_zones)

        pipeline = _pipeline_snapshot(root)

        # Collect evidence refs from all contributing packets
        evidence_refs = [pos["packet_id"] for pos in positions.values()]

        next_actions = []
        if tier >= 3 and concrete_action:
            next_actions.append({"action": concrete_action, "assigned_lane": "kitt"})
        if any(s == "PROMOTED" for s in pipeline.get("by_state", {}).keys()):
            next_actions.append({"action": "Review promoted strategies for paper trade", "assigned_lane": "kitt"})

        # Risk-driven actions
        high_risk = [z for z, d in risk_zones.items() if d.get("level") == "high"]
        if high_risk:
            next_actions.append({
                "action": f"Elevated risk zones: {', '.join(high_risk)}. Review exposure.",
                "assigned_lane": "kitt",
            })

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

        notes_parts = [f"host={slot.host}"]
        if override_reason:
            notes_parts.append(f"override={override_reason}")
        if risk_zones:
            notes_parts.append(f"risk_zones={len(risk_zones)}")
        fish_pos = positions.get("fish", {})
        if fish_pos.get("calibration_adjusted"):
            notes_parts.append(
                f"fish_cal_trend={fish_pos.get('calibration_trend', '?')}"
            )

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
            evidence_refs=evidence_refs,
            notes="; ".join(notes_parts),
        )
        store_packet(root, pkt)
        return pkt


# ---------------------------------------------------------------------------
# Health summary
# ---------------------------------------------------------------------------

def emit_health_summary(
    root: Path,
    period_start: str,
    period_end: str,
    packets_produced: int,
    syntheses_run: int = 0,
    cadence_refusals: int = 0,
    degraded_count: int = 0,
    error_count: int = 0,
    usefulness_score: float = 0.5,
    efficiency_score: float = 0.5,
    health_score: float = 0.8,
    confidence_score: float = 0.5,
    host_used: str = "NIMO",
    scheduler_waits: int = 0,
) -> QuantPacket:
    """Emit TradeFloor health_summary per spec §10."""
    can_start, _, _ = check_capacity(root, LANE)
    from workspace.quant.shared.governor import evaluate_cycle, get_lane_params
    gov_action, gov_reason = evaluate_cycle(
        root, LANE,
        usefulness_score=usefulness_score,
        efficiency_score=efficiency_score,
        health_score=health_score,
        confidence_score=confidence_score,
        host_has_capacity=can_start,
    )
    params = get_lane_params(root, LANE)

    pkt = make_packet(
        "health_summary", "tradefloor",
        f"TradeFloor health: {syntheses_run} syntheses, {cadence_refusals} cadence refusals, {degraded_count} degraded",
        priority="low",
        period_start=period_start,
        period_end=period_end,
        packets_produced=packets_produced,
        packets_by_type={"tradefloor_packet": syntheses_run},
        escalation_count=0,
        error_count=error_count,
        cloud_bursts=0,
        estimated_cloud_cost=0.0,
        notable_events=f"{degraded_count} degraded syntheses" if degraded_count else "routine",
        scheduler_waits=scheduler_waits,
        scheduler_bypasses=0,
        host_used=host_used,
        local_runtime_seconds=0.0,
        cloud_runtime_seconds=0.0,
        usefulness_score=usefulness_score,
        efficiency_score=efficiency_score,
        health_score=health_score,
        confidence_score=confidence_score,
        governor_action_taken=gov_action,
        governor_reason=gov_reason,
        current_batch_size=params.get("batch_size", 1),
        current_cadence_multiplier=params.get("cadence_multiplier", cadence_multiplier)
        if (cadence_multiplier := params.get("cadence_multiplier")) is not None
        else 1.0,
    )
    store_packet(root, pkt)
    return pkt
