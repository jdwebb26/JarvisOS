#!/usr/bin/env python3
"""Idempotent trigger: emit the latest factory operator_packet if not yet emitted.

The weekly pipeline (Phase 7) already calls emit inline. This script is a
safety net the scheduler can invoke afterwards — it only emits when the
newest operator_packet.json has no matching factory_downstream.json with
the same cycle_id, so repeated calls are harmless.

Usage (scheduler / cron):
    python3 scripts/emit_factory_packet.py
    python3 scripts/emit_factory_packet.py --force   # re-emit even if already done
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.integrations.factory_packet_adapter import (
    FACTORY_ARTIFACT_ROOT,
    FactoryPacketError,
    _discover_newest_packet,
    emit_factory_weekly,
)


def _already_emitted(packet_path: Path) -> bool:
    """Return True if factory_downstream.json exists with matching cycle_id."""
    downstream = packet_path.parent / "factory_downstream.json"
    if not downstream.is_file():
        return False
    try:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        ds = json.loads(downstream.read_text(encoding="utf-8"))
        return ds.get("cycle_id") == packet.get("cycle_id")
    except (json.JSONDecodeError, OSError):
        return False


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Idempotent factory packet emit trigger")
    parser.add_argument("--force", action="store_true", help="Re-emit even if already done")
    args = parser.parse_args()

    try:
        packet_path = _discover_newest_packet(FACTORY_ARTIFACT_ROOT)
    except FactoryPacketError as exc:
        print(f"SKIP: {exc}")
        return 0

    if not args.force and _already_emitted(packet_path):
        print(f"SKIP: already emitted — {packet_path.parent.name}")
        return 0

    print(f"EMIT: {packet_path}")
    result = emit_factory_weekly(path=packet_path)
    ev = result["event_result"]
    print(f"  event:  {ev['event_id']}")
    print(f"  outbox: {len(ev.get('outbox_entries', []))} entries")
    print(f"  brief:  {result['kitt_brief_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
