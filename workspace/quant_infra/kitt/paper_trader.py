#!/usr/bin/env python3
"""Kitt Paper Trading State Machine.

Manages autonomous paper trading for the Kitt quant lane.
All positions are PAPER ONLY — no live trading capability exists here.

Usage:
    # Check status
    .venv/bin/python3 workspace/quant_infra/kitt/paper_trader.py --status

    # Open a paper position
    .venv/bin/python3 workspace/quant_infra/kitt/paper_trader.py --open-long 24500 --stop 24400 --target 24700 --reason "breakout above resistance"

    # Close a position
    .venv/bin/python3 workspace/quant_infra/kitt/paper_trader.py --close <position_id> --exit-price 24650

    # Mark positions to market
    .venv/bin/python3 workspace/quant_infra/kitt/paper_trader.py --mark 24600

    # Performance summary
    .venv/bin/python3 workspace/quant_infra/kitt/paper_trader.py --performance
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb

from warehouse.loader import (
    get_connection,
    insert_paper_position,
    insert_trade_decision,
    close_paper_position,
    mark_position,
)
from packets.writer import write_packet, read_packet

THIS_DIR = Path(__file__).resolve().parent
QUANT_INFRA = THIS_DIR.parent
WAREHOUSE_PATH = QUANT_INFRA / "warehouse" / "quant.duckdb"
BRIEFS_DIR = QUANT_INFRA / "research" / "kitt_briefs"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid(prefix: str = "kpp") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def open_position(
    direction: str,
    entry_price: float,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    reasoning: str = "",
    quantity: int = 1,
    symbol: str = "NQ",
) -> str:
    """Open a new paper position and log the decision."""
    con = get_connection(WAREHOUSE_PATH)
    try:
        pos_id = _uid("kpp")
        dec_id = _uid("kpd")

        # Record the position
        insert_paper_position(con, {
            "position_id": pos_id,
            "opened_at": _now(),
            "symbol": symbol,
            "direction": direction,
            "quantity": quantity,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "reasoning": reasoning,
            "upstream_packet": "",
        })

        # Record the decision
        insert_trade_decision(con, {
            "decision_id": dec_id,
            "decided_at": _now(),
            "action": f"open_{direction}",
            "symbol": symbol,
            "reasoning": reasoning,
            "confidence": None,
            "market_context": f"entry={entry_price}, SL={stop_loss}, TP={take_profit}",
            "position_id": pos_id,
            "upstream_packets": "",
        })

        # Write kitt packet
        _write_kitt_packet(con)

        # Write brief
        _write_brief(con, f"Opened {direction} {symbol} @ {entry_price}")

        print(f"[kitt] Opened {direction} {symbol} @ {entry_price} → {pos_id}")
        return pos_id
    finally:
        con.close()


def close_position_by_id(position_id: str, exit_price: float) -> None:
    """Close a paper position by ID."""
    con = get_connection(WAREHOUSE_PATH)
    try:
        close_paper_position(con, position_id, exit_price)

        # Record the close decision
        insert_trade_decision(con, {
            "decision_id": _uid("kpd"),
            "decided_at": _now(),
            "action": "close",
            "symbol": "NQ",
            "reasoning": f"Closed position {position_id} at {exit_price}",
            "position_id": position_id,
        })

        # Update outcome on the decision that opened this position
        row = con.execute(
            "SELECT pnl FROM kitt_paper_positions WHERE position_id = ?",
            [position_id]
        ).fetchone()
        if row:
            pnl = row[0]
            outcome = "win" if pnl and pnl > 0 else ("loss" if pnl and pnl < 0 else "scratch")
            con.execute(
                "UPDATE kitt_trade_decisions SET outcome = ? WHERE position_id = ? AND action LIKE 'open_%'",
                [outcome, position_id]
            )

        _write_kitt_packet(con)
        _write_brief(con, f"Closed {position_id} @ {exit_price}")

        print(f"[kitt] Closed {position_id} @ {exit_price}")
    finally:
        con.close()


def mark_all_positions(mark_price: float) -> None:
    """Mark all open positions to current market price."""
    con = get_connection(WAREHOUSE_PATH)
    try:
        positions = con.execute(
            "SELECT position_id FROM kitt_paper_positions WHERE status = 'open'"
        ).fetchall()

        for (pos_id,) in positions:
            mark_position(con, pos_id, mark_price)

        _write_kitt_packet(con)
        print(f"[kitt] Marked {len(positions)} open positions @ {mark_price}")
    finally:
        con.close()


def check_stops(current_price: float) -> list[str]:
    """Check if any open positions hit their stop loss. Returns list of stopped position IDs."""
    con = get_connection(WAREHOUSE_PATH)
    stopped = []
    try:
        positions = con.execute("""
            SELECT position_id, direction, stop_loss
            FROM kitt_paper_positions
            WHERE status = 'open' AND stop_loss IS NOT NULL
        """).fetchall()

        for pos_id, direction, stop_loss in positions:
            triggered = False
            if direction == "long" and current_price <= stop_loss:
                triggered = True
            elif direction == "short" and current_price >= stop_loss:
                triggered = True

            if triggered:
                close_paper_position(con, pos_id, stop_loss, status="stopped_out")
                insert_trade_decision(con, {
                    "decision_id": _uid("kpd"),
                    "decided_at": _now(),
                    "action": "close",
                    "symbol": "NQ",
                    "reasoning": f"Stop loss triggered at {stop_loss}",
                    "position_id": pos_id,
                })
                stopped.append(pos_id)
                print(f"[kitt] STOP triggered: {pos_id} closed @ {stop_loss}")

        if stopped:
            _write_kitt_packet(con)
    finally:
        con.close()
    return stopped


def get_status() -> dict:
    """Get current paper trading status."""
    con = get_connection(WAREHOUSE_PATH)
    try:
        open_positions = con.execute("""
            SELECT position_id, opened_at, symbol, direction, quantity,
                   entry_price, stop_loss, take_profit, mark_price, marked_at, reasoning
            FROM kitt_paper_positions WHERE status = 'open'
            ORDER BY opened_at DESC
        """).fetchall()

        perf = con.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'open') as open_count,
                COUNT(*) FILTER (WHERE pnl > 0) as wins,
                COUNT(*) FILTER (WHERE pnl < 0) as losses,
                COALESCE(ROUND(SUM(pnl), 2), 0) as total_pnl,
                COALESCE(ROUND(AVG(pnl) FILTER (WHERE pnl IS NOT NULL), 2), 0) as avg_pnl
            FROM kitt_paper_positions
        """).fetchone()

        recent_decisions = con.execute("""
            SELECT decision_id, decided_at, action, reasoning, confidence
            FROM kitt_trade_decisions
            ORDER BY decided_at DESC LIMIT 5
        """).fetchall()

        return {
            "open_positions": [
                {
                    "position_id": r[0], "opened_at": str(r[1]), "symbol": r[2],
                    "direction": r[3], "quantity": r[4], "entry_price": r[5],
                    "stop_loss": r[6], "take_profit": r[7], "mark_price": r[8],
                    "marked_at": str(r[9]) if r[9] else None, "reasoning": r[10],
                }
                for r in open_positions
            ],
            "performance": {
                "total_trades": perf[0], "open": perf[1], "wins": perf[2],
                "losses": perf[3], "total_pnl": perf[4], "avg_pnl": perf[5],
            },
            "recent_decisions": [
                {"id": r[0], "at": str(r[1]), "action": r[2], "reasoning": r[3], "confidence": r[4]}
                for r in recent_decisions
            ],
        }
    finally:
        con.close()


