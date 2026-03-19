#!/usr/bin/env python3
"""Quant Lanes — Pulse: Discretionary / TradingView Alert Lane.

Pulse is a separate lane for operator discretionary alerts.
It ingests loose, trader-style alerts (level-only, notes, tags),
clusters them, learns from outcomes, and proposes downstream actions.

Critical rule: Pulse CANNOT inject into Fish/Atlas/Hermes/Sigma/TradeFloor
without explicit operator approval through #review.

Core quant lanes remain autonomous from their own sources.
Pulse is auxiliary evidence, not the main driver.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import make_packet, QuantPacket
from workspace.quant.shared.packet_store import store_packet, list_lane_packets

LANE = "pulse"

# Dedup: alerts within this many points of each other cluster together
_CLUSTER_DISTANCE = 10.0
# Cooldown: minimum seconds between alerts at the same cluster
_CLUSTER_COOLDOWN_SECONDS = 300  # 5 minutes
# Max downstream proposals per cluster per 24h window
_MAX_PROPOSALS_PER_CLUSTER_24H = 2
# Max Atlas seeds from Pulse per 24h
_MAX_ATLAS_SEEDS_24H = 3
# Max Fish context injections per 24h
_MAX_FISH_INJECTIONS_24H = 3

# Tags that can be inferred from freeform alert text
_TAG_PATTERNS = {
    "liquidity": r"\b(liquidity|liq)\b",
    "sweep": r"\b(sweep|swept)\b",
    "reclaim": r"\b(reclaim|reclaimed)\b",
    "breakout": r"\b(breakout|break\s*out|bo)\b",
    "session": r"\b(session|london|ny|asia|open|close)\b",
    "rejection": r"\b(rejection|rejected|rej)\b",
    "support": r"\b(support|demand)\b",
    "resistance": r"\b(resistance|supply)\b",
    "gap": r"\b(gap|imbalance|fvg)\b",
    "vwap": r"\b(vwap)\b",
}


# ---------------------------------------------------------------------------
# Alert parsing — accepts loose, incomplete trader-style input
# ---------------------------------------------------------------------------

def parse_alert(
    text: str,
    symbol: str = "NQ",
    level: Optional[float] = None,
    direction: Optional[str] = None,
    timeframe: Optional[str] = None,
) -> dict:
    """Parse a loose alert into structured form.

    Accepts:
      - just a level: "18450"
      - level + note: "18450 liquidity sweep"
      - freeform: "NQ reclaimed session high, watching 18500"
      - minimal: "support at 450" (relative level)

    Returns dict with: symbol, level, direction, timeframe, tags, note, raw_text
    """
    raw = text.strip()
    tags = set()

    # Infer tags from text
    for tag, pattern in _TAG_PATTERNS.items():
        if re.search(pattern, raw, re.IGNORECASE):
            tags.add(tag)

    # Try to extract a level from text if not provided
    if level is None:
        # Look for numbers that could be price levels (4-5 digit numbers)
        numbers = re.findall(r"\b(\d{4,5}(?:\.\d{1,2})?)\b", raw)
        if numbers:
            level = float(numbers[0])
        else:
            # Try smaller numbers (relative levels like "450")
            small = re.findall(r"\b(\d{2,3}(?:\.\d{1,2})?)\b", raw)
            if small:
                level = float(small[0])

    # Infer direction from text if not provided
    if direction is None:
        text_lower = raw.lower()
        bull = sum(1 for w in ("long", "bull", "bullish", "buy", "support", "demand", "reclaim")
                   if w in text_lower)
        bear = sum(1 for w in ("short", "bear", "bearish", "sell", "resistance", "supply", "rejection")
                   if w in text_lower)
        if bull > bear:
            direction = "bullish"
        elif bear > bull:
            direction = "bearish"

    # Infer symbol from text if different from default
    text_upper = raw.upper()
    for sym in ("NQ", "ES", "YM", "RTY", "CL", "GC", "BTC", "ETH"):
        if sym in text_upper:
            symbol = sym
            break

    return {
        "symbol": symbol,
        "level": level,
        "direction": direction,
        "timeframe": timeframe,
        "tags": sorted(tags),
        "note": raw if raw else None,
        "raw_text": raw,
    }


# ---------------------------------------------------------------------------
# Alert ingestion
# ---------------------------------------------------------------------------

def ingest_alert(
    root: Path,
    text: str = "",
    symbol: str = "NQ",
    level: Optional[float] = None,
    direction: Optional[str] = None,
    timeframe: Optional[str] = None,
    source: str = "tradingview",
) -> tuple[QuantPacket, dict]:
    """Ingest a discretionary alert. Accepts loose input.

    Returns (alert_packet, parsed_alert).
    """
    parsed = parse_alert(text, symbol=symbol, level=level,
                         direction=direction, timeframe=timeframe)

    # Build thesis from parsed data
    parts = []
    if parsed["symbol"]:
        parts.append(parsed["symbol"])
    if parsed["level"] is not None:
        parts.append(f"@ {parsed['level']}")
    if parsed["direction"]:
        parts.append(parsed["direction"])
    if parsed["tags"]:
        parts.append(f"[{', '.join(parsed['tags'])}]")
    thesis = " ".join(parts) if parts else (text[:100] or "Discretionary alert")

    notes_parts = [f"source={source}"]
    if parsed["level"] is not None:
        notes_parts.append(f"level={parsed['level']}")
    if parsed["direction"]:
        notes_parts.append(f"direction={parsed['direction']}")
    if parsed["tags"]:
        notes_parts.append(f"tags={','.join(parsed['tags'])}")
    if parsed["note"]:
        notes_parts.append(f"note={parsed['note'][:200]}")

    pkt = make_packet(
        "pulse_alert_packet", "pulse",
        thesis,
        priority="medium",
        symbol_scope=parsed["symbol"],
        timeframe_scope=parsed["timeframe"],
        confidence=0.5,
        notes="; ".join(notes_parts),
        escalation_level="none",
    )
    store_packet(root, pkt)

    return pkt, parsed


# ---------------------------------------------------------------------------
# Clustering — group alerts near the same level
# ---------------------------------------------------------------------------

def _parse_alert_level(pkt: QuantPacket) -> Optional[float]:
    """Extract level from an alert packet's notes."""
    for part in (pkt.notes or "").split(";"):
        part = part.strip()
        if part.startswith("level="):
            try:
                return float(part.split("=", 1)[1])
            except ValueError:
                pass
    return None


