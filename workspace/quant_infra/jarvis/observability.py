#!/usr/bin/env python3
"""Jarvis Quant Observability — operator-facing summary of quant lane activity.

Reads all lane packets, event queue state, and warehouse state to produce
an operator summary including the quant event handshake chain.

Usage:
    .venv/bin/python3 workspace/quant_infra/jarvis/observability.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packets.writer import read_all_latest, read_packet
from events.emitter import read_pending, get_latest_event

QUANT_INFRA = Path(__file__).resolve().parent.parent
WAREHOUSE_PATH = QUANT_INFRA / "warehouse" / "quant.duckdb"
HANDSHAKE_LOG = QUANT_INFRA / "logs" / "handshake"
VALIDATION_DIR = QUANT_INFRA / "research" / "sigma_validations"


def get_warehouse_summary() -> dict:
    """Get summary counts from DuckDB warehouse."""
    try:
        import duckdb
        con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
        try:
            tables = {}
            for tbl in ["ohlcv_daily", "kitt_paper_positions", "kitt_trade_decisions",
                         "fish_scenarios", "atlas_experiment_inputs",
                         "sigma_validation_inputs", "market_environment_snapshots",
                         "market_news_items", "token_usage"]:
                try:
                    count = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                    tables[tbl] = count
                except Exception:
                    tables[tbl] = "N/A"

            # Paper trading summary
            paper = {}
            try:
                row = con.execute("""
                    SELECT COUNT(*) FILTER (WHERE status = 'open'),
                           COUNT(*) FILTER (WHERE status != 'open'),
                           COALESCE(SUM(pnl) FILTER (WHERE pnl IS NOT NULL), 0)
                    FROM kitt_paper_positions
                """).fetchone()
                paper = {"open": row[0], "closed": row[1], "total_pnl": float(row[2])}
            except Exception:
                pass

            # Active scenarios
            active_scenarios = 0
            try:
                active_scenarios = con.execute(
                    "SELECT COUNT(*) FROM fish_scenarios WHERE status = 'active'"
                ).fetchone()[0]
            except Exception:
                pass

            return {
                "table_counts": tables,
                "paper_trading": paper,
                "active_scenarios": active_scenarios,
            }
        finally:
            con.close()
    except Exception as e:
        return {"error": str(e)}


def get_lane_packet_summary() -> dict:
    """Get summary of all lane packets."""
    packets = read_all_latest()
    summary = {}
    for lane, packet in packets.items():
        summary[lane] = {
            "type": packet.get("packet_type", "unknown"),
            "timestamp": packet.get("timestamp", "unknown"),
            "summary": packet.get("summary", ""),
            "confidence": packet.get("metadata", {}).get("confidence"),
        }
    return summary


def get_event_queue_summary() -> dict:
    """Get summary of Kitt event queue state."""
    pending = read_pending("kitt")
    latest = get_latest_event("kitt")

    processed_dir = QUANT_INFRA / "events" / "kitt" / "processed"
    processed_count = len(list(processed_dir.glob("*.json"))) if processed_dir.exists() else 0

    return {
        "pending": len(pending),
        "processed": processed_count,
        "latest_event": {
            "id": latest["event_id"],
            "type": latest["event_type"],
            "timestamp": latest["timestamp"][:19],
        } if latest else None,
    }


def get_handshake_summary() -> dict | None:
    """Get latest handshake run summary."""
    latest_path = HANDSHAKE_LOG / "latest.json"
    if not latest_path.exists():
        return None
    try:
        data = json.loads(latest_path.read_text())
        return {
            "started_at": data.get("started_at", "?")[:19],
            "completed_at": data.get("completed_at", "?")[:19],
            "steps": {
                k: v.get("status", "?") for k, v in data.get("steps", {}).items()
            },
        }
    except (json.JSONDecodeError, OSError):
        return None


def get_sigma_validation_summary() -> dict | None:
    """Get latest Sigma paper-trade validation summary."""
    sigma_pkt = read_packet("sigma")
    if not sigma_pkt:
        return None

    data = sigma_pkt.get("data", {})
    return {
        "verdict": data.get("verdict", "?"),
        "flags": data.get("flags", 0),
        "positions_checked": data.get("positions_checked", 0),
        "summary": data.get("summary", ""),
        "timestamp": sigma_pkt.get("timestamp", "?")[:19],
    }


def get_fish_scenario_summary() -> dict | None:
    """Get latest Fish scenario summary from packet."""
    fish_pkt = read_packet("fish")
    if not fish_pkt:
        return None

    data = fish_pkt.get("data", {})
    scenarios = data.get("scenarios", [])

    # Summarize by type and impact
    negative = [s for s in scenarios if s.get("impact") == "negative"]
    high_prob = [s for s in scenarios if (s.get("probability") or 0) >= 0.25]

    return {
        "count": data.get("scenario_count", len(scenarios)),
        "negative_count": len(negative),
        "high_prob_count": len(high_prob),
        "market_context": data.get("market_context", {}),
        "timestamp": fish_pkt.get("timestamp", "?")[:19],
    }


def generate_operator_report() -> str:
    """Generate the full operator report."""
    now = datetime.now(timezone.utc)
    warehouse = get_warehouse_summary()
    lane_packets = get_lane_packet_summary()

    report = f"""
