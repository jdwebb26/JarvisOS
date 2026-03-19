#!/usr/bin/env python3
"""Quant Lanes — Packet contracts and validation.

Defines the standard packet schema per QUANT_LANES_OPERATING_SPEC v3.5.1 §10.
All quant lane packets must use these contracts. No raw dict packets.

Usage:
    from workspace.quant.shared.schemas.packets import (
        make_packet, validate_packet,
        PacketPriority, REJECTION_REASONS, EXECUTION_REJECTION_REASONS,
    )
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PacketPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EscalationLevel(str, Enum):
    NONE = "none"
    TEAM_ONLY = "team_only"
    KITT_ONLY = "kitt_only"
    OPERATOR_REVIEW = "operator_review"
    URGENT_OPERATOR = "urgent_operator"


# Strategy rejection reasons (Sigma → Atlas)
REJECTION_REASONS = {
    "curve_fit", "poor_oos", "insufficient_trades", "regime_fragile",
    "excessive_drawdown", "invalid_execution_assumptions",
    "correlation_to_existing", "other",
}

# Execution rejection reasons (Executor → Kitt)
EXECUTION_REJECTION_REASONS = {
    "invalid_approval", "expired_approval", "revoked_approval",
    "mode_mismatch", "symbol_not_approved", "strategy_limit_breach",
    "portfolio_limit_breach", "kill_switch_engaged", "broker_unhealthy",
    "broker_rejected", "insufficient_liquidity", "other",
}

# Canonical packet types per spec §10
CANONICAL_PACKET_TYPES = {
    # Research (Hermes)
    "research_packet", "dataset_packet", "repo_packet", "theme_packet",
    # Research direction (any → Hermes)
    "research_request_packet",
    # Discovery (Atlas)
    "idea_packet", "candidate_packet", "experiment_batch_packet", "failure_learning_packet",
    # Scenarios (Fish)
    "scenario_packet", "forecast_packet", "regime_packet", "risk_map_packet", "calibration_packet",
    # Validation (Sigma)
    "validation_packet", "promotion_packet", "strategy_rejection_packet",
    "papertrade_candidate_packet", "paper_review_packet",
    # Operator request (Kitt)
    "papertrade_request_packet", "live_trade_packet",
    # Execution (Executor)
    "execution_intent_packet", "execution_status_packet", "fill_packet",
    "execution_rejection_packet", "position_update_packet", "kill_switch_event",
    # Briefing (Kitt)
    "brief_packet", "setup_packet", "alert_packet",
    # Synthesis (TradeFloor or Kitt)
    "tradefloor_packet", "tradefloor_request_packet",
    # System (all lanes)
    "health_summary",
    # Pulse (discretionary / TradingView alert lane)
    "pulse_alert_packet", "pulse_cluster_packet", "pulse_outcome_packet",
    "pulse_learning_packet", "pulse_review_proposal_packet",
}

# Canonical lane names
LANE_NAMES = {"kitt", "atlas", "fish", "sigma", "hermes", "executor", "tradefloor", "pulse"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_hash(data: str, length: int = 8) -> str:
    return hashlib.sha256(data.encode()).hexdigest()[:length]


# ---------------------------------------------------------------------------
# Packet dataclass
# ---------------------------------------------------------------------------

@dataclass
class QuantPacket:
    """Standard quant lane packet — spec §10 core + extended fields."""

    # Core fields (required)
    packet_id: str = ""
    packet_type: str = ""
    lane: str = ""
    created_at: str = ""
    thesis: str = ""
    priority: str = "medium"

    # Extended fields (optional)
    strategy_id: Optional[str] = None
    symbol_scope: Optional[Any] = None
    timeframe_scope: Optional[str] = None
    confidence: Optional[float] = None
    evidence_refs: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    action_requested: Optional[str] = None
    escalation_level: str = "none"
    supersedes: Optional[str] = None
    approval_ref: Optional[str] = None
    notes: Optional[str] = None

    # Strategy rejection fields
    rejection_reason: Optional[str] = None
    rejection_detail: Optional[str] = None
    suggestion: Optional[str] = None

    # Execution rejection fields
    execution_rejection_reason: Optional[str] = None
    execution_rejection_detail: Optional[str] = None
    order_details: Optional[dict] = None

    # Execution fields
    execution_mode: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[str] = None
    order_type: Optional[str] = None
    sizing: Optional[dict] = None
    risk_limits: Optional[dict] = None
    execution_status: Optional[str] = None
    fill_price: Optional[float] = None
    slippage: Optional[float] = None
    error_code: Optional[str] = None

    # Paper review fields
    review_period: Optional[dict] = None
    trade_count: Optional[int] = None
    realized_pf: Optional[float] = None
    realized_sharpe: Optional[float] = None
    max_drawdown: Optional[float] = None
    avg_slippage: Optional[float] = None
    fill_rate: Optional[float] = None
    portfolio_correlation: Optional[float] = None
    consistency_flag: Optional[str] = None
    outcome: Optional[str] = None
    outcome_reasoning: Optional[str] = None
    iteration_guidance: Optional[str] = None

    # TradeFloor fields
    agreement_tier: Optional[int] = None
    agreement_tier_reasoning: Optional[str] = None
    agreement_matrix: Optional[dict] = None
    disagreement_matrix: Optional[dict] = None
    confidence_weighted_synthesis: Optional[str] = None
    pipeline_snapshot: Optional[dict] = None
    next_actions: Optional[list] = None
    deferred_questions: Optional[list] = None
    operator_recommendation: Optional[str] = None
    operator_recommendation_reasoning: Optional[str] = None
    degraded: Optional[bool] = None

    # Health summary fields
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    packets_produced: Optional[int] = None
    packets_by_type: Optional[dict] = None
    escalation_count: Optional[int] = None
    error_count: Optional[int] = None
    cloud_bursts: Optional[int] = None
    estimated_cloud_cost: Optional[float] = None
    notable_events: Optional[str] = None
    scheduler_waits: Optional[int] = None
    scheduler_bypasses: Optional[int] = None
    host_used: Optional[str] = None
    local_runtime_seconds: Optional[float] = None
    cloud_runtime_seconds: Optional[float] = None
    usefulness_score: Optional[float] = None
    efficiency_score: Optional[float] = None
    health_score: Optional[float] = None
    confidence_score: Optional[float] = None
    governor_action_taken: Optional[str] = None
    governor_reason: Optional[str] = None
    current_batch_size: Optional[int] = None
    current_cadence_multiplier: Optional[float] = None

    def to_dict(self) -> dict:
        """Serialize, dropping None values for compactness."""
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "QuantPacket":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


def make_packet(
    packet_type: str,
    lane: str,
    thesis: str,
    priority: str = "medium",
    **kwargs,
) -> QuantPacket:
    """Create a new packet with auto-generated ID and timestamp."""
    if packet_type not in CANONICAL_PACKET_TYPES:
        raise ValueError(f"Unknown packet_type: {packet_type!r}. Must be one of {CANONICAL_PACKET_TYPES}")
    if lane not in LANE_NAMES:
        raise ValueError(f"Unknown lane: {lane!r}. Must be one of {LANE_NAMES}")
    if priority not in PacketPriority._value2member_map_:
        raise ValueError(f"Invalid priority: {priority!r}")

    ts = _now_iso()
    short = _short_hash(f"{lane}{packet_type}{ts}")
    packet_id = f"{lane}-{packet_type.replace('_packet', '').replace('_', '-')}-{ts[:19].replace(':', '')}-{short}"

    return QuantPacket(
        packet_id=packet_id,
        packet_type=packet_type,
        lane=lane,
        created_at=ts,
        thesis=thesis,
        priority=priority,
        **kwargs,
    )


def validate_packet(packet: QuantPacket) -> list[str]:
    """Validate a packet against spec contracts. Returns list of errors (empty = valid)."""
    errors = []

    # Core field checks
    if not packet.packet_id:
        errors.append("packet_id is required")
    if not packet.packet_type:
        errors.append("packet_type is required")
    elif packet.packet_type not in CANONICAL_PACKET_TYPES:
        errors.append(f"packet_type {packet.packet_type!r} not in canonical list")
    if not packet.lane:
        errors.append("lane is required")
    elif packet.lane not in LANE_NAMES:
        errors.append(f"lane {packet.lane!r} not in canonical list")
    if not packet.created_at:
        errors.append("created_at is required")
    if not packet.thesis:
        errors.append("thesis is required")

    # Strategy rejection packet requirements
    if packet.packet_type == "strategy_rejection_packet":
        if not packet.rejection_reason:
            errors.append("strategy_rejection_packet requires rejection_reason")
        elif packet.rejection_reason not in REJECTION_REASONS:
            errors.append(f"rejection_reason {packet.rejection_reason!r} not valid")
        if not packet.rejection_detail:
            errors.append("strategy_rejection_packet requires rejection_detail")
        if not packet.strategy_id:
            errors.append("strategy_rejection_packet requires strategy_id")

    # Execution rejection packet requirements
    if packet.packet_type == "execution_rejection_packet":
        if not packet.execution_rejection_reason:
            errors.append("execution_rejection_packet requires execution_rejection_reason")
        elif packet.execution_rejection_reason not in EXECUTION_REJECTION_REASONS:
            errors.append(f"execution_rejection_reason {packet.execution_rejection_reason!r} not valid")
        if not packet.execution_rejection_detail:
            errors.append("execution_rejection_packet requires execution_rejection_detail")

    # Execution packets require approval_ref
    if packet.packet_type in {"execution_intent_packet", "execution_status_packet", "fill_packet"}:
        if not packet.approval_ref:
            errors.append(f"{packet.packet_type} requires approval_ref")
        if not packet.execution_mode:
            errors.append(f"{packet.packet_type} requires execution_mode")
        if not packet.strategy_id:
            errors.append(f"{packet.packet_type} requires strategy_id")

    # Papertrade request requires approval_ref
    if packet.packet_type == "papertrade_request_packet":
        if not packet.strategy_id:
            errors.append("papertrade_request_packet requires strategy_id")

    # Paper review packet requirements
    if packet.packet_type == "paper_review_packet":
        if not packet.strategy_id:
            errors.append("paper_review_packet requires strategy_id")
        if packet.outcome and packet.outcome not in {"advance_to_live", "iterate", "kill"}:
            errors.append(f"paper_review_packet outcome must be advance_to_live/iterate/kill, got {packet.outcome!r}")
        if packet.outcome == "iterate" and not packet.iteration_guidance:
            errors.append("paper_review_packet with iterate outcome requires iteration_guidance")

    return errors


def save_packet(packet: QuantPacket, base_dir: str | Any) -> str:
    """Save a packet to the given directory. Returns the file path."""
    from pathlib import Path
    d = Path(base_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{packet.packet_id}.json"
    path.write_text(json.dumps(packet.to_dict(), indent=2) + "\n", encoding="utf-8")
    return str(path)


def load_packet(path: str | Any) -> QuantPacket:
    """Load a packet from a JSON file."""
    from pathlib import Path
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return QuantPacket.from_dict(data)