def _parse_alert_tags(pkt: QuantPacket) -> list[str]:
    """Extract tags from an alert packet's notes."""
    for part in (pkt.notes or "").split(";"):
        part = part.strip()
        if part.startswith("tags="):
            return part.split("=", 1)[1].split(",")
    return []


def cluster_alerts(root: Path, max_age_hours: float = 24.0) -> list[dict]:
    """Cluster recent alerts by level proximity.

    Returns list of clusters:
    [{level, symbol, count, alert_ids, tags, direction, first_at, last_at}]
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    alerts = list_lane_packets(root, "pulse", "pulse_alert_packet")

    # Filter to recent
    recent = []
    for a in alerts:
        try:
            if datetime.fromisoformat(a.created_at) > cutoff:
                recent.append(a)
        except (ValueError, TypeError):
            continue

    # Build clusters by level proximity
    clusters: list[dict] = []
    for alert in recent:
        lvl = _parse_alert_level(alert)
        sym = alert.symbol_scope or "NQ"
        tags = _parse_alert_tags(alert)

        merged = False
        for cluster in clusters:
            if cluster["symbol"] != sym:
                continue
            if lvl is not None and cluster["level"] is not None:
                if abs(lvl - cluster["level"]) <= _CLUSTER_DISTANCE:
                    cluster["count"] += 1
                    cluster["alert_ids"].append(alert.packet_id)
                    cluster["tags"] = sorted(set(cluster["tags"] + tags))
                    cluster["last_at"] = alert.created_at
                    # Update level to weighted average
                    cluster["level"] = round(
                        (cluster["level"] * (cluster["count"] - 1) + lvl) / cluster["count"], 2
                    )
                    merged = True
                    break

        if not merged:
            clusters.append({
                "level": lvl,
                "symbol": sym,
                "count": 1,
                "alert_ids": [alert.packet_id],
                "tags": tags,
                "direction": None,
                "first_at": alert.created_at,
                "last_at": alert.created_at,
            })

    # Emit cluster packets for clusters with 2+ alerts
    for cluster in clusters:
        if cluster["count"] >= 2:
            thesis = (
                f"{cluster['symbol']} cluster @ {cluster['level']}: "
                f"{cluster['count']} alerts [{', '.join(cluster['tags'][:5])}]"
            )
            cpkt = make_packet(
                "pulse_cluster_packet", "pulse", thesis,
                priority="medium",
                symbol_scope=cluster["symbol"],
                confidence=min(0.3 + 0.1 * cluster["count"], 0.8),
                evidence_refs=cluster["alert_ids"],
                notes=f"level={cluster['level']}; count={cluster['count']}; tags={','.join(cluster['tags'])}",
            )
            store_packet(root, cpkt)

    return clusters


# ---------------------------------------------------------------------------
# Dedup / anti-spam — cooldown per level cluster
# ---------------------------------------------------------------------------

def check_alert_cooldown(
    root: Path, symbol: str, level: float,
    cooldown_seconds: float = _CLUSTER_COOLDOWN_SECONDS,
) -> bool:
    """Check if an alert at this level is within cooldown. Returns True if blocked."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=cooldown_seconds)
    alerts = list_lane_packets(root, "pulse", "pulse_alert_packet")
    for a in reversed(alerts):
        if a.symbol_scope != symbol:
            continue
        a_level = _parse_alert_level(a)
        if a_level is not None and abs(a_level - level) <= _CLUSTER_DISTANCE:
            try:
                if datetime.fromisoformat(a.created_at) > cutoff:
                    return True  # Within cooldown
            except (ValueError, TypeError):
                continue
    return False


