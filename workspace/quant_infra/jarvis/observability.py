#!/usr/bin/env python3
"""Jarvis Quant Observability — operator-facing summary of quant lane activity.

Reads all lane packets and warehouse state to produce an operator summary.

Usage:
    .venv/bin/python3 workspace/quant_infra/jarvis/observability.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packets.writer import read_all_latest

QUANT_INFRA = Path(__file__).resolve().parent.parent
WAREHOUSE_PATH = QUANT_INFRA / "warehouse" / "quant.duckdb"


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
