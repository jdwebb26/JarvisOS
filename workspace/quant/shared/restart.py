#!/usr/bin/env python3
"""Quant Lanes — Restart/recovery for Lane B.

Per spec §18: on restart, read own latest + shared/latest/.
Missing state: log gap, start fresh.

This module handles filesystem-based state recovery so that lanes
can restart safely without producing duplicate packets or losing
track of cadence/governor/scheduler state.

All state is in the filesystem. No in-memory singletons.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from workspace.quant.shared.schemas.packets import QuantPacket, load_packet
from workspace.quant.shared.packet_store import get_latest, get_all_latest, list_lane_packets
from workspace.quant.shared.scheduler.scheduler import (
    get_active_jobs, _active_jobs_path, _save_active_jobs, STALE_TIMEOUT_SECONDS,
)
from workspace.quant.shared.governor import load_governor_state


def recover_lane_state(root: Path, lane: str) -> dict:
    """Recover a lane's state from the filesystem after restart.

    Returns a recovery summary:
        latest_packet: most recent packet from this lane in shared/latest
        lane_packet_count: total packets in the lane directory
        governor_params: current governor parameters for this lane
        scheduler_stale_cleared: number of stale jobs cleaned
        cadence_ok: (tradefloor only) whether cadence state file is readable
        gaps: list of issues found
    """
    summary = {
        "lane": lane,
        "latest_packet": None,
        "lane_packet_count": 0,
        "governor_params": {},
        "scheduler_stale_cleared": 0,
        "gaps": [],
    }

    # 1. Read latest packet for this lane
    latest = get_all_latest(root)
    lane_latest = {k: p for k, p in latest.items() if p.lane == lane}
    if lane_latest:
        newest = max(lane_latest.values(), key=lambda p: p.created_at)
        summary["latest_packet"] = newest.packet_id
    else:
        summary["gaps"].append(f"no packets in shared/latest for {lane}")

    # 2. Count lane packets on disk
    lane_dir = root / "workspace" / "quant" / lane
    if lane_dir.exists():
        summary["lane_packet_count"] = len(list(lane_dir.glob("*.json")))
    else:
        summary["gaps"].append(f"lane directory missing: {lane}")

    # 3. Read governor state
    gov = load_governor_state(root)
    if lane in gov:
        summary["governor_params"] = gov[lane]
    else:
        summary["gaps"].append(f"no governor state for {lane}")

    # 4. Clear stale scheduler registrations
    summary["scheduler_stale_cleared"] = clear_stale_scheduler_jobs(root)

    return summary


def clear_stale_scheduler_jobs(root: Path) -> int:
    """Clear stale scheduler registrations from active_jobs.json.

    Called on restart to ensure crashed jobs don't block capacity.
    Returns count of cleared jobs.
    """
    import time
    path = _active_jobs_path(root)
    if not path.exists():
        return 0

    try:
        jobs = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        # Corrupt file — reset
        _save_active_jobs(root, [])
        return 0

    now = time.time()
    before = len(jobs)
    cleaned = [j for j in jobs if (now - j.get("registered_at", 0)) < STALE_TIMEOUT_SECONDS]
    after = len(cleaned)
    _save_active_jobs(root, cleaned)
    return before - after


def check_latest_coherence(root: Path) -> tuple[bool, list[str]]:
    """Verify shared/latest/ is coherent: files parse, lane names valid, no corruption.

    Returns (coherent, issues).
    """
    from workspace.quant.shared.schemas.packets import LANE_NAMES, validate_packet
    issues = []
    latest_dir = root / "workspace" / "quant" / "shared" / "latest"
    if not latest_dir.exists():
        return True, []  # Empty is coherent

    for f in latest_dir.glob("*.json"):
        try:
            pkt = load_packet(f)
            errors = validate_packet(pkt)
            if errors:
                issues.append(f"{f.name}: validation errors: {errors}")
            if pkt.lane not in LANE_NAMES:
                issues.append(f"{f.name}: unknown lane {pkt.lane}")
        except (json.JSONDecodeError, KeyError, Exception) as e:
            issues.append(f"{f.name}: corrupt: {e}")

    return len(issues) == 0, issues


def check_tradefloor_cadence_after_restart(root: Path) -> tuple[bool, float]:
    """Check if TradeFloor cadence state survived restart.

    Returns (can_run, seconds_remaining).
    """
    from workspace.quant.tradefloor.synthesis_lane import check_cadence
    return check_cadence(root)


def check_dedup_state_after_restart(root: Path) -> dict:
    """Check Hermes dedup state after restart.

    Returns {recent_sources: set, count: int} — sources that would be deduped.
    """
    from workspace.quant.hermes.research_lane import _recent_sources
    sources = _recent_sources(root)
    return {"recent_sources": sources, "count": len(sources)}


def check_stale_lanes(root: Path, max_age_hours: float = 24.0) -> dict:
    """Detect lanes that haven't produced a packet recently.

    Returns {lane: {stale: bool, last_packet_age_hours: float, last_packet_id: str}}.
    Silent lanes are broken lanes (spec §1.10).
    """
    from workspace.quant.shared.schemas.packets import LANE_NAMES
    latest = get_all_latest(root)

    # Group by lane, find newest per lane
    lane_newest: dict[str, Optional[QuantPacket]] = {lane: None for lane in LANE_NAMES if lane != "tradefloor"}
    for key, pkt in latest.items():
        lane = pkt.lane
        if lane not in lane_newest:
            continue
        if lane_newest[lane] is None or pkt.created_at > lane_newest[lane].created_at:
            lane_newest[lane] = pkt

    now = datetime.now(timezone.utc)
    result = {}
    for lane, pkt in lane_newest.items():
        if pkt is None:
            result[lane] = {"stale": True, "last_packet_age_hours": None, "last_packet_id": None}
        else:
            try:
                created = datetime.fromisoformat(pkt.created_at)
                age_hours = (now - created).total_seconds() / 3600
            except (ValueError, TypeError):
                age_hours = 999.0
            result[lane] = {
                "stale": age_hours > max_age_hours,
                "last_packet_age_hours": round(age_hours, 1),
                "last_packet_id": pkt.packet_id,
            }
    return result


def check_kill_switch(root: Path) -> dict:
    """Check kill switch state. Returns {engaged, engaged_at, reason}."""
    path = root / "workspace" / "quant" / "shared" / "config" / "kill_switch.json"
    if not path.exists():
        return {"engaged": False, "engaged_at": None, "reason": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "engaged": data.get("engaged", False),
            "engaged_at": data.get("engaged_at"),
            "reason": data.get("reason"),
        }
    except (json.JSONDecodeError, ValueError):
        return {"engaged": False, "engaged_at": None, "reason": None}


def check_atlas_registry_after_restart(root: Path) -> dict:
    """Check Atlas can see existing strategies after restart (won't create dupes).

    Returns {strategy_count, active_ids, terminal_ids}.
    """
    from workspace.quant.shared.registries.strategy_registry import load_all_strategies, TERMINAL_STATES
    strats = load_all_strategies(root)
    active = [sid for sid, s in strats.items() if s.lifecycle_state not in TERMINAL_STATES]
    terminal = [sid for sid, s in strats.items() if s.lifecycle_state in TERMINAL_STATES]
    return {
        "strategy_count": len(strats),
        "active_ids": active,
        "terminal_ids": terminal,
    }
