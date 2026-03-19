"""Event emitter — file-based event queue for quant lane handshakes.

Events are JSON files written to events/<lane>/pending/.
Each event captures a meaningful state change worth propagating downstream.

Consumers read from pending/, process, and move to processed/.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

EVENTS_DIR = Path(__file__).resolve().parent


def emit_event(
    lane: str,
    event_type: str,
    *,
    symbol: str = "NQ",
    side: str | None = None,
    entry: float | None = None,
    stop: float | None = None,
    target: float | None = None,
    current_mark: float | None = None,
    position_id: str | None = None,
    reason: str = "",
    source_file: str = "",
    source_packet: str = "",
    extra: dict | None = None,
) -> Path:
    """Emit a structured event to the lane's pending queue.

    Returns the path to the written event file.
    """
    now = datetime.now(timezone.utc)
    event_id = f"evt-{lane[:4]}-{uuid.uuid4().hex[:12]}"

    event = {
        "event_id": event_id,
        "event_type": event_type,
        "timestamp": now.isoformat(),
        "lane": lane,
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "stop": stop,
        "target": target,
        "current_mark": current_mark,
        "position_id": position_id,
        "reason": reason,
        "source_file": source_file,
        "source_packet": source_packet,
    }
    if extra:
        event["extra"] = extra

    pending_dir = EVENTS_DIR / lane / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)

    ts = now.strftime("%Y%m%dT%H%M%S")
    filename = f"{event_type}_{ts}_{event_id}.json"
    path = pending_dir / filename
    path.write_text(json.dumps(event, indent=2, default=str) + "\n")

    print(f"[event] Emitted {event_type} -> {path.name}")
    return path


def read_pending(lane: str) -> list[dict]:
    """Read all pending events for a lane, oldest first."""
    pending_dir = EVENTS_DIR / lane / "pending"
    if not pending_dir.exists():
        return []

    events = []
    for f in sorted(pending_dir.glob("*.json")):
        try:
            events.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return events


def mark_processed(lane: str, event_id: str) -> bool:
    """Move an event from pending/ to processed/."""
    pending_dir = EVENTS_DIR / lane / "pending"
    processed_dir = EVENTS_DIR / lane / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    for f in pending_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if data.get("event_id") == event_id:
                dest = processed_dir / f.name
                f.rename(dest)
                return True
        except (json.JSONDecodeError, OSError):
            continue
    return False


def get_latest_event(lane: str) -> dict | None:
    """Get the most recent event (pending or processed) for a lane."""
    for subdir in ["pending", "processed"]:
        d = EVENTS_DIR / lane / subdir
        if not d.exists():
            continue
        files = sorted(d.glob("*.json"), reverse=True)
        if files:
            try:
                return json.loads(files[0].read_text())
            except (json.JSONDecodeError, OSError):
                continue
    return None
