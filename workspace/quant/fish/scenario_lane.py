#!/usr/bin/env python3
"""Quant Lanes — Fish Scenario / Simulation / Calibration Lane.

Per spec §6: scenario, simulation, forecasting, MiroFish lane.

Fish should: simulate, forecast, map futures, self-calibrate.
Fish should not: validate strategies, own promotion, trade.

Feedback contract:
  - periodically compares forecasts to outcomes
  - calibration adjusts own confidence weights based on track record
  - Fish confidence = f(calibration history); poor recent accuracy → lower confidence
  - calibration_packet shared with Kitt
  - risk_map aggregated for TradeFloor/Kitt synthesis

Host placement: SonLM primary, cloud overflow (spec §2).
All heavy work goes through scheduler.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import make_packet, QuantPacket
from workspace.quant.shared.packet_store import store_packet, get_latest, list_lane_packets
from workspace.quant.shared.scheduler.scheduler import (
    heavy_job_slot, check_capacity, resolve_host,
)
from workspace.quant.shared.governor import evaluate_cycle, get_lane_params

LANE = "fish"

# How many recent calibrations to consider for track-record-based confidence
_TRACK_RECORD_WINDOW = 10

# Value error normalization denominator (NQ points)
_VALUE_ERROR_NORM = 500.0

# Number of calibrations before track record gets full weight
_TR_RAMP_COUNT = 5


def _sorted_by_time(packets: list[QuantPacket]) -> list[QuantPacket]:
    """Sort packets by created_at (chronological). Handles sub-second ordering."""
    return sorted(packets, key=lambda p: p.created_at)


# ---------------------------------------------------------------------------
# Scenario emission + history
# ---------------------------------------------------------------------------

def emit_scenario(
    root: Path,
    thesis: str,
    symbol_scope: str = "NQ",
    timeframe_scope: str = "1D",
    confidence: float = 0.5,
    evidence_refs: Optional[list[str]] = None,
) -> QuantPacket:
    """Emit a scenario_packet describing a market scenario."""
    pkt = make_packet(
        "scenario_packet", "fish",
        thesis,
        priority="medium",
        symbol_scope=symbol_scope,
        timeframe_scope=timeframe_scope,
        confidence=confidence,
        evidence_refs=evidence_refs or [],
        escalation_level="team_only",
    )
    store_packet(root, pkt)
    return pkt


def get_scenario_history(
    root: Path,
    symbol_scope: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Query past scenarios with optional symbol filter.

    Returns list of dicts: {packet_id, thesis, symbol_scope, timeframe_scope,
                            confidence, created_at, evidence_refs}
    """
    packets = list_lane_packets(root, "fish", "scenario_packet")
    results = []
    for p in packets:
        if symbol_scope and p.symbol_scope != symbol_scope:
            continue
        results.append({
            "packet_id": p.packet_id,
            "thesis": p.thesis,
            "symbol_scope": p.symbol_scope,
            "timeframe_scope": p.timeframe_scope,
            "confidence": p.confidence,
            "created_at": p.created_at,
            "evidence_refs": p.evidence_refs,
        })
    return results[-limit:]


# ---------------------------------------------------------------------------
# Forecast emission + pending tracking
# ---------------------------------------------------------------------------

def emit_forecast(
    root: Path,
    thesis: str,
    symbol_scope: str = "NQ",
    timeframe_scope: str = "1W",
    confidence: float = 0.5,
    forecast_value: Optional[float] = None,
    forecast_direction: Optional[str] = None,
    evidence_refs: Optional[list[str]] = None,
) -> QuantPacket:
    """Emit a forecast_packet with a directional or value prediction."""
    notes_parts = []
    if forecast_direction:
        notes_parts.append(f"direction={forecast_direction}")
    if forecast_value is not None:
        notes_parts.append(f"target={forecast_value}")
    notes_parts.append("status=pending")

    pkt = make_packet(
        "forecast_packet", "fish",
        thesis,
        priority="medium",
        symbol_scope=symbol_scope,
        timeframe_scope=timeframe_scope,
        confidence=confidence,
        evidence_refs=evidence_refs or [],
        notes="; ".join(notes_parts),
        escalation_level="team_only",
    )
    store_packet(root, pkt)
    return pkt


