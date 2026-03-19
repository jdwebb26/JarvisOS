#!/usr/bin/env python3
"""Salmon event consumer — triggers Fish scenario refresh on Kitt events.

Reads pending Kitt events from the event queue, runs scenario generation
for each meaningful event, and marks events as processed.

This is additive to the existing Salmon timer. The timer continues to run
on its 10-minute cadence. This consumer forces an immediate refresh when
Kitt emits a meaningful state change.

Usage:
    python3 workspace/quant_infra/salmon/event_consumer.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from events.emitter import read_pending, mark_processed
from salmon.adapter import run_scenario_generation


# Event types that should trigger a scenario refresh
TRIGGER_EVENTS = {
    "position_opened",
    "position_closed",
    "stop_triggered",
    "target_hit",
    "thesis_changed",
}


def consume_kitt_events() -> int:
    """Process pending Kitt events and trigger scenario refresh.

    Returns number of events processed.
    """
    pending = read_pending("kitt")
    if not pending:
        print("[salmon-consumer] No pending Kitt events.")
        return 0

    actionable = [e for e in pending if e.get("event_type") in TRIGGER_EVENTS]
    if not actionable:
        # Mark non-actionable events as processed too
        for e in pending:
            mark_processed("kitt", e["event_id"])
        print(f"[salmon-consumer] {len(pending)} pending events, none actionable. Marked processed.")
        return 0

    print(f"[salmon-consumer] {len(actionable)} actionable Kitt event(s). Running scenario refresh...")

    # Run scenario generation once for the batch (idempotent)
    try:
        scenarios = run_scenario_generation()
        print(f"[salmon-consumer] Scenario refresh complete: {len(scenarios)} scenarios generated.")
    except Exception as exc:
        print(f"[salmon-consumer] ERROR during scenario refresh: {exc}")
        # Still mark events as processed to avoid infinite retry
        # The next timer cycle will regenerate anyway

    # Mark all pending events as processed
    for e in pending:
        mark_processed("kitt", e["event_id"])
        print(f"[salmon-consumer] Processed: {e['event_id']} ({e.get('event_type')})")

    return len(actionable)


def main():
    count = consume_kitt_events()
    print(f"[salmon-consumer] Done. Processed {count} event(s).")


if __name__ == "__main__":
    main()
