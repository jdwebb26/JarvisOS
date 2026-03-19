#!/usr/bin/env python3
"""Quant Event Handshake — orchestrates the full chain:

    Kitt event -> Salmon/Fish scenario refresh -> Sigma validation -> Jarvis summary

Each step is bounded, idempotent, and auditable. Safe to rerun.

Usage:
    python3 workspace/quant_infra/handshake.py                # full chain
    python3 workspace/quant_infra/handshake.py --step salmon   # single step
    python3 workspace/quant_infra/handshake.py --step sigma
    python3 workspace/quant_infra/handshake.py --step jarvis
    python3 workspace/quant_infra/handshake.py --status        # show chain state
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

QUANT_INFRA = Path(__file__).resolve().parent
HANDSHAKE_LOG = QUANT_INFRA / "logs" / "handshake"


def run_chain() -> dict:
    """Run the full handshake chain. Returns summary dict."""
    now = datetime.now(timezone.utc)
    results = {"started_at": now.isoformat(), "steps": {}}

    print("=" * 60)
    print(f"  QUANT EVENT HANDSHAKE — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # Step 1: Consume Kitt events -> Salmon scenario refresh
    print("\n[1/3] Salmon: consuming Kitt events + scenario refresh...")
    results["steps"]["salmon"] = _run_salmon()

    # Step 2: Sigma paper-trade validation
    print("\n[2/3] Sigma: paper-trade validation...")
    results["steps"]["sigma"] = _run_sigma()

    # Step 3: Jarvis operator summary refresh
    print("\n[3/3] Jarvis: operator summary refresh...")
    results["steps"]["jarvis"] = _run_jarvis()

    # Write handshake log
    results["completed_at"] = datetime.now(timezone.utc).isoformat()
    _write_handshake_log(results)

    print("\n" + "=" * 60)
    print("  HANDSHAKE COMPLETE")
    for step, info in results["steps"].items():
        status = info.get("status", "unknown")
        icon = "OK" if status == "ok" else "!!"
        print(f"  [{icon}] {step}: {info.get('summary', status)}")
    print("=" * 60)

    return results


def _run_salmon() -> dict:
    """Run Salmon event consumer + scenario refresh."""
    try:
        from salmon.event_consumer import consume_kitt_events
        count = consume_kitt_events()
        return {"status": "ok", "events_processed": count,
                "summary": f"{count} event(s) processed"}
    except Exception as exc:
        print(f"[handshake] Salmon error: {exc}")
        return {"status": "error", "error": str(exc), "summary": f"error: {exc}"}


def _run_sigma() -> dict:
    """Run Sigma paper-trade validation."""
    try:
        from sigma.paper_trade_validator import validate_paper_trade
        result = validate_paper_trade()
        return {"status": "ok", "verdict": result["verdict"],
                "flags": result["flags"],
                "summary": f"verdict={result['verdict']}, {result['flags']} flag(s)"}
    except Exception as exc:
        print(f"[handshake] Sigma error: {exc}")
        return {"status": "error", "error": str(exc), "summary": f"error: {exc}"}


def _run_jarvis() -> dict:
    """Run Jarvis operator summary refresh."""
    try:
        from jarvis.observability import generate_operator_report
        report = generate_operator_report()

        # Write report
        logs_dir = QUANT_INFRA / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        (logs_dir / "latest_operator_report.txt").write_text(report)
        ts = now.strftime("%Y%m%dT%H%M%S")
        (logs_dir / f"operator_report_{ts}.txt").write_text(report)

        return {"status": "ok", "summary": "operator report refreshed"}
    except Exception as exc:
        print(f"[handshake] Jarvis error: {exc}")
        return {"status": "error", "error": str(exc), "summary": f"error: {exc}"}


def get_chain_status() -> dict:
    """Show current state of the handshake chain."""
    from packets.writer import read_packet
    from events.emitter import read_pending, get_latest_event

    status = {}

    # Kitt events
    pending = read_pending("kitt")
    latest = get_latest_event("kitt")
    status["kitt_events"] = {
        "pending_count": len(pending),
        "latest_event": {
            "event_id": latest["event_id"],
            "event_type": latest["event_type"],
            "timestamp": latest["timestamp"],
        } if latest else None,
    }

    # Lane packets
    for lane in ["kitt", "fish", "sigma"]:
        pkt = read_packet(lane)
        if pkt:
            status[f"{lane}_packet"] = {
                "type": pkt.get("packet_type"),
                "timestamp": pkt.get("timestamp"),
                "summary": pkt.get("summary", "")[:80],
            }
        else:
            status[f"{lane}_packet"] = None

    # Latest handshake log
    log_dir = HANDSHAKE_LOG
    if log_dir.exists():
        logs = sorted(log_dir.glob("*.json"), reverse=True)
        if logs:
            try:
                latest_log = json.loads(logs[0].read_text())
                status["last_handshake"] = {
                    "started_at": latest_log.get("started_at"),
                    "completed_at": latest_log.get("completed_at"),
                    "steps": {
                        k: v.get("status") for k, v in latest_log.get("steps", {}).items()
                    },
                }
            except (json.JSONDecodeError, OSError):
                pass

    return status


def _write_handshake_log(results: dict) -> None:
    """Write handshake run log."""
    HANDSHAKE_LOG.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S")
    path = HANDSHAKE_LOG / f"handshake_{ts}.json"
    path.write_text(json.dumps(results, indent=2, default=str) + "\n")
    (HANDSHAKE_LOG / "latest.json").write_text(json.dumps(results, indent=2, default=str) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Quant Event Handshake")
    parser.add_argument("--step", type=str, choices=["salmon", "sigma", "jarvis"],
                        help="Run a single step")
    parser.add_argument("--status", action="store_true", help="Show chain status")
    args = parser.parse_args()

    if args.status:
        status = get_chain_status()
        print(json.dumps(status, indent=2, default=str))
    elif args.step == "salmon":
        _run_salmon()
    elif args.step == "sigma":
        _run_sigma()
    elif args.step == "jarvis":
        _run_jarvis()
    else:
        run_chain()


if __name__ == "__main__":
    main()
