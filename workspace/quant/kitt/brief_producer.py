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
from workspace.quant.shared.live_approval_state import (
    resolve_live_approval_state as _live_approval_state,
)

_PROOF_MARKERS = ("proof", "smoke", "phase0", "test-", "la-001", "bad-001")


def _is_proof_artifact(strategy_id: str) -> bool:
    sid = strategy_id.lower()
    return any(m in sid for m in _PROOF_MARKERS)


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _strategies_by_state(root: Path) -> dict[str, list[str]]:
    strategies = load_all_strategies(root)
    by_state: dict[str, list[str]] = {}
    for sid, s in strategies.items():
        if _is_proof_artifact(sid):
            continue
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
    live_queued = by_state.get("LIVE_QUEUED", [])
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
    for sid in live_queued:
        la = _live_approval_state(sid, approvals)
        lines.append(f"  LIVE_QUEUED: {sid} — {la['label']}")

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
            if not (p.strategy_id and _is_proof_artifact(p.strategy_id)):
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
                if pkt.strategy_id and _is_proof_artifact(pkt.strategy_id):
                    continue
                return f"[{pkt.lane}] {pkt.thesis[:140]}"
    high = [p for p in latest.values()
            if p.priority in {"high", "critical"}
            and not (p.strategy_id and _is_proof_artifact(p.strategy_id))]
    if high:
        top = max(high, key=lambda p: (p.priority == "critical", p.created_at))
        return f"[{top.lane}] {top.thesis[:140]}"
    return "No high-priority signals."


def _feedback_loops(root: Path, latest: dict[str, QuantPacket]) -> str:
    """Build per-lane feedback loop status. Phone-readable, concise."""
    lines = []

    # Atlas: learning state
    try:
        from workspace.quant.atlas.exploration_lane import build_knowledge
        k = build_knowledge(root)
        rej = k["rejection_count"]
        adapted = k["adapted"]
        banned = len(k["banned_params"])
        lines.append(f"  atlas    {rej} rejections ingested, adapted={adapted}, {banned} banned params")
    except Exception:
        lines.append("  atlas    no data")

    # Fish: calibration track record
    try:
        from workspace.quant.fish.scenario_lane import build_calibration_state, get_pending_forecasts
        cal = build_calibration_state(root)
        pending = get_pending_forecasts(root)
        if cal["total_calibrations"] > 0:
            hr = f"{cal['direction_hit_rate']:.0%}" if cal["direction_hit_rate"] is not None else "?"
            lines.append(
                f"  fish     {cal['total_calibrations']} calibrations, "
                f"hit_rate={hr}, trend={cal['trend']}, "
                f"streak={cal['streak']}, {len(pending)} pending"
            )
        else:
            lines.append(f"  fish     no calibrations yet, {len(pending)} pending forecasts")
    except Exception:
        lines.append("  fish     no data")

    # Sigma: promotion/rejection pressure
    from workspace.quant.shared.packet_store import list_lane_packets
    sigma_rej = list_lane_packets(root, "sigma", "strategy_rejection_packet")
    sigma_promo = list_lane_packets(root, "sigma", "promotion_packet")
    sigma_rej = [p for p in sigma_rej if not (p.strategy_id and _is_proof_artifact(p.strategy_id))]
    sigma_promo = [p for p in sigma_promo if not (p.strategy_id and _is_proof_artifact(p.strategy_id))]
    lines.append(f"  sigma    {len(sigma_promo)} promoted, {len(sigma_rej)} rejected")

    # TradeFloor: last agreement + risk
    tf_pkt = None
    for key, pkt in latest.items():
        if pkt.packet_type == "tradefloor_packet":
            tf_pkt = pkt
    if tf_pkt:
        tier = tf_pkt.agreement_tier if tf_pkt.agreement_tier is not None else "?"
        risk_note = ""
        notes = tf_pkt.notes or ""
        if "risk_zones=" in notes:
            risk_note = " +risk"
        lines.append(f"  floor    tier={tier}{risk_note}")
    else:
        lines.append("  floor    no synthesis yet")

    # Stale lane warnings
    try:
        from workspace.quant.shared.restart import check_stale_lanes
        stale = check_stale_lanes(root)
        stale_names = [lane for lane, info in stale.items() if info["stale"]]
        if stale_names:
            lines.append(f"  ⚠ stale  {', '.join(stale_names)}")
    except Exception:
        pass

    return "\n".join(lines)