def get_pending_forecasts(root: Path) -> list[QuantPacket]:
    """List forecasts that haven't been calibrated yet.

    A forecast is pending if no calibration_packet references its packet_id.
    """
    forecasts = list_lane_packets(root, "fish", "forecast_packet")
    calibrations = list_lane_packets(root, "fish", "calibration_packet")

    # Build set of forecast IDs that have been calibrated
    calibrated_ids: set[str] = set()
    for cal in calibrations:
        for ref in cal.evidence_refs:
            calibrated_ids.add(ref)

    return [f for f in forecasts if f.packet_id not in calibrated_ids]


# ---------------------------------------------------------------------------
# Regime classification
# ---------------------------------------------------------------------------

def emit_regime(
    root: Path,
    thesis: str,
    regime_label: str = "unknown",
    confidence: float = 0.5,
) -> QuantPacket:
    """Emit a regime_packet classifying the current market regime."""
    pkt = make_packet(
        "regime_packet", "fish",
        thesis,
        priority="medium",
        confidence=confidence,
        notes=f"regime={regime_label}",
        escalation_level="team_only",
    )
    store_packet(root, pkt)
    return pkt


# ---------------------------------------------------------------------------
# Risk map emission + aggregation
# ---------------------------------------------------------------------------

def emit_risk_map(
    root: Path,
    thesis: str,
    risk_zones: Optional[dict] = None,
    symbol_scope: str = "NQ",
    confidence: float = 0.5,
    evidence_refs: Optional[list[str]] = None,
) -> QuantPacket:
    """Emit a risk_map_packet mapping risk zones.

    risk_zones: {zone_name: {level, description}} — e.g.,
        {"vix_spike": {"level": "high", "trigger": "VIX > 30"},
         "liquidity_gap": {"level": "medium", "trigger": "overnight volume < 50th pctile"}}
    """
    pkt = make_packet(
        "risk_map_packet", "fish",
        thesis,
        priority="medium",
        symbol_scope=symbol_scope,
        confidence=confidence,
        evidence_refs=evidence_refs or [],
        notes=f"risk_zones={len(risk_zones or {})}" if risk_zones else None,
        escalation_level="team_only",
    )
    # Store risk_zones in artifacts field as a path reference
    if risk_zones:
        rz_dir = root / "workspace" / "quant" / "fish" / "risk_maps"
        rz_dir.mkdir(parents=True, exist_ok=True)
        rz_path = rz_dir / f"{pkt.packet_id}_zones.json"
        rz_path.write_text(json.dumps(risk_zones, indent=2) + "\n", encoding="utf-8")
        pkt.artifacts = [str(rz_path)]

    store_packet(root, pkt)
    return pkt


def get_active_risk_zones(root: Path, limit: int = 5) -> dict:
    """Aggregate recent risk maps into a unified risk zone view.

    Merges zones from the most recent risk_map_packets (up to `limit`).
    When the same zone appears in multiple maps, the most recent wins.
    Returns {zone_name: {level, trigger, source_packet_id, confidence}}.
    """
    risk_maps = _sorted_by_time(list_lane_packets(root, "fish", "risk_map_packet"))
    recent = risk_maps[-limit:]

    merged: dict[str, dict] = {}
    for rm in recent:
        if not rm.artifacts:
            continue
        for artifact_path in rm.artifacts:
            path = Path(artifact_path)
            if not path.exists():
                continue
            try:
                zones = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            for zone_name, zone_data in zones.items():
                merged[zone_name] = {
                    **zone_data,
                    "source_packet_id": rm.packet_id,
                    "confidence": rm.confidence,
                }
    return merged


# ---------------------------------------------------------------------------
# Calibration state — persistent accumulated track record
# ---------------------------------------------------------------------------

def _parse_calibration_score(packet: QuantPacket) -> Optional[float]:
    """Extract calibration_score from a calibration_packet's notes."""
    notes = packet.notes or ""
    for part in notes.split(";"):
        part = part.strip()
        if part.startswith("calibration_score="):
            try:
                return float(part.split("=", 1)[1])
            except ValueError:
                pass
    return None


