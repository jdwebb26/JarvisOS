#!/usr/bin/env python3
"""Quant Lanes — Fish Scenario / Simulation / Calibration Lane.

Per spec §6: scenario, simulation, forecasting, MiroFish lane.

Fish should: simulate, forecast, map futures, self-calibrate.
Fish should not: validate strategies, own promotion, trade.

Feedback contract:
  - periodically compares forecasts to outcomes
  - calibration adjusts own confidence weights
  - Fish confidence = f(calibration history); poor recent accuracy → lower confidence
  - calibration_packet shared with Kitt

Host placement: SonLM primary, cloud overflow (spec §2).
All heavy work goes through scheduler.
"""
from __future__ import annotations

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

    pkt = make_packet(
        "forecast_packet", "fish",
        thesis,
        priority="medium",
        symbol_scope=symbol_scope,
        timeframe_scope=timeframe_scope,
        confidence=confidence,
        evidence_refs=evidence_refs or [],
        notes="; ".join(notes_parts) if notes_parts else None,
        escalation_level="team_only",
    )
    store_packet(root, pkt)
    return pkt


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
        import json
        rz_dir = root / "workspace" / "quant" / "fish" / "risk_maps"
        rz_dir.mkdir(parents=True, exist_ok=True)
        rz_path = rz_dir / f"{pkt.packet_id}_zones.json"
        rz_path.write_text(json.dumps(risk_zones, indent=2) + "\n", encoding="utf-8")
        pkt.artifacts = [str(rz_path)]

    store_packet(root, pkt)
    return pkt


def calibrate(
    root: Path,
    prior_forecast: QuantPacket,
    realized_value: float,
    realized_direction: str,
) -> tuple[QuantPacket, dict]:
    """Compare a prior forecast to realized outcome and emit calibration_packet.

    This is the core feedback loop: Fish compares what it predicted
    to what actually happened, computes error, and adjusts confidence.

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
        normalized_error = min(value_error / 500.0, 1.0)
        score_components.append(1.0 - normalized_error)

    calibration_score = sum(score_components) / len(score_components) if score_components else 0.5

    # Blend prior confidence with calibration score
    adjusted_confidence = 0.7 * prior_confidence + 0.3 * calibration_score

    # Load calibration history to compute trend
    cal_history = list_lane_packets(root, "fish", "calibration_packet")
    recent_scores = []
    for cp in cal_history[-5:]:
        if cp.confidence is not None:
            recent_scores.append(cp.confidence)
    recent_scores.append(calibration_score)

    if len(recent_scores) >= 2:
        trend = "improving" if recent_scores[-1] > sum(recent_scores[:-1]) / len(recent_scores[:-1]) else "degrading"
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
        "history_depth": len(recent_scores),
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
        notes=f"calibration_score={calibration_score:.3f}; trend={trend}; direction_correct={direction_correct}",
        escalation_level="team_only",
    )
    store_packet(root, pkt)

    return pkt, calibration_result


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
    """Emit Fish health_summary per spec §10 with governor evaluation."""
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

    pkt = make_packet(
        "health_summary", "fish",
        f"Fish health: {scenarios_emitted} scenarios, {forecasts_emitted} forecasts, {calibrations_done} calibrations",
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
        notable_events=f"{calibrations_done} calibrations performed" if calibrations_done else "routine",
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