def _pulse_section(root: Path) -> Optional[str]:
    """Build Pulse discretionary alert section for the brief.

    Clearly separated from core quant lanes. Shows alert activity,
    proposal lifecycle (pending/approved/rejected), and learning.
    """
    try:
        from workspace.quant.pulse.alert_lane import list_all_proposals
        from workspace.quant.shared.packet_store import list_lane_packets as _list

        alerts = _list(root, "pulse", "pulse_alert_packet")
        clusters = _list(root, "pulse", "pulse_cluster_packet")
        all_proposals = list_all_proposals(root)

        if not alerts and not all_proposals:
            return None

        lines = []
        lines.append(f"  {len(alerts)} alerts, {len(clusters)} clusters")

        # Proposal lifecycle from authoritative state files
        if all_proposals:
            pending = [p for p in all_proposals if p["status"] == "pending"]
            approved = [p for p in all_proposals if p["status"] == "approved"]
            rejected = [p for p in all_proposals if p["status"] == "rejected"]
            lines.append(f"  Proposals: {len(pending)} pending, "
                         f"{len(approved)} approved, {len(rejected)} rejected")
            for p in pending[-2:]:
                lines.append(f"    awaiting: {p['approval_ref']} → {p['target']}")
            for p in approved[-2:]:
                ds = p.get("downstream_packet_id", "?")
                lines.append(f"    released: {p['approval_ref']} → {ds[:35]}")

        # Learning summary (only if outcomes exist)
        outcomes = _list(root, "pulse", "pulse_outcome_packet")
        if outcomes:
            hits = sum(1 for o in outcomes if "hit=true" in (o.notes or ""))
            total = len(outcomes)
            hr = f"{hits/total:.0%}" if total else "?"
            lines.append(f"  Learning: {total} outcomes, hit_rate={hr}")

        return "\n".join(lines)
    except Exception:
        return None