def _write_kitt_packet(con: duckdb.DuckDBPyConnection) -> None:
    """Write the kitt quant packet with current state."""
    open_positions = con.execute("""
        SELECT position_id, direction, entry_price, mark_price, stop_loss, take_profit
        FROM kitt_paper_positions WHERE status = 'open'
    """).fetchall()

    perf = con.execute("""
        SELECT COUNT(*) FILTER (WHERE status != 'open') as closed,
               COUNT(*) FILTER (WHERE pnl > 0) as wins,
               COALESCE(ROUND(SUM(pnl), 2), 0) as total_pnl
        FROM kitt_paper_positions
    """).fetchone()

    positions_data = [
        {
            "id": r[0], "direction": r[1], "entry": r[2],
            "mark": r[3], "stop": r[4], "target": r[5],
        }
        for r in open_positions
    ]

    write_packet(
        lane="kitt",
        packet_type="quant",
        summary=f"Kitt: {len(open_positions)} open positions, {perf[0]} closed ({perf[1]} wins), PnL={perf[2]}",
        data={
            "open_positions": positions_data,
            "performance": {"closed": perf[0], "wins": perf[1], "total_pnl": perf[2]},
        },
        upstream=["hermes_synthesis"],
        source_module="kitt.paper_trader",
        confidence=0.6,
    )