def _parse_direction_correct(packet: QuantPacket) -> Optional[bool]:
    """Extract direction_correct from a calibration_packet's notes."""
    notes = packet.notes or ""
    for part in notes.split(";"):
        part = part.strip()
        if part.startswith("direction_correct="):
            val = part.split("=", 1)[1].strip()
            if val == "True":
                return True
            elif val == "False":
                return False
    return None


def build_calibration_state(root: Path) -> dict:
    """Build cumulative calibration state from all calibration_packets.

    Returns:
        {
            "total_calibrations": int,
            "direction_hits": int,
            "direction_misses": int,
            "direction_hit_rate": float,  # 0-1, or None if no directional forecasts
            "recent_scores": [float],     # last _TRACK_RECORD_WINDOW calibration_scores
            "recent_avg": float,          # mean of recent_scores
            "streak": int,                # positive = consecutive hits, negative = consecutive misses
            "trend": str,                 # "improving" | "degrading" | "stable" | "insufficient_data"
            "track_record_confidence": float,  # 0-1, derived from overall track record
        }
    """
    calibrations = _sorted_by_time(list_lane_packets(root, "fish", "calibration_packet"))

    total = len(calibrations)
    direction_hits = 0
    direction_misses = 0
    raw_scores: list[float] = []
    direction_results: list[bool] = []

    for cal in calibrations:
        score = _parse_calibration_score(cal)
        if score is not None:
            raw_scores.append(score)

        dc = _parse_direction_correct(cal)
        if dc is not None:
            direction_results.append(dc)
            if dc:
                direction_hits += 1
            else:
                direction_misses += 1

    # Recent window
    recent_scores = raw_scores[-_TRACK_RECORD_WINDOW:]
    recent_avg = sum(recent_scores) / len(recent_scores) if recent_scores else 0.5

    # Streak: count consecutive same results from the end
    streak = 0
    if direction_results:
        last = direction_results[-1]
        for r in reversed(direction_results):
            if r == last:
                streak += 1
            else:
                break
        if not last:
            streak = -streak

    # Trend: compare recent half to older half
    if len(recent_scores) >= 4:
        mid = len(recent_scores) // 2
        older_avg = sum(recent_scores[:mid]) / mid
        newer_avg = sum(recent_scores[mid:]) / (len(recent_scores) - mid)
        if newer_avg > older_avg + 0.05:
            trend = "improving"
        elif newer_avg < older_avg - 0.05:
            trend = "degrading"
        else:
            trend = "stable"
    elif len(recent_scores) >= 2:
        trend = "improving" if recent_scores[-1] > recent_scores[0] else "degrading"
    else:
        trend = "insufficient_data"

    # Direction hit rate
    total_directional = direction_hits + direction_misses
    direction_hit_rate = direction_hits / total_directional if total_directional > 0 else None

    # Track record confidence: a composite score that rewards accuracy + consistency
    # Base: recent_avg (raw calibration quality)
    # Boost: direction hit rate if available
    # Penalize: negative streaks
    tr_confidence = recent_avg
    if direction_hit_rate is not None:
        tr_confidence = 0.6 * recent_avg + 0.4 * direction_hit_rate
    if streak <= -3:
        tr_confidence *= 0.8  # Penalize cold streaks
    elif streak >= 3:
        tr_confidence *= 1.1  # Reward hot streaks
    tr_confidence = max(0.05, min(0.95, tr_confidence))

    return {
        "total_calibrations": total,
        "direction_hits": direction_hits,
        "direction_misses": direction_misses,
        "direction_hit_rate": direction_hit_rate,
        "recent_scores": recent_scores,
        "recent_avg": recent_avg,
        "streak": streak,
        "trend": trend,
        "track_record_confidence": tr_confidence,
    }


# ---------------------------------------------------------------------------
# Calibration — forecast vs outcome comparison
# ---------------------------------------------------------------------------

