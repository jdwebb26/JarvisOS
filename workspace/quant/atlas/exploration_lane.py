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

Host placement: NIMO primary, SonLM overflow (spec §2).
All heavy work goes through scheduler.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import make_packet, QuantPacket
from workspace.quant.shared.packet_store import store_packet, get_latest, list_lane_packets
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, load_all_strategies,
    get_strategy, get_lineage, get_children, get_strategies_by_state,
)
from workspace.quant.shared.scheduler.scheduler import (
    heavy_job_slot, check_capacity, resolve_host,
)
from workspace.quant.shared.governor import evaluate_cycle, get_lane_params

LANE = "atlas"

# Thesis similarity threshold — 0.0 = identical, 1.0 = completely different
# Below this ratio of shared words, we consider theses duplicates.
_SIMILARITY_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# Knowledge base — accumulated learning from the rejection/review trail
# ---------------------------------------------------------------------------

def _normalize_thesis(thesis: str) -> set[str]:
    """Extract meaningful words from a thesis for comparison."""
    # Strip adaptation annotations
    cleaned = re.sub(r"\[adapted:.*?\]", "", thesis, flags=re.IGNORECASE)
    words = set(re.findall(r"[a-z0-9]+", cleaned.lower()))
    # Remove very common stopwords
    words -= {"the", "a", "an", "is", "it", "in", "on", "of", "to", "and", "or",
              "for", "with", "from", "by", "at", "as", "be", "this", "that", "not"}
    return words