================================================================================
  QUANT INFRASTRUCTURE STATUS — {now.strftime('%Y-%m-%d %H:%M UTC')}
================================================================================

WAREHOUSE ({WAREHOUSE_PATH})
"""
    if "table_counts" in warehouse:
        for tbl, count in warehouse["table_counts"].items():
            report += f"  {tbl:35s} {count:>8s}\n" if isinstance(count, str) else f"  {tbl:35s} {count:>8d} rows\n"
    else:
        report += f"  Error: {warehouse.get('error', 'unknown')}\n"

    if warehouse.get("paper_trading"):
        pt = warehouse["paper_trading"]
        report += f"""
KITT PAPER TRADING
  Open positions:  {pt.get('open', 0)}
  Closed trades:   {pt.get('closed', 0)}
  Total PnL:       ${pt.get('total_pnl', 0):.2f}
"""

    report += f"""
FISH SCENARIOS
  Active scenarios: {warehouse.get('active_scenarios', 0)}
"""

    # Event queue
    events = get_event_queue_summary()
    report += f"""
KITT EVENT QUEUE
  Pending events:  {events['pending']}
  Processed:       {events['processed']}
"""
    if events["latest_event"]:
        le = events["latest_event"]
        report += f"  Latest event:    {le['type']} [{le['timestamp']}]\n"

    # Fish scenario detail
    fish = get_fish_scenario_summary()
    if fish:
        report += f"""
FISH SCENARIO DETAIL [{fish['timestamp']}]
  Total scenarios:     {fish['count']}
  Negative impact:     {fish['negative_count']}
  High probability:    {fish['high_prob_count']}
"""

    # Sigma validation
    sigma = get_sigma_validation_summary()
    if sigma:
        verdict_display = sigma["verdict"].upper()
        report += f"""
SIGMA PAPER-TRADE VALIDATION [{sigma['timestamp']}]
  Verdict:  {verdict_display}
  Flags:    {sigma['flags']}
  Checked:  {sigma['positions_checked']} position(s)
  {sigma['summary'][:80]}
"""

    # Handshake chain
    hs = get_handshake_summary()
    if hs:
        steps = "  ".join(f"{k}={v}" for k, v in hs["steps"].items())
        report += f"""
HANDSHAKE CHAIN [{hs['completed_at']}]
  {steps}
"""

    # Circuit breakers
    try:
        sys.path.insert(0, str(QUANT_INFRA.parent.parent))
        from workspace.quant.shared.circuit_breakers import circuit_breaker_summary
        cb = circuit_breaker_summary(QUANT_INFRA.parent.parent)
        if cb["status"] == "tripped":
            report += f"""
CIRCUIT BREAKERS — {cb['count']} TRIPPED ({cb['critical_count']} critical, {cb['warning_count']} warning)
"""
            for t in cb["tripped"]:
                icon = "!!" if t["severity"] == "critical" else "**"
                report += f"  [{icon}] {t['lane']:10s}  {t['breaker']} — {t['detail']}\n"
        else:
            report += "\nCIRCUIT BREAKERS — all clear\n"
    except Exception as exc:
        report += f"\nCIRCUIT BREAKERS — check failed: {exc}\n"

    report += "\nLANE PACKETS\n"
    if lane_packets:
        for lane, info in sorted(lane_packets.items()):
            ts = info.get("timestamp", "?")[:19]
            conf = info.get("confidence")
            conf_str = f" ({conf:.0%})" if conf is not None else ""
            report += f"  {lane:10s}  [{ts}]  {info.get('summary', '')[:70]}{conf_str}\n"
    else:
        report += "  No packets found\n"

    report += "\n================================================================================"
    return report


def main():
    report = generate_operator_report()
    print(report)

    # Also write to logs
    logs_dir = QUANT_INFRA / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    (logs_dir / "latest_operator_report.txt").write_text(report)
    ts = now.strftime("%Y%m%dT%H%M%S")
    (logs_dir / f"operator_report_{ts}.txt").write_text(report)
    print(f"\n[jarvis] Report saved to {logs_dir / 'latest_operator_report.txt'}")


if __name__ == "__main__":
    main()
