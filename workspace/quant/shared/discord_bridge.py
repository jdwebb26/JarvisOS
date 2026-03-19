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
    # Atlas outputs → #atlas
    "candidate_packet": "quant_candidate_submitted",
    # Fish outputs → #fish
    "scenario_packet": "quant_scenario_submitted",
    # Pulse outputs → #pulse
    "pulse_alert_packet": "quant_pulse_alert",
    "pulse_cluster_packet": "quant_pulse_cluster",
    "pulse_review_proposal_packet": "quant_pulse_proposal",
    "pulse_learning_packet": "quant_pulse_learning",
    # Health → owner channel
    "health_summary": "quant_health",
}

# Which agent_id to use for routing (determines Discord channel)
_LANE_TO_AGENT_ID: dict[str, str] = {
    "kitt": "kitt",
    "sigma": "sigma",
    "atlas": "atlas",       # Atlas owns #atlas channel
    "fish": "fish",         # Fish owns #fish channel
    "hermes": "hermes",
    "executor": "kitt",     # Executor has no standalone channel per spec §19
    "tradefloor": "kitt",   # TradeFloor routes through Kitt
    "pulse": "pulse",       # Pulse owns #pulse channel
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

    # Build enriched extra fields from packet — richer context for operator messages
    extra: dict[str, Any] = {
        "packet_id": packet.packet_id,
        "packet_type": packet.packet_type,
        "lane": packet.lane,
        "source_lane": packet.lane,
        "strategy_id": packet.strategy_id or "",
        "priority": packet.priority,
        "title": packet.thesis[:80] if packet.thesis else "",
        "confidence": packet.confidence,
        "action_requested": packet.action_requested or "",
    }
    # Quant-specific enrichment for approval-bearing events
    if kind in ("quant_papertrade_request", "quant_pulse_proposal"):
        extra["thesis"] = packet.thesis or ""
        extra["symbol"] = packet.symbol or "NQ"
        extra["risk_limits"] = packet.risk_limits or {}
        extra["sizing"] = packet.sizing or {}
        extra["max_drawdown"] = packet.max_drawdown
        extra["notes"] = packet.notes or ""
        extra["approval_ref"] = packet.approval_ref or ""
    if kind == "quant_pulse_proposal":
        extra["escalation_level"] = packet.escalation_level or "none"

    return emit_event(
        kind=kind,
        agent_id=agent_id,
        detail=detail,
        extra=extra,
        root=resolved_root,
    )


def emit_quant_approval_request(
    strategy_id: str,
    approval_type: str,
    approval_ref: str,
    detail: str,
    *,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Emit a quant paper/live trade approval request to #review.

    Uses the existing approval_requested event kind, which the
    discord_event_router routes to the #review channel (archimedes).
    The approval_id field is set so the rendered message includes
    approve/reject instructions that the review poller can parse.
    """
    resolved_root = Path(root or ROOT).resolve()

    # Live_trade approvals start as pending review; paper_trade are immediate
    if approval_type == "live_trade":
        title = f"Live Trade Approval (pending): {strategy_id}"
        risk = "critical"
    else:
        title = f"{approval_type.replace('_', ' ').title()}: {strategy_id}"
        risk = "high"

    return emit_event(
        kind="approval_requested",
        agent_id="kitt",
        detail=detail,
        extra={
            "approval_id": approval_ref,
            "approval_type": approval_type,
            "strategy_id": strategy_id,
            "source_lane": "quant",
            "title": title,
            "task_type": "quant",
            "risk_level": risk,
        },
        root=resolved_root,
    )


# ---------------------------------------------------------------------------
# Delivery health check
# ---------------------------------------------------------------------------

# Quant-relevant channels to check
_QUANT_DELIVERY_CHANNELS = {
    "sigma":   "JARVIS_DISCORD_WEBHOOK_SIGMA",
    "kitt":    "JARVIS_DISCORD_WEBHOOK_KITT",
    "atlas":   "JARVIS_DISCORD_WEBHOOK_ATLAS",
    "fish":    "JARVIS_DISCORD_WEBHOOK_FISH",
    "review":  "REVIEW_WEBHOOK_URL",
    "worklog": "JARVIS_DISCORD_WEBHOOK_WORKLOG",
    "pulse":   "JARVIS_DISCORD_WEBHOOK_PULSE",
}


def check_delivery_health() -> dict[str, str]:
    """Check whether quant-relevant Discord webhooks are configured.

    Returns {channel_name: "ok" | "missing_webhook"}.
    Reads ~/.openclaw/secrets.env (same source the outbox sender uses).
    """
    import os
    # Load secrets.env the same way systemd EnvironmentFile does
    env_vals: dict[str, str] = {}
    secrets_path = Path.home() / ".openclaw" / "secrets.env"
    if secrets_path.exists():
        for line in secrets_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env_vals[k.strip()] = v.strip()

    result = {}
    for name, env_var in _QUANT_DELIVERY_CHANNELS.items():
        val = env_vals.get(env_var, os.environ.get(env_var, ""))
        if val and val != "REPLACE_ME":
            result[name] = "ok"
        else:
            result[name] = "missing_webhook"
    return result
