#!/usr/bin/env python3
"""Quant Lanes — Discord Bridge.

Maps quant lane packet events to the live runtime's emit_event() system.
This is the integration point between the quant packet system and the
existing Jarvis/OpenClaw Discord event router.

No new event routing infrastructure — reuses runtime/core/discord_event_router.py
exactly as-is.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.discord_event_router import emit_event
from workspace.quant.shared.schemas.packets import QuantPacket


# Map quant packet types to Discord event kinds
_PACKET_TO_EVENT_KIND: dict[str, str] = {
    # Sigma outputs → #sigma or #kitt
    "strategy_rejection_packet": "quant_strategy_rejected",
    "promotion_packet": "quant_strategy_promoted",
    "validation_packet": "quant_validation_completed",
    "papertrade_candidate_packet": "quant_papertrade_candidate",
    "paper_review_packet": "quant_paper_review",
    # Kitt outputs → #kitt
    "brief_packet": "kitt_brief_completed",
    "alert_packet": "quant_alert",
    "setup_packet": "quant_setup",
    "papertrade_request_packet": "quant_papertrade_request",
    # Executor outputs → #kitt (executor has no standalone channel)
    "execution_intent_packet": "quant_execution_intent",
    "execution_status_packet": "quant_execution_status",
    "execution_rejection_packet": "quant_execution_rejected",
    "fill_packet": "quant_fill",
    # Atlas outputs → #kitt (high-value only)
    "candidate_packet": "quant_candidate_submitted",
    # Health → owner channel
    "health_summary": "quant_health",
}

# Which agent_id to use for routing (determines Discord channel)
_LANE_TO_AGENT_ID: dict[str, str] = {
    "kitt": "kitt",
    "sigma": "sigma",
    "atlas": "kitt",        # Atlas escalation goes through Kitt
    "fish": "kitt",         # Fish escalation goes through Kitt
    "hermes": "hermes",
    "executor": "kitt",     # Executor has no standalone channel per spec §19
    "tradefloor": "kitt",   # TradeFloor routes through Kitt
}


def emit_quant_event(
    packet: QuantPacket,
    *,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Emit a quant packet as a Discord event via the live runtime event router.

    Maps packet_type to an event kind, renders a compact message, and routes
    through the existing emit_event() system.

    Returns the emit_event() result dict.
    """
    resolved_root = Path(root or ROOT).resolve()

    kind = _PACKET_TO_EVENT_KIND.get(packet.packet_type)
    if kind is None:
        # Unknown packet type — skip Discord emission
        return {"skipped": True, "reason": f"no event mapping for {packet.packet_type}"}

    agent_id = _LANE_TO_AGENT_ID.get(packet.lane, "kitt")

    # Build detail text from packet
    detail = packet.thesis
    if packet.strategy_id:
        detail = f"[{packet.strategy_id}] {detail}"

    return emit_event(
        kind=kind,
        agent_id=agent_id,
        detail=detail,
        extra={
            "packet_id": packet.packet_id,
            "packet_type": packet.packet_type,
            "lane": packet.lane,
            "strategy_id": packet.strategy_id or "",
            "priority": packet.priority,
        },
        root=resolved_root,
    )


def emit_quant_approval_request(
    strategy_id: str,
    approval_type: str,
    detail: str,
    *,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Emit a quant paper/live trade approval request to #review.

    Uses the existing approval_requested event kind, which the
    discord_event_router routes to the #review channel (archimedes).
    The review poller + inbound server handle operator response.
    """
    resolved_root = Path(root or ROOT).resolve()

    return emit_event(
        kind="approval_requested",
        agent_id="kitt",
        detail=f"Quant {approval_type} approval needed for strategy {strategy_id}. {detail}",
        extra={
            "approval_type": approval_type,
            "strategy_id": strategy_id,
            "source": "quant_lanes",
        },
        root=resolved_root,
    )
