#!/usr/bin/env python3
"""Quant Lanes — Packet store and shared/latest management.

Handles:
  - Saving packets to lane-specific directories
  - Updating shared/latest/ with the most recent packet per type per lane
  - Reading latest packets for Kitt / TradeFloor synthesis

Per spec §18: shared/latest/ always current.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from workspace.quant.shared.schemas.packets import QuantPacket, save_packet, load_packet


def _quant_dir(root: Path) -> Path:
    return root / "workspace" / "quant"


def _latest_dir(root: Path) -> Path:
    d = _quant_dir(root) / "shared" / "latest"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lane_dir(root: Path, lane: str) -> Path:
    d = _quant_dir(root) / lane
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_packet(root: Path, packet: QuantPacket) -> str:
    """Save a packet to its lane directory AND update shared/latest/.

    Returns the path to the saved packet file.
    """
    # Save to lane directory
    lane_d = _lane_dir(root, packet.lane)
    path = save_packet(packet, lane_d)

    # Update shared/latest/ — keyed by lane-packet_type
    latest_key = f"{packet.lane}_{packet.packet_type}"
    latest_path = _latest_dir(root) / f"{latest_key}.json"
    latest_path.write_text(
        json.dumps(packet.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )

    return path


def get_latest(root: Path, lane: str, packet_type: str) -> Optional[QuantPacket]:
    """Read the latest packet for a lane+type from shared/latest/."""
    latest_key = f"{lane}_{packet_type}"
    path = _latest_dir(root) / f"{latest_key}.json"
    if not path.exists():
        return None
    return load_packet(path)


def get_all_latest(root: Path) -> dict[str, QuantPacket]:
    """Read all latest packets. Returns {key: QuantPacket}."""
    latest_d = _latest_dir(root)
    result = {}
    for f in sorted(latest_d.glob("*.json")):
        try:
            result[f.stem] = load_packet(f)
        except (json.JSONDecodeError, KeyError):
            continue
    return result


def list_lane_packets(root: Path, lane: str, packet_type: Optional[str] = None) -> list[QuantPacket]:
    """List all packets in a lane directory, optionally filtered by type."""
    lane_d = _lane_dir(root, lane)
    packets = []
    for f in sorted(lane_d.glob("*.json")):
        try:
            p = load_packet(f)
            if packet_type is None or p.packet_type == packet_type:
                packets.append(p)
        except (json.JSONDecodeError, KeyError):
            continue
    return packets
