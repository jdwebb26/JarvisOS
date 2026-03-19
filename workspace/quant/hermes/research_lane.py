#!/usr/bin/env python3
"""Quant Lanes — Hermes Research Intake Lane.

Per spec §6: external research feeder.

Direction set by research_request_packets from other lanes or operator.
Without requests, follows shared/config/watch_list.json.
Dedup: skip same source within configurable window (default 24h) unless re-requested.

Hermes should not: make quant decisions, validate, spam operator, self-direct indefinitely.

Host placement: mixed primary, either overflow (spec §2). Low compute, mostly I/O.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import make_packet, QuantPacket
from workspace.quant.shared.packet_store import store_packet, get_latest, list_lane_packets
from workspace.quant.shared.scheduler.scheduler import (
    heavy_job_slot, check_capacity, resolve_host,
)
from workspace.quant.shared.governor import evaluate_cycle, get_lane_params

LANE = "hermes"
DEFAULT_DEDUP_HOURS = 24


def _load_watch_list(root: Path) -> list[dict]:
    """Load the watch list config."""
    path = root / "workspace" / "quant" / "shared" / "config" / "watch_list.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _recent_sources(root: Path, hours: int = DEFAULT_DEDUP_HOURS) -> set[str]:
    """Get sources researched within the dedup window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sources = set()
    for pkt in list_lane_packets(root, "hermes", "research_packet"):
        try:
            created = datetime.fromisoformat(pkt.created_at)
            if created > cutoff and pkt.notes:
                for part in pkt.notes.split(";"):
                    part = part.strip()
                    if part.startswith("source="):
                        sources.add(part.split("=", 1)[1])
        except (ValueError, TypeError):
            continue
    return sources


def check_dedup(root: Path, source: str, hours: int = DEFAULT_DEDUP_HOURS) -> bool:
    """Check if a source was already researched within the dedup window.

    Returns True if the source is a duplicate (should skip).
    """
    return source in _recent_sources(root, hours)


# Confidence adjustment by source type (spec §9)
SOURCE_QUALITY = {
    "official_doc": 1.0,
    "api": 0.9,
    "article": 0.7,
    "repo": 0.7,
    "web": 0.5,
    "social": 0.3,
}


def emit_research(
    root: Path,
    thesis: str,
    source: str,
    source_type: str = "web",
    symbol_scope: Optional[str] = None,
    confidence: float = 0.5,
    evidence_refs: Optional[list[str]] = None,
    requested_by: Optional[str] = None,
    force: bool = False,
) -> Optional[QuantPacket]:
    """Emit a research_packet. Respects dedup unless force=True.

    Returns None if deduped (skipped).
    """
    if not force and check_dedup(root, source):
        return None

    quality_mult = SOURCE_QUALITY.get(source_type, 0.5)
    adjusted_confidence = confidence * quality_mult

    notes_parts = [f"source={source}", f"source_type={source_type}"]
    if requested_by:
        notes_parts.append(f"requested_by={requested_by}")

    pkt = make_packet(
        "research_packet", "hermes",
        thesis,
        priority="medium",
        symbol_scope=symbol_scope,
        confidence=adjusted_confidence,
        evidence_refs=evidence_refs or [],
        notes="; ".join(notes_parts),
        escalation_level="none",
    )
    store_packet(root, pkt)
    return pkt


def emit_dataset(
    root: Path,
    thesis: str,
    dataset_name: str,
    source: str,
    source_type: str = "api",
    symbol_scope: Optional[str] = None,
    confidence: float = 0.6,
    evidence_refs: Optional[list[str]] = None,
) -> Optional[QuantPacket]:
    """Emit a dataset_packet referencing acquired/discovered dataset.

    Respects dedup on source.
    """
    if check_dedup(root, source):
        return None

    quality_mult = SOURCE_QUALITY.get(source_type, 0.5)
    pkt = make_packet(
        "dataset_packet", "hermes",
        thesis,
        priority="medium",
        symbol_scope=symbol_scope,
        confidence=confidence * quality_mult,
        evidence_refs=evidence_refs or [],
        notes=f"source={source}; source_type={source_type}; dataset={dataset_name}",
        escalation_level="none",
    )
    store_packet(root, pkt)
    return pkt


def emit_repo(
    root: Path,
    thesis: str,
    repo_url: str,
    source_type: str = "repo",
    symbol_scope: Optional[str] = None,
    confidence: float = 0.5,
    evidence_refs: Optional[list[str]] = None,
) -> Optional[QuantPacket]:
    """Emit a repo_packet referencing a discovered code repository.

    Respects dedup on repo_url.
    """
    if check_dedup(root, repo_url):
        return None

    quality_mult = SOURCE_QUALITY.get(source_type, 0.5)
    pkt = make_packet(
        "repo_packet", "hermes",
        thesis,
        priority="low",
        symbol_scope=symbol_scope,
        confidence=confidence * quality_mult,
        evidence_refs=evidence_refs or [],
        notes=f"source={repo_url}; source_type={source_type}",
        escalation_level="none",
    )
    store_packet(root, pkt)
    return pkt


