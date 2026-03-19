"""Packet writer — create and persist lane output packets.

Every packet follows the standard envelope defined in quant_spine_v1.md.
Packets are written to packets/<lane>/latest.json and optionally timestamped.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PACKETS_DIR = Path(__file__).resolve().parent


def write_packet(
    lane: str,
    packet_type: str,
    summary: str,
    data: dict[str, Any],
    upstream: list[str] | None = None,
    source_module: str = "",
    freshness_hours: float = 0.0,
    confidence: float = 0.5,
    save_timestamped: bool = True,
) -> Path:
    """Write a packet to packets/<lane>/latest.json.

    Args:
        lane: Lane name (scout, hermes, kitt, fish, atlas, sigma)
        packet_type: Packet type identifier
        summary: Human-readable one-liner
        data: Lane-specific structured data
        upstream: List of upstream packet types that fed this
        source_module: Module that produced this packet
        freshness_hours: How old the source data is
        confidence: Confidence level 0-1
        save_timestamped: Also save a timestamped copy

    Returns:
        Path to the latest.json file
    """
    now = datetime.now(timezone.utc)

    packet = {
        "packet_type": f"{lane}_{packet_type}",
        "lane": lane,
        "timestamp": now.isoformat(),
        "version": "1.0.0",
        "summary": summary,
        "upstream": upstream or [],
        "data": data,
        "metadata": {
            "source_module": source_module,
            "data_freshness_hours": freshness_hours,
            "confidence": confidence,
        },
    }

    lane_dir = PACKETS_DIR / lane
    lane_dir.mkdir(parents=True, exist_ok=True)

    # Write latest
    latest_path = lane_dir / "latest.json"
    latest_path.write_text(json.dumps(packet, indent=2, default=str) + "\n")

    # Write timestamped copy
    if save_timestamped:
        ts = now.strftime("%Y%m%dT%H%M%S")
        ts_path = lane_dir / f"{lane}_{packet_type}_{ts}.json"
        ts_path.write_text(json.dumps(packet, indent=2, default=str) + "\n")

    return latest_path


def read_packet(lane: str) -> dict | None:
    """Read the latest packet for a lane."""
    path = PACKETS_DIR / lane / "latest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def read_all_latest() -> dict[str, dict]:
    """Read all latest packets across lanes."""
    result = {}
    for lane_dir in PACKETS_DIR.iterdir():
        if lane_dir.is_dir() and (lane_dir / "latest.json").exists():
            try:
                result[lane_dir.name] = json.loads((lane_dir / "latest.json").read_text())
            except (json.JSONDecodeError, OSError):
                continue
    return result