def calibrate(
    root: Path,
    prior_forecast: QuantPacket,
    realized_value: float,
    realized_direction: str,
) -> tuple[QuantPacket, dict]:
    """Compare a prior forecast to realized outcome and emit calibration_packet.

    This is the core feedback loop: Fish compares what it predicted
    to what actually happened, computes error, and adjusts confidence
    based on both this event and the cumulative track record.

    Returns (calibration_packet, calibration_result).
    """
    prior_confidence = prior_forecast.confidence or 0.5
    prior_notes = prior_forecast.notes or ""

    # Parse prior direction and value from notes
    prior_direction = None
    prior_value = None
    for part in prior_notes.split(";"):
        part = part.strip()
        if part.startswith("direction="):
            prior_direction = part.split("=", 1)[1]
        elif part.startswith("target="):
            try:
                prior_value = float(part.split("=", 1)[1])
            except ValueError:
                pass

    # Compute calibration metrics
    direction_correct = (prior_direction == realized_direction) if prior_direction else None
    value_error = abs(prior_value - realized_value) if prior_value is not None else None

    # Compute calibration score (0-1, higher = better)
    score_components = []
    if direction_correct is not None:
        score_components.append(1.0 if direction_correct else 0.0)
    if value_error is not None:
        normalized_error = min(value_error / _VALUE_ERROR_NORM, 1.0)
        score_components.append(1.0 - normalized_error)

    calibration_score = sum(score_components) / len(score_components) if score_components else 0.5

    # Build calibration state from history BEFORE this event
    cal_state = build_calibration_state(root)

    # Confidence adjustment: blend prior confidence, this calibration score,
    # and the cumulative track record.
    # Track record weight ramps up with sample count (0 at start, full at _TR_RAMP_COUNT).
    # Remaining weight goes to the event (calibration score).
    # - 50% prior confidence (momentum/continuity)
    # - (0.50 - tr_weight) event weight (immediate feedback)
    # - tr_weight track record confidence (accumulated trust)
    tr_conf = cal_state["track_record_confidence"]
    num_prior = cal_state["total_calibrations"]
    tr_weight = 0.30 * min(num_prior / _TR_RAMP_COUNT, 1.0)
    event_weight = 0.50 - tr_weight
    adjusted_confidence = (
        0.50 * prior_confidence
        + event_weight * calibration_score
        + tr_weight * tr_conf
    )
    adjusted_confidence = max(0.05, min(0.95, adjusted_confidence))

    # Compute trend including this new score
    all_scores = cal_state["recent_scores"] + [calibration_score]
    if len(all_scores) >= 4:
        mid = len(all_scores) // 2
        older_avg = sum(all_scores[:mid]) / mid
        newer_avg = sum(all_scores[mid:]) / (len(all_scores) - mid)
        if newer_avg > older_avg + 0.05:
            trend = "improving"
        elif newer_avg < older_avg - 0.05:
            trend = "degrading"
        else:
            trend = "stable"
    elif len(all_scores) >= 2:
        trend = "improving" if all_scores[-1] > all_scores[0] else "degrading"
    else:
        trend = "insufficient_data"

    calibration_result = {
        "prior_forecast_id": prior_forecast.packet_id,
        "prior_direction": prior_direction,
        "prior_value": prior_value,
        "prior_confidence": prior_confidence,
        "realized_direction": realized_direction,
        "realized_value": realized_value,
        "direction_correct": direction_correct,
        "value_error": value_error,
        "calibration_score": calibration_score,
        "adjusted_confidence": adjusted_confidence,
        "trend": trend,
        "history_depth": len(all_scores),
        "track_record_confidence": tr_conf,
        "direction_hit_rate": cal_state["direction_hit_rate"],
        "streak": cal_state["streak"],
    }

    thesis = (
        f"Calibration: forecast was {'correct' if direction_correct else 'incorrect'} on direction"
        f"{f', value error {value_error:.1f}' if value_error is not None else ''}. "
        f"Score: {calibration_score:.2f}, trend: {trend}. "
        f"Confidence adjusted {prior_confidence:.2f} → {adjusted_confidence:.2f}."
    )

    pkt = make_packet(
        "calibration_packet", "fish",
        thesis,
        priority="medium",
        confidence=adjusted_confidence,
        evidence_refs=[prior_forecast.packet_id],
        notes=(
            f"calibration_score={calibration_score:.3f}; "
            f"trend={trend}; "
            f"direction_correct={direction_correct}; "
            f"track_record_confidence={tr_conf:.3f}; "
            f"streak={cal_state['streak']}"
        ),
        escalation_level="team_only",
    )
    store_packet(root, pkt)

    return pkt, calibration_result


