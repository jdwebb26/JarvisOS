#!/usr/bin/env python3
"""Quant Lanes — Kitt Brief Producer.

Reads packets from all quant lanes via shared/latest/ and produces
operator-facing briefs per spec §7 format.

Kitt is the single operator-facing interface. Briefs must be structured
and scannable.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import make_packet, QuantPacket
from workspace.quant.shared.packet_store import store_packet, get_latest, get_all_latest
from workspace.quant.shared.registries.strategy_registry import load_all_strategies


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _count_strategies_by_state(root: Path) -> dict[str, list[str]]:
    """Count strategies grouped by lifecycle state."""
    strategies = load_all_strategies(root)
    by_state: dict[str, list[str]] = {}
    for sid, s in strategies.items():
        by_state.setdefault(s.lifecycle_state, []).append(sid)
    return by_state


def _lane_summary(latest: dict[str, QuantPacket], lane: str) -> str:
    """Extract 1-line summary for a lane from latest packets."""
    # Look for the most relevant packet from this lane
    for key, pkt in latest.items():
        if pkt.lane == lane:
            return f"{pkt.packet_type}: {pkt.thesis[:100]}"
    return "no recent packets"


def _execution_summary(latest: dict[str, QuantPacket]) -> Optional[str]:
    """Build execution section if executor packets exist."""
    exec_pkts = [p for p in latest.values() if p.lane == "executor"]
    if not exec_pkts:
        return None
    lines = []
    for p in exec_pkts:
        mode = p.execution_mode or "unknown"
        status = p.execution_status or "unknown"
        sid = p.strategy_id or "unknown"
        lines.append(f"  {sid}: mode={mode}, status={status}")
        if p.fill_price:
            lines.append(f"    fill={p.fill_price}, slippage={p.slippage}")
    return "\n".join(lines)


def _tradefloor_summary(latest: dict[str, QuantPacket]) -> Optional[str]:
    """Build tradefloor section if tradefloor packets exist."""
    tf = None
    for key, pkt in latest.items():
        if pkt.packet_type == "tradefloor_packet":
            tf = pkt
    if tf is None:
        return None
    tier = tf.agreement_tier if tf.agreement_tier is not None else "N/A"
    return f"  Agreement tier: {tier}\n  Key finding: {tf.thesis[:120]}"


def produce_brief(root: Path, market_read: str = "No live market data consumed.") -> QuantPacket:
    """Produce a Kitt brief packet from current lane state.

    Per spec §7: structured, scannable, includes all relevant sections.
    """
    ts = _now_ts()
    latest = get_all_latest(root)
    by_state = _count_strategies_by_state(root)

    # Build sections
    paper_active = by_state.get("PAPER_ACTIVE", [])
    paper_queued = by_state.get("PAPER_QUEUED", [])
    live_active = by_state.get("LIVE_ACTIVE", [])
    near_promotion = by_state.get("PROMOTED", []) + by_state.get("PAPER_REVIEW", [])

    pipeline_section = (
        f"  PAPER_ACTIVE: {len(paper_active)} strategies ({', '.join(paper_active) or 'none'})\n"
        f"  PAPER_QUEUED: {len(paper_queued)} strategies ({', '.join(paper_queued) or 'none'})\n"
        f"  LIVE_ACTIVE:  {len(live_active)} strategies ({', '.join(live_active) or 'none'})\n"
        f"  Near promotion: {', '.join(near_promotion) or 'none'}"
    )

    # Top signal — find the highest-priority recent packet
    top_signal = "No high-priority signals."
    high_priority_pkts = [p for p in latest.values() if p.priority in {"high", "critical"}]
    if high_priority_pkts:
        top = max(high_priority_pkts, key=lambda p: (p.priority == "critical", p.created_at))
        top_signal = f"[{top.lane}/{top.packet_type}] {top.thesis[:150]}"

    # Lane activity
    lane_lines = []
    for lane in ["atlas", "fish", "sigma", "hermes"]:
        summary = _lane_summary(latest, lane)
        lane_lines.append(f"  {lane.capitalize():8s}: {summary}")
    lane_section = "\n".join(lane_lines)

    # Execution section
    exec_section = _execution_summary(latest)

    # TradeFloor section
    tf_section = _tradefloor_summary(latest)

    # Build brief text
    brief_text = f"""KITT BRIEF — {ts}
━━━━━━━━━━━━━━━━━━━━━━━━━

MARKET READ
{market_read}

TOP SIGNAL
{top_signal}

PIPELINE
{pipeline_section}

LANE ACTIVITY
{lane_section}"""

    if tf_section:
        brief_text += f"\n\nTRADEFLOOR\n{tf_section}"

    if exec_section:
        brief_text += f"\n\nEXECUTION\n{exec_section}"

    brief_text += f"""

SYSTEM HEALTH
  Active lanes: {', '.join(sorted(set(p.lane for p in latest.values()))) or 'none'}
  Silent/errored: checking...
  Governor: not yet active

OPERATOR ACTION NEEDED
  {'none' if not near_promotion else ', '.join(near_promotion) + ' — may need paper trade decision'}"""

    # Create and store the brief packet
    brief = make_packet(
        "brief_packet", "kitt",
        f"Kitt brief at {ts}. Pipeline: {len(paper_active)} paper-active, {len(live_active)} live-active.",
        priority="medium",
        notes=brief_text,
        escalation_level="none",
    )

    store_packet(root, brief)
    return brief


def produce_execution_summary(
    root: Path,
    strategy_id: str,
    mode: str,
    status: str,
    trade_count: int = 0,
    pnl: float = 0.0,
    drawdown: float = 0.0,
    slippage: float = 0.0,
    anomalies: str = "none",
    next_review: str = "",
) -> str:
    """Produce spec §7 execution summary format string."""
    return f"""EXECUTION UPDATE — {strategy_id}
Mode: {mode}
Status: {status}
Trades: {trade_count} | PnL: {pnl} | Drawdown: {drawdown}
Slippage: {slippage}
Anomalies: {anomalies}
Next review: {next_review}"""
