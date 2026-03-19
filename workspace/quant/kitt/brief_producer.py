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
from workspace.quant.shared.registries.approval_registry import load_all_approvals


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _strategies_by_state(root: Path) -> dict[str, list[str]]:
    strategies = load_all_strategies(root)
    by_state: dict[str, list[str]] = {}
    for sid, s in strategies.items():
        by_state.setdefault(s.lifecycle_state, []).append(sid)
    return by_state


def _pipeline_section(by_state: dict[str, list[str]], root: Path) -> str:
    lines = []
    paper_active = by_state.get("PAPER_ACTIVE", [])
    live_active = by_state.get("LIVE_ACTIVE", [])
    if paper_active:
        lines.append(f"  PAPER: {', '.join(paper_active)}")
    if live_active:
        lines.append(f"  LIVE:  {', '.join(live_active)}")
    if not paper_active and not live_active:
        lines.append("  No active positions")

    promoted = by_state.get("PROMOTED", [])
    queued = by_state.get("PAPER_QUEUED", [])
    review = by_state.get("PAPER_REVIEW", [])
    approvals = load_all_approvals(root)
    for sid in promoted:
        has_appr = any(a.strategy_id == sid and not a.revoked for a in approvals)
        if has_appr:
            ref = next(a.approval_ref for a in approvals if a.strategy_id == sid and not a.revoked)
            lines.append(f"  AWAITING APPROVAL: {sid} ({ref})")
        else:
            lines.append(f"  PROMOTED: {sid} (needs paper request)")
    for sid in queued:
        lines.append(f"  PAPER_QUEUED: {sid}")
    for sid in review:
        lines.append(f"  PAPER_REVIEW: {sid}")

    ideas = len(by_state.get("IDEA", []))
    candidates = len(by_state.get("CANDIDATE", []))
    rejected = len(by_state.get("REJECTED", []))
    if ideas + candidates + rejected > 0:
        lines.append(f"  Depth: {ideas} ideas, {candidates} candidates, {rejected} rejected")
    return "\n".join(lines) if lines else "  Empty pipeline"


def _exec_section(latest: dict[str, QuantPacket]) -> Optional[str]:
    pkt = None
    for key, p in latest.items():
        if p.packet_type == "execution_status_packet":
            pkt = p
    if pkt is None:
        return None
    sid = pkt.strategy_id or "?"
    line = f"  {sid}: {pkt.execution_mode or '?'} {pkt.execution_status or '?'}"
    if pkt.fill_price is not None:
        line += f" @ {pkt.fill_price}"
    if pkt.slippage is not None:
        line += f" (slip {pkt.slippage:.4f})"
    return line


def _top_signal(latest: dict[str, QuantPacket]) -> str:
    for ptype in ["execution_rejection_packet", "promotion_packet",
                   "paper_review_packet", "papertrade_candidate_packet"]:
        for key, pkt in latest.items():
            if pkt.packet_type == ptype:
                return f"[{pkt.lane}] {pkt.thesis[:140]}"
    high = [p for p in latest.values() if p.priority in {"high", "critical"}]
    if high:
        top = max(high, key=lambda p: (p.priority == "critical", p.created_at))
        return f"[{top.lane}] {top.thesis[:140]}"
    return "No high-priority signals."


def _lane_activity(latest: dict[str, QuantPacket]) -> str:
    lines = []
    for lane in ["sigma", "atlas", "hermes", "fish"]:
        pkts = [(k, p) for k, p in latest.items() if p.lane == lane]
        if pkts:
            _, best = max(pkts, key=lambda x: x[1].created_at)
            label = best.packet_type.replace("_packet", "").replace("_", " ")
            lines.append(f"  {lane:8s} {label}: {best.thesis[:80]}")
        else:
            lines.append(f"  {lane:8s} silent")
    return "\n".join(lines)


def _operator_actions(by_state: dict[str, list[str]], root: Path) -> str:
    actions = []
    promoted = by_state.get("PROMOTED", [])
    approvals = load_all_approvals(root)
    for sid in promoted:
        pending = [a for a in approvals if a.strategy_id == sid and not a.revoked]
        if pending:
            actions.append(f"Approve paper: approve {pending[-1].approval_ref}")
        else:
            actions.append(f"Request paper: quant_lanes.py request-paper {sid}")
    for sid in by_state.get("PAPER_REVIEW", []):
        actions.append(f"Review paper results: {sid}")
    return "\n".join(f"  {a}" for a in actions) if actions else "  none"


def produce_brief(root: Path, market_read: str = "No live market data.") -> QuantPacket:
    """Produce a Kitt brief. Spec section 7, phone-scannable."""
    ts = _now_ts()
    latest = get_all_latest(root)
    by_state = _strategies_by_state(root)
    paper_active = by_state.get("PAPER_ACTIVE", [])
    live_active = by_state.get("LIVE_ACTIVE", [])

    exec_section = _exec_section(latest)
    lanes = sorted(set(p.lane for p in latest.values()))

    brief_text = f"""KITT BRIEF — {ts}
━━━━━━━━━━━━━━━━━━━━━━━━━

MARKET READ
{market_read}

TOP SIGNAL
{_top_signal(latest)}

PIPELINE
{_pipeline_section(by_state, root)}"""

    if exec_section:
        brief_text += f"\n\nEXECUTION\n{exec_section}"

    # TradeFloor section — surface synthesis for operator if present
    tf_pkt = None
    for key, pkt in latest.items():
        if pkt.packet_type == "tradefloor_packet":
            tf_pkt = pkt
    if tf_pkt is not None:
        tier = tf_pkt.agreement_tier if tf_pkt.agreement_tier is not None else "?"
        brief_text += f"\n\nTRADEFLOOR\n  Agreement tier: {tier}\n  {tf_pkt.thesis[:120]}"

    # Check delivery health for HEALTH section
    from workspace.quant.shared.discord_bridge import check_delivery_health
    dh = check_delivery_health()
    dh_problems = [k for k, v in dh.items() if v != "ok"]
    delivery_line = "  Delivery: all channels ok" if not dh_problems else f"  Delivery: {', '.join(dh_problems)} missing webhook (worklog mirror active)"

    brief_text += f"""

LANES
{_lane_activity(latest)}

HEALTH
  Active: {', '.join(lanes) if lanes else 'none'}
{delivery_line}
  Governor: not yet active

OPERATOR ACTION NEEDED
{_operator_actions(by_state, root)}"""

    brief = make_packet(
        "brief_packet", "kitt",
        f"Kitt brief {ts}. {len(paper_active)} paper, {len(live_active)} live.",
        priority="medium",
        notes=brief_text,
        escalation_level="none",
    )
    store_packet(root, brief)
    return brief