def _thesis_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity between two thesis strings. 0.0=disjoint, 1.0=identical."""
    wa, wb = _normalize_thesis(a), _normalize_thesis(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def build_knowledge(root: Path) -> dict:
    """Build a knowledge base from the full rejection and review trail.

    Returns:
        {
            "rejection_count": int,
            "clusters": {reason: count},
            "avoidance_patterns": [str],
            "adapted": bool,
            "rejected_theses": [(strategy_id, thesis, reason, detail, suggestion)],
            "failure_learnings": [(strategy_id, learning_text)],
            "paper_survivors": [(strategy_id, outcome)],
            "banned_params": {param_key: reason},
            "iteration_guidance": {strategy_id: guidance_text},
        }
    """
    rejections = list_lane_packets(root, "sigma", "strategy_rejection_packet")
    learnings = list_lane_packets(root, "atlas", "failure_learning_packet")
    paper_reviews = list_lane_packets(root, "sigma", "paper_review_packet")

    # Build a map of original candidate theses from Atlas lane
    atlas_candidates = list_lane_packets(root, "atlas", "candidate_packet")
    candidate_thesis_map: dict[str, str] = {}
    for c in atlas_candidates:
        if c.strategy_id:
            candidate_thesis_map[c.strategy_id] = c.thesis

    # Cluster rejection reasons
    clusters: dict[str, int] = {}
    rejected_theses: list[tuple[str, str, str, str, str]] = []
    for r in rejections:
        reason = r.rejection_reason or "unknown"
        clusters[reason] = clusters.get(reason, 0) + 1
        # Use the original candidate thesis for dedup comparison (not Sigma's rejection text)
        original_thesis = candidate_thesis_map.get(r.strategy_id or "", r.thesis)
        rejected_theses.append((
            r.strategy_id or "unknown",
            original_thesis,
            reason,
            r.rejection_detail or "",
            r.suggestion or "",
        ))

    # Build avoidance patterns from clusters (threshold: 2+ of same reason)
    avoidance: list[str] = []
    for reason, count in clusters.items():
        if count >= 2:
            avoidance.append(f"avoid_{reason}")
        elif count >= 1:
            avoidance.append(f"caution_{reason}")

    # Extract failure learnings
    failure_learnings: list[tuple[str, str]] = []
    for l in learnings:
        failure_learnings.append((l.strategy_id or "unknown", l.thesis))

    # Extract paper review outcomes
    paper_survivors: list[tuple[str, str]] = []
    iteration_guidance: dict[str, str] = {}
    for pr in paper_reviews:
        paper_survivors.append((pr.strategy_id or "unknown", pr.outcome or "unknown"))
        if pr.outcome == "iterate" and pr.iteration_guidance:
            iteration_guidance[pr.strategy_id or "unknown"] = pr.iteration_guidance

    # Build banned parameter patterns from repeated failures
    banned_params: dict[str, str] = {}
    if clusters.get("curve_fit", 0) >= 2:
        banned_params["overfit_risk"] = "Multiple curve_fit rejections — increase OOS validation"
    if clusters.get("excessive_drawdown", 0) >= 2:
        banned_params["drawdown_risk"] = "Multiple excessive_drawdown — tighten stop-loss or reduce position sizing"
    if clusters.get("insufficient_trades", 0) >= 2:
        banned_params["trade_frequency"] = "Multiple insufficient_trades — broaden entry criteria"
    if clusters.get("regime_fragile", 0) >= 2:
        banned_params["regime_sensitivity"] = "Multiple regime_fragile — add regime filter"

    return {
        "rejection_count": len(rejections),
        "clusters": clusters,
        "avoidance_patterns": avoidance,
        "adapted": len(avoidance) > 0,
        "rejected_theses": rejected_theses,
        "failure_learnings": failure_learnings,
        "paper_survivors": paper_survivors,
        "banned_params": banned_params,
        "iteration_guidance": iteration_guidance,
    }


# Keep backward-compat alias
def ingest_rejections(root: Path) -> dict:
    """Ingest Sigma rejection packets and build avoidance patterns.

    Returns a feedback summary: {rejection_count, clusters, avoidance_patterns, adapted, ...}
    """
    return build_knowledge(root)


# ---------------------------------------------------------------------------
# Thesis dedup — prevent submitting the same failed idea
# ---------------------------------------------------------------------------

def check_thesis_dedup(root: Path, thesis: str) -> Optional[tuple[str, float]]:
    """Check if a thesis is too similar to a previously rejected one.

    Returns (rejected_strategy_id, similarity) if duplicate found, else None.
    """
    knowledge = build_knowledge(root)
    for sid, rej_thesis, reason, detail, suggestion in knowledge["rejected_theses"]:
        sim = _thesis_similarity(thesis, rej_thesis)
        if sim >= _SIMILARITY_THRESHOLD:
            return (sid, sim)
    return None


# ---------------------------------------------------------------------------
# Candidate generation — rejection-aware, knowledge-driven
# ---------------------------------------------------------------------------

def _compute_adjusted_confidence(
    base_confidence: float,
    knowledge: dict,
    parent_id: Optional[str],
) -> float:
    """Adjust confidence based on accumulated knowledge.

    - Boost if adapting from known failures (learning applied)
    - Reduce if generating in a heavily-rejected area
    - Boost if parent survived paper trading
    """
    adjusted = base_confidence

    # Boost for adaptation: we've learned from failures
    if knowledge["adapted"]:
        adjusted += 0.05

    # Reduce for high rejection density (many failures = risky area)
    total_rejections = knowledge["rejection_count"]
    if total_rejections >= 5:
        adjusted -= 0.10
    elif total_rejections >= 3:
        adjusted -= 0.05

    # Boost if parent survived paper trading
    if parent_id:
        for sid, outcome in knowledge["paper_survivors"]:
            if sid == parent_id and outcome == "advance_to_live":
                adjusted += 0.10
                break
            elif sid == parent_id and outcome == "iterate":
                adjusted += 0.05
                break

    # Boost for applied failure learnings
    if knowledge["failure_learnings"]:
        adjusted += 0.02 * min(len(knowledge["failure_learnings"]), 3)

    return max(0.05, min(0.95, adjusted))


def _compute_parameter_adjustments(knowledge: dict) -> dict:
    """Compute parameter adjustments based on failure patterns.

    Returns a dict of parameter adjustments the candidate should apply.
    """
    adjustments: dict[str, str] = {}

    # Apply adjustments based on banned params (from repeated failures)
    for param_key, reason in knowledge["banned_params"].items():
        adjustments[param_key] = reason

    # Apply adjustments from individual rejection patterns
    clusters = knowledge["clusters"]
    if clusters.get("poor_oos", 0) >= 1:
        adjustments["oos_validation"] = "strengthen_oos"
    if clusters.get("curve_fit", 0) >= 1:
        adjustments["regularization"] = "increase_regularization"
    if clusters.get("regime_fragile", 0) >= 1:
        adjustments["regime_filter"] = "add_regime_filter"
    if clusters.get("excessive_drawdown", 0) >= 1:
        adjustments["risk_management"] = "tighten_stops"
    if clusters.get("insufficient_trades", 0) >= 1:
        adjustments["entry_criteria"] = "broaden_entries"
    if clusters.get("correlation_to_existing", 0) >= 1:
        adjustments["diversification"] = "increase_uniqueness"

    return adjustments


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
    skip_thesis_dedup: bool = False,
) -> tuple[QuantPacket, dict]:
    """Generate a candidate packet with rejection-aware exploration.

    Consults the full knowledge base (rejections, learnings, paper reviews)
    to steer away from known failure patterns and adjust parameters.

    Raises:
        ValueError: if strategy_id already exists or thesis is duplicate of rejected idea
    """
    # Check for ID duplicate
    if _strategy_id_exists(root, strategy_id):
        raise ValueError(f"Strategy {strategy_id} already exists in registry")

    # Check thesis dedup (unless explicitly skipped, e.g. for iterate path)
    if not skip_thesis_dedup:
        dup = check_thesis_dedup(root, thesis)
        if dup is not None:
            dup_sid, dup_sim = dup
            raise DuplicateThesisError(
                f"Thesis too similar to rejected strategy {dup_sid} "
                f"(similarity={dup_sim:.2f} >= {_SIMILARITY_THRESHOLD})",
                rejected_id=dup_sid,
                similarity=dup_sim,
            )

    # Build knowledge
    knowledge = build_knowledge(root)
    applied_avoidance = avoidance_patterns or knowledge["avoidance_patterns"]

    # Compute parameter adjustments from failure patterns
    param_adjustments = _compute_parameter_adjustments(knowledge)

    # Adjust confidence based on knowledge
    adjusted_confidence = _compute_adjusted_confidence(confidence, knowledge, parent_id)

    # Annotate thesis with adaptation context
    adapted_thesis = thesis
    if applied_avoidance:
        adapted_thesis = f"{thesis} [adapted: avoiding {', '.join(applied_avoidance)}]"

    # Create strategy in registry
    create_strategy(
        root, strategy_id, actor="atlas",
        parent_id=parent_id, lineage_note=lineage_note,
    )

    # Transition to CANDIDATE
    transition_strategy(root, strategy_id, "CANDIDATE", actor="atlas",
                        note=f"Generated with avoidance: {applied_avoidance or 'none'}; "
                             f"param_adjustments: {list(param_adjustments.keys()) or 'none'}")

    # Build notes with parameter adjustments
    notes_parts = []
    if applied_avoidance:
        notes_parts.append(f"avoidance_patterns: {applied_avoidance}")
    if param_adjustments:
        notes_parts.append(f"param_adjustments: {param_adjustments}")
    if knowledge["failure_learnings"]:
        notes_parts.append(f"learnings_applied: {len(knowledge['failure_learnings'])}")

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
        notes="; ".join(notes_parts) if notes_parts else None,
    )
    store_packet(root, candidate)

    # Include param_adjustments in the feedback dict
    feedback = dict(knowledge)
    feedback["param_adjustments"] = param_adjustments
    feedback["adjusted_confidence"] = adjusted_confidence

    return candidate, feedback


# ---------------------------------------------------------------------------
# Iterate path — re-submit a strategy from ITERATE state with sigma guidance
# ---------------------------------------------------------------------------

def iterate_candidate(
    root: Path,
    original_strategy_id: str,
    new_strategy_id: str,
    revised_thesis: str,
    symbol_scope: str = "NQ",
    timeframe_scope: str = "15m",
    confidence: float = 0.5,
    evidence_refs: Optional[list[str]] = None,
) -> tuple[QuantPacket, dict]:
    """Create a new candidate from an ITERATE strategy, incorporating sigma guidance.

    This is the spec-compliant iteration path:
    ITERATE → (new IDEA with parent_id) → CANDIDATE

    The revised_thesis should address the issues identified in the paper review.
    Thesis dedup is skipped because this is an intentional iteration.

    Raises:
        ValueError: if original strategy is not in ITERATE state
    """
    original = get_strategy(root, original_strategy_id)
    if original is None:
        raise ValueError(f"Strategy {original_strategy_id} not found")
    if original.lifecycle_state != "ITERATE":
        raise ValueError(
            f"Strategy {original_strategy_id} is in state {original.lifecycle_state}, "
            f"expected ITERATE"
        )

    # Extract iteration guidance from state history
    guidance = None
    for entry in reversed(original.state_history):
        if entry.iteration_guidance:
            guidance = entry.iteration_guidance
            break

    # Build lineage note
    lineage_note = f"Iteration of {original_strategy_id}"
    if guidance:
        lineage_note += f" — guidance: {guidance}"

    # Generate with skip_thesis_dedup=True (intentional iteration, not a naive retry)
    return generate_candidate(
        root,
        strategy_id=new_strategy_id,
        thesis=revised_thesis,
        symbol_scope=symbol_scope,
        timeframe_scope=timeframe_scope,
        confidence=confidence,
        evidence_refs=evidence_refs,
        parent_id=original_strategy_id,
        lineage_note=lineage_note,
        skip_thesis_dedup=True,
    )


# ---------------------------------------------------------------------------
# Batch generation
# ---------------------------------------------------------------------------

def generate_candidate_batch(
    root: Path,
    candidates: list[dict],
) -> tuple[QuantPacket, list[QuantPacket], dict]:
    """Generate a batch of candidates with scheduler-aware heavy-job control.

    Each entry in candidates: {strategy_id, thesis, symbol_scope?, ...}

    Returns (batch_packet, candidate_packets, scheduler_info).
    Heavy work goes through scheduler; if no capacity, returns partial results.
    """
    scheduler_info = {"acquired": False, "host": "", "waited": False,
                      "generated": 0, "skipped": 0, "dedup_blocked": 0}

    with heavy_job_slot(root, LANE) as slot:
        scheduler_info["acquired"] = slot.acquired
        scheduler_info["host"] = slot.host
        scheduler_info["waited"] = slot.waited

        if not slot.acquired:
            scheduler_info["skipped"] = len(candidates)
            batch = make_packet(
                "experiment_batch_packet", "atlas",
                f"Batch skipped: scheduler wait ({slot.wait_reason}). {len(candidates)} candidates deferred.",
                priority="low",
                notes=f"scheduler_wait={slot.wait_reason}; host={slot.host}",
                escalation_level="none",
            )
            store_packet(root, batch)
            return batch, [], scheduler_info

        # Governor check
        params = get_lane_params(root, LANE)
        if params.get("paused"):
            scheduler_info["skipped"] = len(candidates)
            batch = make_packet(
                "experiment_batch_packet", "atlas",
                f"Batch skipped: lane paused by governor.",
                priority="low",
                escalation_level="none",
            )
            store_packet(root, batch)
            return batch, [], scheduler_info

        max_batch = params.get("batch_size", 1)
        to_run = candidates[:max_batch]
        generated = []

        for c in to_run:
            try:
                pkt, _ = generate_candidate(
                    root,
                    strategy_id=c["strategy_id"],
                    thesis=c["thesis"],
                    symbol_scope=c.get("symbol_scope", "NQ"),
                    timeframe_scope=c.get("timeframe_scope", "15m"),
                    confidence=c.get("confidence", 0.5),
                    evidence_refs=c.get("evidence_refs"),
                    parent_id=c.get("parent_id"),
                    lineage_note=c.get("lineage_note"),
                )
                generated.append(pkt)
            except DuplicateThesisError:
                scheduler_info["dedup_blocked"] = scheduler_info.get("dedup_blocked", 0) + 1
            except (ValueError, TimeoutError):
                pass

        scheduler_info["generated"] = len(generated)
        scheduler_info["skipped"] = len(candidates) - len(generated)

        batch = make_packet(
            "experiment_batch_packet", "atlas",
            f"Batch: {len(generated)}/{len(candidates)} candidates generated on {slot.host}",
            priority="medium",
            notes=f"host={slot.host}; batch_size={max_batch}; dedup_blocked={scheduler_info['dedup_blocked']}",
            escalation_level="team_only",
        )
        store_packet(root, batch)
        return batch, generated, scheduler_info


# ---------------------------------------------------------------------------
# Failure learning
# ---------------------------------------------------------------------------

def emit_failure_learning(
    root: Path,
    rejection_packet: QuantPacket,
    learning: str,
) -> QuantPacket:
    """Emit a failure_learning_packet after processing a rejection."""
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


# ---------------------------------------------------------------------------
# Health summary
# ---------------------------------------------------------------------------

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
    scheduler_waits: int = 0,
    batch_size: int = 1,
    cadence_multiplier: float = 1.0,
) -> QuantPacket:
    """Emit Atlas health_summary per spec §10.

    Also runs governor evaluation to determine next-cycle action.
    """
    # Evaluate governor
    can_start, _, _ = check_capacity(root, LANE)
    gov_action, gov_reason = evaluate_cycle(
        root, LANE,
        usefulness_score=usefulness_score,
        efficiency_score=efficiency_score,
        health_score=health_score,
        confidence_score=confidence_score,
        host_has_capacity=can_start,
    )

    # Read back updated params
    params = get_lane_params(root, LANE)

    # Include knowledge summary in health
    knowledge = build_knowledge(root)

    pkt = make_packet(
        "health_summary", "atlas",
        f"Atlas health: {candidates_generated} candidates, {rejections_ingested} rejections ingested, "
        f"{len(knowledge['failure_learnings'])} learnings, "
        f"{len(knowledge['banned_params'])} banned params",
        priority="low",
        period_start=period_start,
        period_end=period_end,
        packets_produced=packets_produced,
        packets_by_type={"candidate_packet": candidates_generated,
                         "failure_learning_packet": rejections_ingested},
        escalation_count=0,
        error_count=error_count,
        cloud_bursts=0,
        estimated_cloud_cost=0.0,
        notable_events=(
            f"Adapted from {rejections_ingested} rejections; "
            f"banned_params={list(knowledge['banned_params'].keys())}"
            if rejections_ingested else "routine"
        ),
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strategy_id_exists(root: Path, strategy_id: str) -> bool:
    """Check if a strategy_id already exists in registry."""
    all_strats = load_all_strategies(root)
    return strategy_id in all_strats


class DuplicateThesisError(ValueError):
    """Raised when a candidate thesis is too similar to a previously rejected one."""
    def __init__(self, message: str, rejected_id: str, similarity: float):
        super().__init__(message)
        self.rejected_id = rejected_id
        self.similarity = similarity