def _proof_section(root: Path, by_state: dict[str, list[str]]) -> Optional[str]:
    """Build proof progress section for active paper runs. Read-only."""
    try:
        from workspace.quant.executor.proof_tracker import (
            get_active_run, evaluate_proof, get_proof_profile,
        )
        from datetime import datetime, timezone as _tz

        paper_active = by_state.get("PAPER_ACTIVE", [])
        paper_review = by_state.get("PAPER_REVIEW", [])
        paper_queued = by_state.get("PAPER_QUEUED", [])
        if not paper_active and not paper_review and not paper_queued:
            return None

        lines = []
        for sid in paper_active:
            run = get_active_run(root, sid)
            if run is None:
                lines.append(f"  {sid}: no active run data")
                continue
            profile = get_proof_profile(root, run.horizon_class)
            try:
                started = datetime.fromisoformat(run.started_at)
                days = (datetime.now(_tz.utc) - started).total_seconds() / 86400
            except (ValueError, TypeError):
                days = 0.0

            result = evaluate_proof(root, run.paper_run_id)
            if result["sufficient"]:
                lines.append(f"  {sid} [{run.horizon_class}]: PROOF READY")
            else:
                blocking = [k for k, v in result["criteria"].items() if not v["met"]]
                trades_pct = min(run.closed_count / profile.min_trades_required, 1.0) if profile.min_trades_required > 0 else 1.0
                days_pct = min(days / profile.min_days_required, 1.0) if profile.min_days_required > 0 else 1.0
                overall = min(trades_pct, days_pct)
                lines.append(
                    f"  {sid} [{run.horizon_class}]: {overall:.0%} "
                    f"({run.closed_count}/{profile.min_trades_required} trades, "
                    f"{days:.0f}/{profile.min_days_required}d) "
                    f"blocked: {', '.join(blocking)}"
                )

        for sid in paper_review:
            lines.append(f"  {sid}: awaiting operator review")

        for sid in paper_queued:
            lines.append(f"  {sid}: queued, not yet trading")

        return "\n".join(lines) if lines else None
    except Exception:
        return None


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

    # Proof-ready runs that need promotion
    try:
        from workspace.quant.executor.proof_tracker import get_active_run
        for sid in by_state.get("PAPER_ACTIVE", []):
            run = get_active_run(root, sid)
            if run and run.proof_status == "sufficient":
                actions.append(f"Proof ready: quant_lanes.py proof-promote {run.paper_run_id}")
    except Exception:
        pass

    # LIVE_QUEUED strategies needing live approval action
    for sid in by_state.get("LIVE_QUEUED", []):
        la = _live_approval_state(sid, approvals)
        actions.append(f"Live: quant_lanes.py {la['action']}")

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

    # Proof tracker section
    proof_text = _proof_section(root, by_state)
    if proof_text:
        brief_text += f"\n\nPROOF PROGRESS\n{proof_text}"

    if exec_section:
        brief_text += f"\n\nEXECUTION\n{exec_section}"

    # TradeFloor section
    tf_pkt = None
    for key, pkt in latest.items():
        if pkt.packet_type == "tradefloor_packet":
            tf_pkt = pkt
    if tf_pkt is not None:
        tier = tf_pkt.agreement_tier if tf_pkt.agreement_tier is not None else "?"
        brief_text += f"\n\nTRADEFLOOR\n  Agreement tier: {tier}\n  {tf_pkt.thesis[:120]}"

    # Pulse section — separate from core quant lanes
    pulse_text = _pulse_section(root)
    if pulse_text:
        brief_text += f"\n\nPULSE (discretionary)\n{pulse_text}"

    # Feedback loops section
    brief_text += f"\n\nFEEDBACK LOOPS\n{_feedback_loops(root, latest)}"

    # Check delivery health for HEALTH section
    from workspace.quant.shared.discord_bridge import check_delivery_health
    dh = check_delivery_health()
    dh_problems = [k for k, v in dh.items() if v != "ok"]
    delivery_line = "  Delivery: all channels ok" if not dh_problems else f"  Delivery: {', '.join(dh_problems)} missing webhook (worklog mirror active)"

    # Governor status
    from workspace.quant.shared.governor import load_governor_state
    gov = load_governor_state(root)
    paused_lanes = [k for k, v in gov.items() if v.get("paused")]
    if paused_lanes:
        governor_line = f"  Governor: active, paused: {', '.join(paused_lanes)}"
    elif gov:
        governor_line = f"  Governor: active ({len(gov)} lanes)"
    else:
        governor_line = "  Governor: no state"

    # Bootstrap status
    bootstrap_line = ""
    try:
        from workspace.quant.bootstrap import get_all_bootstrap_status
        bs = get_all_bootstrap_status(root)
        not_started = [l for l, s in bs.items() if s == "not_started"]
        stale_bs = [l for l, s in bs.items() if s == "stale"]
        if not_started:
            bootstrap_line = f"\n  Bootstrap: NOT STARTED: {', '.join(not_started)}"
        elif stale_bs:
            bootstrap_line = f"\n  Bootstrap: STALE: {', '.join(stale_bs)}"
        else:
            bootstrap_line = "\n  Bootstrap: all lanes active"
    except Exception:
        pass

    brief_text += f"""

HEALTH
  Active: {', '.join(lanes) if lanes else 'none'}
{delivery_line}
{governor_line}{bootstrap_line}

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
