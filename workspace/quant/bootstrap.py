#!/usr/bin/env python3
"""Quant Lanes — Bootstrap / Cold-Start Logic.

Provides real cold-start behavior for each quant lane so they can begin
operating from empty state without depending on Pulse or manual feeding.

Each lane's bootstrap:
  - Reads its own source config
  - Produces bounded initial packets
  - Respects dedup (safe on repeat runs)
  - Does NOT fabricate history or calibration data

Bootstrap is a one-time ramp, not a replacement for normal cadence.
After bootstrap, lanes transition to their regular cycle behavior.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import QuantPacket
from workspace.quant.shared.packet_store import (
    store_packet, get_latest, get_all_latest, list_lane_packets,
)
from workspace.quant.shared.governor import get_lane_params


# ---------------------------------------------------------------------------
# Bootstrap state tracking
# ---------------------------------------------------------------------------

_BOOTSTRAP_STATE_DIR = "workspace/quant/shared/config"
_BOOTSTRAP_STATE_FILE = "bootstrap_state.json"


def _state_path(root: Path) -> Path:
    d = root / _BOOTSTRAP_STATE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d / _BOOTSTRAP_STATE_FILE


def _load_bootstrap_state(root: Path) -> dict:
    path = _state_path(root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return {}


def _save_bootstrap_state(root: Path, state: dict):
    path = _state_path(root)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _mark_bootstrapped(root: Path, lane: str, packets_emitted: int):
    """Record that a lane has been bootstrapped."""
    state = _load_bootstrap_state(root)
    state[lane] = {
        "bootstrapped_at": datetime.now(timezone.utc).isoformat(),
        "packets_emitted": packets_emitted,
    }
    _save_bootstrap_state(root, state)


def get_lane_bootstrap_status(root: Path, lane: str) -> str:
    """Return bootstrap status for a lane: 'not_started', 'bootstrapped', 'active', 'stale'.

    - not_started: no bootstrap record AND no packets from this lane
    - bootstrapped: bootstrap record exists but few packets beyond bootstrap
    - active: lane has recent packets (within 24h)
    - stale: lane has packets but none recent (>24h)
    """
    state = _load_bootstrap_state(root)

    # Check for recent packets
    latest = get_all_latest(root)
    lane_packets = {k: p for k, p in latest.items() if p.lane == lane}

    has_recent = False
    if lane_packets:
        now = datetime.now(timezone.utc)
        for pkt in lane_packets.values():
            try:
                created = datetime.fromisoformat(pkt.created_at)
                age_hours = (now - created).total_seconds() / 3600
                if age_hours < 24:
                    has_recent = True
                    break
            except (ValueError, TypeError):
                continue

    if has_recent:
        return "active"

    if lane in state:
        if lane_packets:
            return "stale"
        return "bootstrapped"

    if lane_packets:
        return "stale"

    return "not_started"


def get_all_bootstrap_status(root: Path) -> dict[str, str]:
    """Return bootstrap status for all quant lanes."""
    lanes = ["hermes", "fish", "atlas", "tradefloor"]
    return {lane: get_lane_bootstrap_status(root, lane) for lane in lanes}


# ---------------------------------------------------------------------------
# Hermes bootstrap
# ---------------------------------------------------------------------------

def bootstrap_hermes(root: Path) -> dict:
    """Cold-start Hermes from its configured watchlist and sources.

    - Reads watch_list.json
    - Produces bounded initial research packets
    - Respects dedup (safe on repeat runs)

    Returns summary: {emitted, deduped, watchlist_entries, already_bootstrapped}
    """
    from workspace.quant.hermes.research_lane import (
        run_watchlist_batch, emit_research, check_dedup,
    )

    summary = {
        "emitted": 0,
        "deduped": 0,
        "watchlist_entries": 0,
        "already_bootstrapped": False,
    }

    # Check governor
    params = get_lane_params(root, "hermes")
    if params.get("paused"):
        summary["skipped_reason"] = "governor_paused"
        return summary

    # Run watchlist batch — this is Hermes's natural cold-start path
    packets, info = run_watchlist_batch(root)
    summary["emitted"] = info.get("emitted", 0)
    summary["deduped"] = info.get("deduped", 0)
    summary["watchlist_entries"] = info.get("watchlist_entries", 0)

    if summary["emitted"] == 0 and summary["deduped"] > 0:
        summary["already_bootstrapped"] = True

    if summary["emitted"] > 0:
        _mark_bootstrapped(root, "hermes", summary["emitted"])

    return summary


# ---------------------------------------------------------------------------
# Fish bootstrap
# ---------------------------------------------------------------------------

def _load_fish_bootstrap_config(root: Path) -> dict:
    path = root / "workspace" / "quant" / "shared" / "config" / "fish_bootstrap.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return {}


def bootstrap_fish(root: Path) -> dict:
    """Cold-start Fish from its bootstrap config.

    Creates initial regime classification, seed scenarios, and baseline risk map.
    Does NOT fabricate calibration history — starts with honest zero-calibration state.

    Returns summary: {regimes_emitted, scenarios_emitted, risk_maps_emitted, already_bootstrapped}
    """
    from workspace.quant.fish.scenario_lane import (
        emit_scenario, emit_regime, emit_risk_map,
        build_calibration_state, get_scenario_history,
    )

    summary = {
        "regimes_emitted": 0,
        "scenarios_emitted": 0,
        "risk_maps_emitted": 0,
        "already_bootstrapped": False,
    }

    # Check governor
    params = get_lane_params(root, "fish")
    if params.get("paused"):
        summary["skipped_reason"] = "governor_paused"
        return summary

    config = _load_fish_bootstrap_config(root)
    if not config:
        summary["skipped_reason"] = "no_config"
        return summary

    # Check if Fish already has scenario history — don't re-seed
    existing_scenarios = get_scenario_history(root, limit=1)
    existing_regimes = list_lane_packets(root, "fish", "regime_packet")
    existing_risk_maps = list_lane_packets(root, "fish", "risk_map_packet")

    if existing_scenarios and existing_regimes:
        summary["already_bootstrapped"] = True
        return summary

    # Emit seed regimes (if none exist)
    if not existing_regimes:
        for regime in config.get("seed_regimes", []):
            emit_regime(
                root,
                thesis=regime["thesis"],
                regime_label=regime["label"],
                confidence=regime.get("confidence", 0.4),
            )
            summary["regimes_emitted"] += 1

    # Emit seed scenarios (if none exist)
    if not existing_scenarios:
        for scenario in config.get("seed_scenarios", []):
            emit_scenario(
                root,
                thesis=scenario["thesis"],
                symbol_scope=scenario.get("symbol_scope", "NQ"),
                timeframe_scope=scenario.get("timeframe_scope", "1D"),
                confidence=scenario.get("confidence", 0.4),
            )
            summary["scenarios_emitted"] += 1

    # Emit seed risk map (if none exist)
    if not existing_risk_maps:
        seed_zones = config.get("seed_risk_zones")
        if seed_zones:
            emit_risk_map(
                root,
                thesis="Bootstrap risk map: baseline risk zones from config",
                risk_zones=seed_zones,
                symbol_scope="NQ",
                confidence=0.3,
            )
            summary["risk_maps_emitted"] = 1

    total = summary["regimes_emitted"] + summary["scenarios_emitted"] + summary["risk_maps_emitted"]
    if total > 0:
        _mark_bootstrapped(root, "fish", total)

    # Honest calibration state: zero calibrations, no fake history
    cal = build_calibration_state(root)
    summary["calibration_state"] = {
        "total_calibrations": cal["total_calibrations"],
        "trend": cal["trend"],
    }

    return summary


# ---------------------------------------------------------------------------
# Atlas bootstrap
# ---------------------------------------------------------------------------

def _load_atlas_sources(root: Path) -> dict:
    path = root / "workspace" / "quant" / "shared" / "config" / "atlas_sources.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return {}


def _find_hermes_evidence(root: Path) -> list[str]:
    """Find recent Hermes research packet IDs for evidence linkage."""
    packets = list_lane_packets(root, "hermes", "research_packet")
    # Take the most recent few
    return [p.packet_id for p in packets[-5:]]


def bootstrap_atlas(root: Path) -> dict:
    """Cold-start Atlas from configured seed themes + Hermes evidence.

    Bounded: respects max_bootstrap_candidates from config.
    Dedup-aware: skips themes already tried (thesis dedup).

    Returns summary: {candidates_generated, dedup_blocked, skipped_reason, already_bootstrapped}
    """
    from workspace.quant.atlas.exploration_lane import (
        generate_candidate, check_thesis_dedup, DuplicateThesisError,
    )
    from workspace.quant.shared.registries.strategy_registry import load_all_strategies

    summary = {
        "candidates_generated": 0,
        "dedup_blocked": 0,
        "already_bootstrapped": False,
    }

    # Check governor
    params = get_lane_params(root, "atlas")
    if params.get("paused"):
        summary["skipped_reason"] = "governor_paused"
        return summary

    config = _load_atlas_sources(root)
    if not config:
        summary["skipped_reason"] = "no_config"
        return summary

    # Check if Atlas already has candidates — don't re-seed
    existing = load_all_strategies(root)
    real_strategies = {sid: s for sid, s in existing.items()
                       if not any(m in sid.lower() for m in ("proof", "smoke", "test-", "phase0"))}
    if real_strategies:
        summary["already_bootstrapped"] = True
        return summary

    themes = config.get("seed_themes", [])
    max_candidates = config.get("max_bootstrap_candidates", 3)
    require_hermes = config.get("require_hermes_evidence", True)

    # Gather Hermes evidence refs if available
    hermes_refs = _find_hermes_evidence(root)
    if require_hermes and not hermes_refs:
        summary["skipped_reason"] = "no_hermes_evidence"
        return summary

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    for i, theme in enumerate(themes[:max_candidates]):
        prefix = theme.get("strategy_prefix", "atlas-boot")
        short = hashlib.sha256(f"{prefix}-{ts}-{i}".encode()).hexdigest()[:6]
        strategy_id = f"{prefix}-{short}"

        try:
            pkt, feedback = generate_candidate(
                root,
                strategy_id=strategy_id,
                thesis=theme["thesis"],
                symbol_scope=theme.get("symbol_scope", "NQ"),
                timeframe_scope=theme.get("timeframe_scope", "15m"),
                confidence=theme.get("confidence", 0.4),
                evidence_refs=hermes_refs[:3],  # Link to recent Hermes work
            )
            summary["candidates_generated"] += 1
        except DuplicateThesisError:
            summary["dedup_blocked"] += 1
        except ValueError as e:
            # Strategy ID collision or other issue — skip
            summary.setdefault("errors", []).append(str(e))

    if summary["candidates_generated"] > 0:
        _mark_bootstrapped(root, "atlas", summary["candidates_generated"])

    return summary


# ---------------------------------------------------------------------------
# TradeFloor bootstrap check
# ---------------------------------------------------------------------------

def bootstrap_tradefloor(root: Path) -> dict:
    """Check if TradeFloor has enough upstream evidence to synthesize.

    TradeFloor does NOT bootstrap from nothing. It only runs when at least
    2 upstream lanes have real packets.

    Returns summary: {can_synthesize, upstream_lanes, synthesized, reason}
    """
    from workspace.quant.tradefloor.synthesis_lane import synthesize, CadenceRefused

    summary = {
        "can_synthesize": False,
        "upstream_lanes": [],
        "synthesized": False,
    }

    latest = get_all_latest(root)
    upstream_lanes = set()
    for key, pkt in latest.items():
        if pkt.lane not in ("tradefloor", "kitt", "executor"):
            upstream_lanes.add(pkt.lane)

    summary["upstream_lanes"] = sorted(upstream_lanes)

    if len(upstream_lanes) < 2:
        summary["reason"] = f"Insufficient upstream evidence ({len(upstream_lanes)} lanes). Need >= 2."
        return summary

    summary["can_synthesize"] = True

    try:
        pkt = synthesize(root, override_reason="bootstrap: first synthesis after cold start")
        summary["synthesized"] = True
        summary["tier"] = pkt.agreement_tier
        _mark_bootstrapped(root, "tradefloor", 1)
    except CadenceRefused:
        summary["reason"] = "cadence_refused"
    except Exception as e:
        summary["reason"] = str(e)

    return summary


# ---------------------------------------------------------------------------
# Bootstrap all
# ---------------------------------------------------------------------------

def bootstrap_all(root: Path) -> dict:
    """Run bootstrap for all quant lanes in dependency order.

    Order: Hermes first (upstream research), then Fish (scenarios),
    then Atlas (candidates, may use Hermes evidence), then TradeFloor
    (synthesis, only if enough upstream).
    """
    results = {}

    results["hermes"] = bootstrap_hermes(root)
    results["fish"] = bootstrap_fish(root)
    results["atlas"] = bootstrap_atlas(root)
    results["tradefloor"] = bootstrap_tradefloor(root)

    return results