# ---------------------------------------------------------------------------
# Batch generation
# ---------------------------------------------------------------------------

def run_scenario_batch(
    root: Path,
    scenarios: list[dict],
) -> tuple[list[QuantPacket], dict]:
    """Run a batch of scenario simulations with scheduler-aware control.

    Each entry: {thesis, symbol_scope?, confidence?, ...}
    Returns (emitted_packets, scheduler_info).
    """
    scheduler_info = {"acquired": False, "host": "", "waited": False, "emitted": 0, "skipped": 0}

    with heavy_job_slot(root, LANE) as slot:
        scheduler_info["acquired"] = slot.acquired
        scheduler_info["host"] = slot.host
        scheduler_info["waited"] = slot.waited

        if not slot.acquired:
            scheduler_info["skipped"] = len(scenarios)
            return [], scheduler_info

        params = get_lane_params(root, LANE)
        if params.get("paused"):
            scheduler_info["skipped"] = len(scenarios)
            return [], scheduler_info

        max_batch = params.get("batch_size", 1)
        emitted = []
        for s in scenarios[:max_batch]:
            pkt = emit_scenario(
                root,
                thesis=s["thesis"],
                symbol_scope=s.get("symbol_scope", "NQ"),
                confidence=s.get("confidence", 0.5),
            )
            emitted.append(pkt)

        scheduler_info["emitted"] = len(emitted)
        scheduler_info["skipped"] = len(scenarios) - len(emitted)
        return emitted, scheduler_info


# ---------------------------------------------------------------------------
# Health summary — includes calibration state
# ---------------------------------------------------------------------------

def emit_health_summary(
    root: Path,
    period_start: str,
    period_end: str,
    packets_produced: int,
    scenarios_emitted: int = 0,
    forecasts_emitted: int = 0,
    calibrations_done: int = 0,
    error_count: int = 0,
    usefulness_score: float = 0.5,
    efficiency_score: float = 0.5,
    health_score: float = 0.8,
    confidence_score: float = 0.5,
    host_used: str = "SonLM",
    scheduler_waits: int = 0,
    batch_size: int = 1,
    cadence_multiplier: float = 1.0,
) -> QuantPacket:
    """Emit Fish health_summary per spec §10 with governor evaluation
    and calibration state."""
    can_start, _, _ = check_capacity(root, LANE)
    gov_action, gov_reason = evaluate_cycle(
        root, LANE,
        usefulness_score=usefulness_score,
        efficiency_score=efficiency_score,
        health_score=health_score,
        confidence_score=confidence_score,
        host_has_capacity=can_start,
    )

    params = get_lane_params(root, LANE)

    # Include calibration state in health
    cal_state = build_calibration_state(root)
    pending = get_pending_forecasts(root)

    notable_parts = []
    if calibrations_done:
        notable_parts.append(f"{calibrations_done} calibrations performed")
    if cal_state["total_calibrations"] > 0:
        notable_parts.append(
            f"track_record: {cal_state['trend']}, "
            f"hit_rate={cal_state['direction_hit_rate']}, "
            f"streak={cal_state['streak']}"
        )
    if pending:
        notable_parts.append(f"{len(pending)} forecasts pending calibration")

    pkt = make_packet(
        "health_summary", "fish",
        (
            f"Fish health: {scenarios_emitted} scenarios, "
            f"{forecasts_emitted} forecasts, {calibrations_done} calibrations. "
            f"Track record: {cal_state['trend']}, "
            f"tr_confidence={cal_state['track_record_confidence']:.2f}"
        ),
        priority="low",
        period_start=period_start,
        period_end=period_end,
        packets_produced=packets_produced,
        packets_by_type={
            "scenario_packet": scenarios_emitted,
            "forecast_packet": forecasts_emitted,
            "calibration_packet": calibrations_done,
        },
        escalation_count=0,
        error_count=error_count,
        cloud_bursts=0,
        estimated_cloud_cost=0.0,
        notable_events="; ".join(notable_parts) if notable_parts else "routine",
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
        current_batch_size=params.get("batch_size", batch_size),
        current_cadence_multiplier=params.get("cadence_multiplier", cadence_multiplier),
    )
    store_packet(root, pkt)
    return pkt