# ---------------------------------------------------------------------------
# Learning — accumulate per-level and per-tag hit rates
# ---------------------------------------------------------------------------

def record_outcome(
    root: Path,
    alert_packet_id: str,
    hit: bool,
    realized_move: Optional[float] = None,
    notes: str = "",
) -> QuantPacket:
    """Record whether an alert's anticipated level was hit or missed."""
    pkt = make_packet(
        "pulse_outcome_packet", "pulse",
        f"Outcome for {alert_packet_id}: {'HIT' if hit else 'MISS'}"
        + (f" (move={realized_move})" if realized_move is not None else ""),
        priority="low",
        evidence_refs=[alert_packet_id],
        notes=f"hit={'true' if hit else 'false'}"
              + (f"; realized_move={realized_move}" if realized_move is not None else "")
              + (f"; note={notes}" if notes else ""),
    )
    store_packet(root, pkt)
    return pkt


def build_learning_state(root: Path) -> dict:
    """Build accumulated learning from outcome history.

    Returns {total_outcomes, hits, misses, hit_rate, per_tag_hits, per_tag_total,
             per_tag_rate, noise_alerts (alerts with no outcome)}.
    """
    outcomes = list_lane_packets(root, "pulse", "pulse_outcome_packet")
    alerts = list_lane_packets(root, "pulse", "pulse_alert_packet")

    total = len(outcomes)
    hits = 0
    misses = 0
    per_tag_hits: dict[str, int] = {}
    per_tag_total: dict[str, int] = {}

    # Build alert_id → tags map
    alert_tags: dict[str, list[str]] = {}
    for a in alerts:
        alert_tags[a.packet_id] = _parse_alert_tags(a)

    # Map outcomes to their alert's tags
    outcome_alert_ids = set()
    for o in outcomes:
        hit = "hit=true" in (o.notes or "")
        if hit:
            hits += 1
        else:
            misses += 1

        for ref in o.evidence_refs:
            outcome_alert_ids.add(ref)
            for tag in alert_tags.get(ref, []):
                per_tag_total[tag] = per_tag_total.get(tag, 0) + 1
                if hit:
                    per_tag_hits[tag] = per_tag_hits.get(tag, 0) + 1

    # Alerts without outcomes = noise candidates
    noise = len([a for a in alerts if a.packet_id not in outcome_alert_ids])

    per_tag_rate = {}
    for tag in per_tag_total:
        per_tag_rate[tag] = round(per_tag_hits.get(tag, 0) / per_tag_total[tag], 2)

    # Emit learning packet
    hit_rate = hits / total if total > 0 else None
    learning_pkt = make_packet(
        "pulse_learning_packet", "pulse",
        f"Pulse learning: {total} outcomes, hit_rate={hit_rate:.0%}" if hit_rate is not None
        else f"Pulse learning: {total} outcomes, no hit rate yet",
        priority="low",
        notes=f"hits={hits}; misses={misses}; noise={noise}; "
              f"tags={json.dumps(per_tag_rate)}",
    )
    store_packet(root, learning_pkt)

    return {
        "total_outcomes": total,
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hit_rate, 3) if hit_rate is not None else None,
        "per_tag_hits": per_tag_hits,
        "per_tag_total": per_tag_total,
        "per_tag_rate": per_tag_rate,
        "noise_alerts": noise,
    }


