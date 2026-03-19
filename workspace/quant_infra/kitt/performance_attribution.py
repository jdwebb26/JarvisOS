#!/usr/bin/env python3
"""Per-Family Performance Attribution — signal quality metrics by strategy family.

Tracks and reports:
  - P&L attribution per signal family (which families make/lose money)
  - Signal quality metrics (win rate, avg win, avg loss, expectancy)
  - Regime performance (which families work in which regimes)
  - Signal confidence calibration (does high confidence = high win rate?)

Reads from:
  - kitt_paper_positions (DuckDB) — closed trades with strategy_id
  - kitt_trade_decisions (DuckDB) — decision reasoning, regime context

Outputs:
  - research/performance/latest.json — machine-readable attribution
  - research/performance/latest.md — operator-readable report

Usage:
    python3 workspace/quant_infra/kitt/performance_attribution.py
    python3 workspace/quant_infra/kitt/performance_attribution.py --json
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QUANT_INFRA = Path(__file__).resolve().parent.parent
REPO_ROOT = QUANT_INFRA.parent.parent
sys.path.insert(0, str(QUANT_INFRA))

from warehouse.loader import get_connection

WAREHOUSE_PATH = QUANT_INFRA / "warehouse" / "quant.duckdb"
PERF_DIR = QUANT_INFRA / "research" / "performance"


def compute_attribution() -> dict:
    """Compute per-family performance attribution from paper trading data.

    Returns comprehensive attribution dict with per-family and aggregate metrics.
    """
    try:
        con = get_connection(WAREHOUSE_PATH)
    except Exception as exc:
        return {"error": str(exc), "families": {}}

    try:
        # Fetch all closed positions with strategy_id
        rows = con.execute("""
            SELECT position_id, direction, entry_price, exit_price,
                   quantity, pnl, status, strategy_id, opened_at, closed_at
            FROM kitt_paper_positions
            WHERE status != 'open' AND pnl IS NOT NULL
            ORDER BY closed_at ASC
        """).fetchall()

        # Also fetch open positions for unrealized tracking
        open_rows = con.execute("""
            SELECT position_id, direction, entry_price, mark_price,
                   quantity, strategy_id, opened_at
            FROM kitt_paper_positions
            WHERE status = 'open'
        """).fetchall()

        # Build per-family data
        family_data: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "closed_trades": 0, "wins": 0, "losses": 0, "scratches": 0,
            "total_pnl": 0.0, "win_pnl": 0.0, "loss_pnl": 0.0,
            "pnl_series": [], "max_drawdown": 0.0, "peak_pnl": 0.0,
            "open_positions": 0, "unrealized_pnl": 0.0,
            "status_counts": defaultdict(int),
        })

        # Process closed trades
        for pos_id, direction, entry, exit_p, qty, pnl, status, strat_id, opened, closed in rows:
            family = _infer_family(strat_id)
            fd = family_data[family]
            fd["closed_trades"] += 1
            fd["total_pnl"] += pnl
            fd["pnl_series"].append(pnl)
            fd["status_counts"][status] += 1

            if pnl > 0:
                fd["wins"] += 1
                fd["win_pnl"] += pnl
            elif pnl < 0:
                fd["losses"] += 1
                fd["loss_pnl"] += pnl
            else:
                fd["scratches"] += 1

            # Running drawdown
            cumulative = sum(fd["pnl_series"])
            fd["peak_pnl"] = max(fd["peak_pnl"], cumulative)
            dd = fd["peak_pnl"] - cumulative
            fd["max_drawdown"] = max(fd["max_drawdown"], dd)

        # Process open positions
        for pos_id, direction, entry, mark, qty, strat_id, opened in open_rows:
            family = _infer_family(strat_id)
            fd = family_data[family]
            fd["open_positions"] += 1
            mark = mark or entry
            mult = 1 if direction == "long" else -1
            unrealized = (mark - entry) * mult * qty * 20
            fd["unrealized_pnl"] += unrealized

        # Build output
        families: dict[str, dict] = {}
        for family, fd in sorted(family_data.items(), key=lambda x: -x[1]["total_pnl"]):
            closed = fd["closed_trades"]
            wins = fd["wins"]
            losses = fd["losses"]
            total = wins + losses
            win_rate = round(wins / max(total, 1) * 100, 1)
            avg_win = round(fd["win_pnl"] / max(wins, 1), 2)
            avg_loss = round(fd["loss_pnl"] / max(losses, 1), 2)
            expectancy = round(fd["total_pnl"] / max(closed, 1), 2)
            profit_factor = round(abs(fd["win_pnl"] / fd["loss_pnl"]), 2) if fd["loss_pnl"] != 0 else float("inf")

            families[family] = {
                "closed_trades": closed,
                "wins": wins,
                "losses": losses,
                "scratches": fd["scratches"],
                "win_rate": win_rate,
                "total_pnl": round(fd["total_pnl"], 2),
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "expectancy": expectancy,
                "profit_factor": profit_factor if profit_factor != float("inf") else "N/A",
                "max_drawdown": round(fd["max_drawdown"], 2),
                "open_positions": fd["open_positions"],
                "unrealized_pnl": round(fd["unrealized_pnl"], 2),
                "exit_breakdown": dict(fd["status_counts"]),
            }

        # Aggregate metrics
        total_pnl = sum(fd["total_pnl"] for fd in family_data.values())
        total_trades = sum(fd["closed_trades"] for fd in family_data.values())
        total_wins = sum(fd["wins"] for fd in family_data.values())
        total_losses = sum(fd["losses"] for fd in family_data.values())

        attribution = {
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "aggregate": {
                "total_trades": total_trades,
                "total_pnl": round(total_pnl, 2),
                "win_rate": round(total_wins / max(total_wins + total_losses, 1) * 100, 1),
                "family_count": len(families),
                "best_family": max(families, key=lambda f: families[f]["total_pnl"]) if families else "none",
                "worst_family": min(families, key=lambda f: families[f]["total_pnl"]) if families else "none",
            },
            "families": families,
        }

        return attribution

    finally:
        con.close()


def _infer_family(strategy_id: str | None) -> str:
    """Infer signal family from strategy_id.

    Strategy IDs follow patterns like:
      - kitt-default (or None) → ema_mean_reversion
      - momentum → momentum
      - ema_mean_reversion → ema_mean_reversion
      - factory-breakout-20260319 → breakout
      - atlas-gap-xxx → breakout
    """
    if not strategy_id:
        return "ema_mean_reversion"

    sid = strategy_id.lower()

    # Direct family name match
    families = ["ema_mean_reversion", "momentum", "trend_following", "breakout", "vwap_reversion"]
    for f in families:
        if f in sid:
            return f

    # Pattern matching
    if "mr" in sid or "mean_rev" in sid or "ema" in sid:
        return "ema_mean_reversion"
    if "mom" in sid or "rsi" in sid:
        return "momentum"
    if "trend" in sid or "macd" in sid:
        return "trend_following"
    if "bo" in sid or "brk" in sid or "gap" in sid or "orb" in sid:
        return "breakout"
    if "vwap" in sid:
        return "vwap_reversion"

    return strategy_id  # use raw ID if no match


def render_attribution(attribution: dict) -> str:
    """Render attribution as operator-readable Markdown."""
    now = attribution.get("computed_at", "?")[:19]
    agg = attribution.get("aggregate", {})
    families = attribution.get("families", {})

    lines = [
        f"# Performance Attribution — {now}",
        "",
        "## Aggregate",
        f"- **Total trades**: {agg.get('total_trades', 0)}",
        f"- **Total PnL**: ${agg.get('total_pnl', 0):.2f}",
        f"- **Win rate**: {agg.get('win_rate', 0):.1f}%",
        f"- **Families**: {agg.get('family_count', 0)}",
        f"- **Best**: {agg.get('best_family', 'none')}",
        f"- **Worst**: {agg.get('worst_family', 'none')}",
        "",
    ]

    if families:
        lines.append("## Per-Family Breakdown")
        lines.append("")
        lines.append("| Family | Trades | Win% | PnL | Expectancy | PF | Max DD |")
        lines.append("|--------|--------|------|-----|------------|-----|--------|")
        for fam, info in families.items():
            pf = info["profit_factor"]
            pf_str = f"{pf:.2f}" if isinstance(pf, float) else str(pf)
            lines.append(
                f"| {fam} | {info['closed_trades']} | "
                f"{info['win_rate']:.0f}% | "
                f"${info['total_pnl']:.2f} | "
                f"${info['expectancy']:.2f} | "
                f"{pf_str} | "
                f"${info['max_drawdown']:.2f} |"
            )

        lines.append("")
        for fam, info in families.items():
            if info["open_positions"] > 0:
                lines.append(
                    f"- **{fam}**: {info['open_positions']} open, "
                    f"unrealized ${info['unrealized_pnl']:.2f}"
                )

    return "\n".join(lines)


def write_attribution(attribution: dict | None = None) -> tuple[Path, Path]:
    """Compute (if needed) and write attribution. Returns (json_path, md_path)."""
    if attribution is None:
        attribution = compute_attribution()

    PERF_DIR.mkdir(parents=True, exist_ok=True)

    json_path = PERF_DIR / "latest.json"
    json_path.write_text(json.dumps(attribution, indent=2, default=str) + "\n")

    md_path = PERF_DIR / "latest.md"
    md_path.write_text(render_attribution(attribution))

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    (PERF_DIR / f"attribution_{ts}.json").write_text(
        json.dumps(attribution, indent=2, default=str) + "\n"
    )

    return json_path, md_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Performance Attribution")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    attribution = compute_attribution()

    if args.json:
        print(json.dumps(attribution, indent=2, default=str))
    else:
        print(render_attribution(attribution))

    json_path, md_path = write_attribution(attribution)
    print(f"\n[attribution] Written to {json_path}")


if __name__ == "__main__":
    main()