def emit_theme(
    root: Path,
    thesis: str,
    theme_name: str,
    source: str = "synthesis",
    confidence: float = 0.5,
    evidence_refs: Optional[list[str]] = None,
) -> QuantPacket:
    """Emit a theme_packet identifying a macro research theme.

    Themes are synthesis outputs so they don't dedup on source.
    """
    pkt = make_packet(
        "theme_packet", "hermes",
        thesis,
        priority="medium",
        confidence=confidence,
        evidence_refs=evidence_refs or [],
        notes=f"source={source}; theme={theme_name}",
        escalation_level="none",
    )
    store_packet(root, pkt)
    return pkt


def process_research_request(
    root: Path,
    request_packet: QuantPacket,
) -> Optional[QuantPacket]:
    """Process a research_request_packet from another lane."""
    notes = request_packet.notes or ""
    source = ""
    for part in notes.split(";"):
        part = part.strip()
        if part.startswith("source="):
            source = part.split("=", 1)[1]

    if not source:
        source = f"request-{request_packet.packet_id}"

    return emit_research(
        root,
        thesis=request_packet.thesis,
        source=source,
        requested_by=request_packet.lane,
        symbol_scope=request_packet.symbol_scope,
        evidence_refs=[request_packet.packet_id],
    )


def emit_research_request(
    root: Path,
    requesting_lane: str,
    thesis: str,
    source: Optional[str] = None,
    symbol_scope: Optional[str] = None,
) -> QuantPacket:
    """Emit a research_request_packet from any lane to Hermes."""
    pkt = make_packet(
        "research_request_packet", requesting_lane,
        thesis,
        priority="medium",
        symbol_scope=symbol_scope,
        action_requested="Hermes: research this topic",
        notes=f"source={source}" if source else None,
        escalation_level="none",
    )
    store_packet(root, pkt)
    return pkt


def run_research_batch(
    root: Path,
    requests: list[dict],
) -> tuple[list[QuantPacket], dict]:
    """Run a batch of research with scheduler-aware control.

    Each entry: {thesis, source, source_type?, ...}
    Returns (emitted_packets, scheduler_info).

    Note: most Hermes work is light I/O, but batches with LLM synthesis are heavy.
    """
    scheduler_info = {"acquired": False, "host": "", "waited": False, "emitted": 0, "skipped": 0, "deduped": 0}

    with heavy_job_slot(root, LANE) as slot:
        scheduler_info["acquired"] = slot.acquired
        scheduler_info["host"] = slot.host
        scheduler_info["waited"] = slot.waited

        if not slot.acquired:
            scheduler_info["skipped"] = len(requests)
            return [], scheduler_info

        params = get_lane_params(root, LANE)
        if params.get("paused"):
            scheduler_info["skipped"] = len(requests)
            return [], scheduler_info

        max_batch = params.get("batch_size", 1)
        emitted = []
        for r in requests[:max_batch]:
            pkt = emit_research(
                root,
                thesis=r["thesis"],
                source=r["source"],
                source_type=r.get("source_type", "web"),
                symbol_scope=r.get("symbol_scope"),
                confidence=r.get("confidence", 0.5),
            )
            if pkt:
                emitted.append(pkt)
            else:
                scheduler_info["deduped"] = scheduler_info.get("deduped", 0) + 1

        scheduler_info["emitted"] = len(emitted)
        scheduler_info["skipped"] = len(requests) - len(emitted) - scheduler_info.get("deduped", 0)
        return emitted, scheduler_info


def emit_health_summary(
    root: Path,
    period_start: str,
    period_end: str,
    packets_produced: int,
    research_emitted: int = 0,
    requests_processed: int = 0,
    dedup_skips: int = 0,
    error_count: int = 0,
    usefulness_score: float = 0.5,
    efficiency_score: float = 0.5,
    health_score: float = 0.8,
    confidence_score: float = 0.5,
    host_used: str = "mixed",
    scheduler_waits: int = 0,
    batch_size: int = 1,
    cadence_multiplier: float = 1.0,
) -> QuantPacket:
    """Emit Hermes health_summary per spec §10 with governor evaluation."""
    can_start, _, _ = check_capacity(root, LANE)
    gov_action, gov_reason = evaluate_cycle(
        root, LANE,
        usefulness_score=usefulness_score,
        efficiency_score=efficiency_score,
        health_score=health_score,
        confidence_score=confidence_score,
        host_has_capacity=can_start,
    )

    params = get_lane_params(root, LANE)

    pkt = make_packet(
        "health_summary", "hermes",
        f"Hermes health: {research_emitted} research, {requests_processed} requests, {dedup_skips} deduped",
        priority="low",
        period_start=period_start,
        period_end=period_end,
        packets_produced=packets_produced,
        packets_by_type={"research_packet": research_emitted, "research_request_packet": requests_processed},
        escalation_count=0,
        error_count=error_count,
        cloud_bursts=0,
        estimated_cloud_cost=0.0,
        notable_events=f"{dedup_skips} dedup skips" if dedup_skips else "routine",
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