# ---------------------------------------------------------------------------
# Review-gated downstream proposals
# ---------------------------------------------------------------------------

# Proposal targets
PROPOSAL_TARGETS = {"fish_scenario", "hermes_research", "atlas_seed"}


def _count_recent_proposals(root: Path, target: str, hours: float = 24.0) -> int:
    """Count proposals of a given target type in the time window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    proposals = list_lane_packets(root, "pulse", "pulse_review_proposal_packet")
    count = 0
    for p in proposals:
        notes = p.notes or ""
        if f"target={target}" in notes:
            try:
                if datetime.fromisoformat(p.created_at) > cutoff:
                    count += 1
            except (ValueError, TypeError):
                continue
    return count


def _count_recent_cluster_proposals(root: Path, cluster_level: float,
                                     symbol: str, hours: float = 24.0) -> int:
    """Count proposals from this specific cluster in the time window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    proposals = list_lane_packets(root, "pulse", "pulse_review_proposal_packet")
    count = 0
    for p in proposals:
        notes = p.notes or ""
        if f"cluster_level={cluster_level}" in notes and p.symbol_scope == symbol:
            try:
                if datetime.fromisoformat(p.created_at) > cutoff:
                    count += 1
            except (ValueError, TypeError):
                continue
    return count


def propose_downstream(
    root: Path,
    target: str,
    thesis: str,
    symbol: str = "NQ",
    cluster_level: Optional[float] = None,
    evidence_refs: Optional[list[str]] = None,
    confidence: float = 0.5,
) -> Optional[QuantPacket]:
    """Create a review-gated proposal for downstream quant lane injection.

    target must be one of: fish_scenario, hermes_research, atlas_seed
    Returns the proposal packet, or None if rate-limited.
    """
    if target not in PROPOSAL_TARGETS:
        raise ValueError(f"Invalid proposal target: {target!r}. Must be one of {PROPOSAL_TARGETS}")

    # Check per-cluster cap
    if cluster_level is not None:
        cluster_count = _count_recent_cluster_proposals(root, cluster_level, symbol)
        if cluster_count >= _MAX_PROPOSALS_PER_CLUSTER_24H:
            return None  # Rate limited

    # Check per-target caps
    if target == "atlas_seed":
        if _count_recent_proposals(root, target) >= _MAX_ATLAS_SEEDS_24H:
            return None
    elif target == "fish_scenario":
        if _count_recent_proposals(root, target) >= _MAX_FISH_INJECTIONS_24H:
            return None

    target_labels = {
        "fish_scenario": "Fish scenario context",
        "hermes_research": "Hermes research topic",
        "atlas_seed": "Atlas experiment seed",
    }

    pkt = make_packet(
        "pulse_review_proposal_packet", "pulse",
        f"Pulse proposes → {target_labels[target]}: {thesis}",
        priority="medium",
        symbol_scope=symbol,
        confidence=confidence,
        evidence_refs=evidence_refs or [],
        action_requested=f"Approve to release as {target} to core quant lanes",
        escalation_level="operator_review",
        notes=f"target={target}"
              + (f"; cluster_level={cluster_level}" if cluster_level is not None else "")
              + "; status=pending",
    )
    store_packet(root, pkt)
    return pkt


