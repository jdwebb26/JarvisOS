#!/usr/bin/env python3
"""Quant Lanes — Atlas Exploration Lane.

Per spec §6: autonomous autoquant / R&D lab.

Atlas should: generate, mutate, explore, rank, package, adapt from rejections,
check registry for duplicates, log feedback intake.

Atlas should not: validate, notify operator for routine experiments, trade,
submit duplicates of active strategies.

Feedback contract:
  - reads Sigma strategy_rejection_packets, adapts when rejections cluster
  - reads Sigma paper_review_packets to learn what survived
  - logs which patterns it has adapted to
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import make_packet, QuantPacket
from workspace.quant.shared.packet_store import store_packet, get_latest, list_lane_packets
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, load_all_strategies,
)


def _load_rejection_history(root: Path) -> list[QuantPacket]:
    """Load all Sigma rejection packets."""
    return list_lane_packets(root, "sigma", "strategy_rejection_packet")


def _cluster_rejections(rejections: list[QuantPacket]) -> dict[str, int]:
    """Count rejection reasons to find failure clusters."""
    counts: dict[str, int] = {}
    for r in rejections:
        reason = r.rejection_reason or "unknown"
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _strategy_id_exists(root: Path, strategy_id: str) -> bool:
    """Check if a strategy_id already exists in registry."""
    all_strats = load_all_strategies(root)
    return strategy_id in all_strats


def ingest_rejections(root: Path) -> dict:
    """Ingest Sigma rejection packets and build avoidance patterns.

    Returns a feedback summary: {reason: count, avoidance_patterns: [...]}
    """
    rejections = _load_rejection_history(root)
    clusters = _cluster_rejections(rejections)

    # Build avoidance patterns from clusters (threshold: 2+ of same reason)
    avoidance = []
    for reason, count in clusters.items():
        if count >= 2:
            avoidance.append(f"avoid_{reason}")
        elif count >= 1:
            avoidance.append(f"caution_{reason}")

    return {
        "rejection_count": len(rejections),
        "clusters": clusters,
        "avoidance_patterns": avoidance,
        "adapted": len(avoidance) > 0,
    }


def generate_candidate(
    root: Path,
    strategy_id: str,
    thesis: str,
    symbol_scope: str = "NQ",
    timeframe_scope: str = "15m",
    confidence: float = 0.5,
    evidence_refs: Optional[list[str]] = None,
    parent_id: Optional[str] = None,
    lineage_note: Optional[str] = None,
    avoidance_patterns: Optional[list[str]] = None,
) -> tuple[QuantPacket, dict]:
    """Generate a candidate packet with rejection-aware exploration.

    Consults rejection history to steer away from known failure patterns.
    Returns (candidate_packet, feedback_summary).
    """
    # Check for duplicate
    if _strategy_id_exists(root, strategy_id):
        raise ValueError(f"Strategy {strategy_id} already exists in registry")

    # Ingest feedback
    feedback = ingest_rejections(root)
    applied_avoidance = avoidance_patterns or feedback["avoidance_patterns"]

    # Adjust confidence based on rejection feedback
    adjusted_confidence = confidence
    if feedback["adapted"]:
        # If we've adapted from rejections, slightly boost confidence
        # (we're exploring new territory)
        adjusted_confidence = min(1.0, confidence + 0.05)

    # Annotate thesis with avoidance if applicable
    adapted_thesis = thesis
    if applied_avoidance:
        adapted_thesis = f"{thesis} [adapted: avoiding {', '.join(applied_avoidance)}]"

    # Create strategy in registry
    entry = create_strategy(
        root, strategy_id, actor="atlas",
        parent_id=parent_id, lineage_note=lineage_note,
    )

    # Transition to CANDIDATE
    transition_strategy(root, strategy_id, "CANDIDATE", actor="atlas",
                        note=f"Generated with avoidance: {applied_avoidance or 'none'}")

    # Emit candidate packet
    candidate = make_packet(
        "candidate_packet", "atlas",
        adapted_thesis,
        priority="medium",
        strategy_id=strategy_id,
        symbol_scope=symbol_scope,
        timeframe_scope=timeframe_scope,
        confidence=adjusted_confidence,
        evidence_refs=evidence_refs or [],
        action_requested="Submit to Sigma for validation",
        escalation_level="team_only",
        notes=f"avoidance_patterns: {applied_avoidance}" if applied_avoidance else None,
    )
    store_packet(root, candidate)

    return candidate, feedback


def emit_failure_learning(
    root: Path,
    rejection_packet: QuantPacket,
    learning: str,
) -> QuantPacket:
    """Emit a failure_learning_packet after processing a rejection.

    Documents what Atlas learned from Sigma's rejection feedback.
    """
    pkt = make_packet(
        "failure_learning_packet", "atlas",
        f"Learning from rejection of {rejection_packet.strategy_id}: {learning}",
        priority="low",
        strategy_id=rejection_packet.strategy_id,
        evidence_refs=[rejection_packet.packet_id],
        escalation_level="none",
    )
    store_packet(root, pkt)
    return pkt


def emit_health_summary(
    root: Path,
    period_start: str,
    period_end: str,
    packets_produced: int,
    candidates_generated: int = 0,
    rejections_ingested: int = 0,
    error_count: int = 0,
    usefulness_score: float = 0.5,
    efficiency_score: float = 0.5,
    health_score: float = 0.8,
    confidence_score: float = 0.5,
    host_used: str = "NIMO",
    governor_action: str = "none",
    governor_reason: str = "",
    batch_size: int = 1,
    cadence_multiplier: float = 1.0,
) -> QuantPacket:
    """Emit Atlas health_summary per spec §10."""
    pkt = make_packet(
        "health_summary", "atlas",
        f"Atlas health: {candidates_generated} candidates, {rejections_ingested} rejections ingested",
        priority="low",
        period_start=period_start,
        period_end=period_end,
        packets_produced=packets_produced,
        packets_by_type={"candidate_packet": candidates_generated, "failure_learning_packet": rejections_ingested},
        escalation_count=0,
        error_count=error_count,
        cloud_bursts=0,
        estimated_cloud_cost=0.0,
        notable_events=f"Adapted from {rejections_ingested} rejections" if rejections_ingested else "routine",
        scheduler_waits=0,
        scheduler_bypasses=0,
        host_used=host_used,
        local_runtime_seconds=0.0,
        cloud_runtime_seconds=0.0,
        usefulness_score=usefulness_score,
        efficiency_score=efficiency_score,
        health_score=health_score,
        confidence_score=confidence_score,
        governor_action_taken=governor_action,
        governor_reason=governor_reason,
        current_batch_size=batch_size,
        current_cadence_multiplier=cadence_multiplier,
    )
    store_packet(root, pkt)
    return pkt