def _write_brief(con: duckdb.DuckDBPyConnection, action_summary: str) -> None:
    """Write a human-readable Kitt brief to research/kitt_briefs/."""
    now = datetime.now(timezone.utc)
    status = get_status.__wrapped__() if hasattr(get_status, "__wrapped__") else None

    # Read status directly from DB since we have connection
    open_pos = con.execute("""
        SELECT position_id, direction, symbol, entry_price, mark_price
        FROM kitt_paper_positions WHERE status = 'open'
    """).fetchall()

    md = f"""# Kitt Brief — {now.strftime('%Y-%m-%d %H:%M UTC')}

## Action
{action_summary}

## Open Positions
"""
    if open_pos:
        for pid, direction, sym, entry, mark in open_pos:
            md += f"- **{pid}**: {direction} {sym} @ {entry} (mark: {mark})\n"
    else:
        md += "- No open positions\n"

    perf = con.execute("""
        SELECT COUNT(*), COUNT(*) FILTER (WHERE pnl > 0),
               COUNT(*) FILTER (WHERE pnl < 0), COALESCE(SUM(pnl), 0)
        FROM kitt_paper_positions WHERE status != 'open'
    """).fetchone()
    md += f"""
## Track Record
- Closed: {perf[0]} | Wins: {perf[1]} | Losses: {perf[2]} | Total PnL: ${perf[3]:.2f}
"""

    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    (BRIEFS_DIR / "latest.md").write_text(md)
    ts = now.strftime("%Y%m%dT%H%M%S")
    (BRIEFS_DIR / f"brief_{ts}.md").write_text(md)


def print_status():
    """Print current paper trading status to stdout."""
    status = get_status()

    print("\n=== KITT PAPER TRADING STATUS ===\n")

    print("Open Positions:")
    if status["open_positions"]:
        for p in status["open_positions"]:
            unrealized = ""
            if p["mark_price"] and p["entry_price"]:
                if p["direction"] == "long":
                    pnl = (p["mark_price"] - p["entry_price"]) * p.get("quantity", 1) * 20
                else:
                    pnl = (p["entry_price"] - p["mark_price"]) * p.get("quantity", 1) * 20
                unrealized = f" (unrealized: ${pnl:.2f})"
            print(f"  {p['position_id']}: {p['direction']} {p['symbol']} @ {p['entry_price']}"
                  f" SL={p['stop_loss']} TP={p['take_profit']}{unrealized}")
    else:
        print("  None")

    perf = status["performance"]
    print(f"\nPerformance: {perf['total_trades']} trades | "
          f"W:{perf['wins']} L:{perf['losses']} | "
          f"PnL: ${perf['total_pnl']:.2f} | Avg: ${perf['avg_pnl']:.2f}")

    print("\nRecent Decisions:")
    for d in status["recent_decisions"]:
        print(f"  [{d['at'][:19]}] {d['action']}: {d['reasoning'][:80]}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Kitt Paper Trading")
    parser.add_argument("--status", action="store_true", help="Show current status")
    parser.add_argument("--performance", action="store_true", help="Show performance summary")
    parser.add_argument("--open-long", type=float, metavar="PRICE", help="Open long at price")
    parser.add_argument("--open-short", type=float, metavar="PRICE", help="Open short at price")
    parser.add_argument("--close", type=str, metavar="POS_ID", help="Close position by ID")
    parser.add_argument("--exit-price", type=float, help="Exit price for close")
    parser.add_argument("--mark", type=float, help="Mark all positions to price")
    parser.add_argument("--stop", type=float, help="Stop loss price")
    parser.add_argument("--target", type=float, help="Take profit price")
    parser.add_argument("--reason", type=str, default="", help="Reasoning for trade")
    parser.add_argument("--check-stops", type=float, metavar="PRICE", help="Check stop losses against price")

    args = parser.parse_args()

    if args.status or args.performance:
        print_status()
    elif args.open_long:
        open_position("long", args.open_long, args.stop, args.target, args.reason)
    elif args.open_short:
        open_position("short", args.open_short, args.stop, args.target, args.reason)
    elif args.close:
        if not args.exit_price:
            print("ERROR: --exit-price required for --close")
            sys.exit(1)
        close_position_by_id(args.close, args.exit_price)
    elif args.mark:
        mark_all_positions(args.mark)
    elif args.check_stops is not None:
        stopped = check_stops(args.check_stops)
        if stopped:
            print(f"[kitt] Stopped out: {stopped}")
        else:
            print("[kitt] No stops triggered")
    else:
        print_status()


if __name__ == "__main__":
    main()