def approve_proposal(root: Path, proposal_packet_id: str) -> Optional[QuantPacket]:
    """Approve a review proposal and emit the downstream packet.

    Returns the downstream packet, or None if proposal not found.
    """
    proposals = list_lane_packets(root, "pulse", "pulse_review_proposal_packet")
    proposal = None
    for p in proposals:
        if p.packet_id == proposal_packet_id:
            proposal = p
            break

    if proposal is None:
        return None

    # Parse target from notes
    target = None
    for part in (proposal.notes or "").split(";"):
        part = part.strip()
        if part.startswith("target="):
            target = part.split("=", 1)[1]

    if not target or target not in PROPOSAL_TARGETS:
        return None

    # Emit the downstream packet into the target lane
    if target == "fish_scenario":
        downstream = make_packet(
            "scenario_packet", "fish",
            f"[from Pulse] {proposal.thesis}",
            priority="medium",
            symbol_scope=proposal.symbol_scope,
            confidence=proposal.confidence,
            evidence_refs=[proposal.packet_id],
            notes="source=pulse_approved",
        )
    elif target == "hermes_research":
        downstream = make_packet(
            "research_request_packet", "hermes",
            f"[from Pulse] {proposal.thesis}",
            priority="medium",
            symbol_scope=proposal.symbol_scope,
            evidence_refs=[proposal.packet_id],
            notes="source=pulse_approved",
            action_requested="Hermes: research this Pulse-originated topic",
        )
    elif target == "atlas_seed":
        downstream = make_packet(
            "idea_packet", "atlas",
            f"[from Pulse] {proposal.thesis}",
            priority="low",
            symbol_scope=proposal.symbol_scope,
            confidence=proposal.confidence,
            evidence_refs=[proposal.packet_id],
            notes="source=pulse_approved",
        )
    else:
        return None

    store_packet(root, downstream)
    return downstream


# ---------------------------------------------------------------------------
# Health summary
# ---------------------------------------------------------------------------

def emit_health_summary(root: Path, period_start: str, period_end: str) -> QuantPacket:
    """Emit Pulse health summary."""
    alerts = list_lane_packets(root, "pulse", "pulse_alert_packet")
    clusters = list_lane_packets(root, "pulse", "pulse_cluster_packet")
    outcomes = list_lane_packets(root, "pulse", "pulse_outcome_packet")
    proposals = list_lane_packets(root, "pulse", "pulse_review_proposal_packet")

    pkt = make_packet(
        "health_summary", "pulse",
        f"Pulse health: {len(alerts)} alerts, {len(clusters)} clusters, "
        f"{len(outcomes)} outcomes, {len(proposals)} proposals",
        priority="low",
        period_start=period_start,
        period_end=period_end,
        packets_produced=len(alerts) + len(clusters) + len(outcomes) + len(proposals),
    )
    store_packet(root, pkt)
    return pkt
