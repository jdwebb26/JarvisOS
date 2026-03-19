"""Jarvis Token Ledger — LLM token usage tracking and cost observability.

Operator-facing only. Tracks token consumption across all quant lanes
for budget awareness and throughput monitoring.

Usage:
    .venv/bin/python3 -c "from workspace.quant_infra.jarvis.token_ledger import TokenLedger; TokenLedger().summary()"
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

THIS_DIR = Path(__file__).resolve().parent
QUANT_INFRA = THIS_DIR.parent
WAREHOUSE_PATH = QUANT_INFRA / "warehouse" / "quant.duckdb"

# Rough cost estimates per 1K tokens (USD)
COST_PER_1K = {
    "qwen-3.5-35b": 0.0,      # Local, no cost
    "qwen-3.5-122b": 0.0,     # Local, no cost
    "qwen-3.5-9b": 0.0,       # Local, no cost
    "claude-opus-4-6": 0.015,
    "claude-sonnet-4-6": 0.003,
    "claude-haiku-4-5": 0.00025,
    "default": 0.001,
}


class TokenLedger:
    """Track and report LLM token usage across quant lanes."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or WAREHOUSE_PATH

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.db_path))

    def record(
        self,
        lane: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        session_id: str = "",
        task_description: str = "",
    ) -> str:
        """Record a token usage event. Returns usage_id."""
        usage_id = f"tu-{uuid.uuid4().hex[:12]}"
        total = prompt_tokens + completion_tokens
        cost_rate = COST_PER_1K.get(model, COST_PER_1K["default"])
        cost = total / 1000.0 * cost_rate

        con = self._connect()
        try:
            con.execute("""
                INSERT INTO token_usage
                (usage_id, recorded_at, lane, model, prompt_tokens, completion_tokens,
                 total_tokens, estimated_cost_usd, session_id, task_description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                usage_id,
                datetime.now(timezone.utc).isoformat(),
                lane,
                model,
                prompt_tokens,
                completion_tokens,
                total,
                round(cost, 6),
                session_id,
                task_description,
            ])
        finally:
            con.close()

        return usage_id

    def summary(self, days: int = 7) -> dict:
        """Get token usage summary for the last N days."""
        con = self._connect()
        try:
            rows = con.execute(f"""
                SELECT
                    lane,
                    COUNT(*) as calls,
                    SUM(total_tokens) as total_tokens,
                    ROUND(SUM(estimated_cost_usd), 4) as total_cost,
                    ROUND(AVG(total_tokens), 0) as avg_tokens
                FROM token_usage
                WHERE recorded_at >= current_timestamp - INTERVAL {days} DAY
                GROUP BY lane
                ORDER BY total_tokens DESC
            """).fetchall()

            totals = con.execute(f"""
                SELECT
                    COUNT(*) as total_calls,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(ROUND(SUM(estimated_cost_usd), 4), 0) as total_cost
                FROM token_usage
                WHERE recorded_at >= current_timestamp - INTERVAL {days} DAY
            """).fetchone()

            return {
                "period_days": days,
                "by_lane": [
                    {"lane": r[0], "calls": r[1], "tokens": r[2], "cost_usd": r[3], "avg_tokens": r[4]}
                    for r in rows
                ],
                "totals": {
                    "calls": totals[0],
                    "tokens": totals[1],
                    "cost_usd": totals[2],
                },
            }
        finally:
            con.close()

    def print_summary(self, days: int = 7) -> None:
        """Print token usage summary to stdout."""
        s = self.summary(days)
        print(f"\n=== TOKEN USAGE ({s['period_days']}d) ===\n")
        if s["by_lane"]:
            for lane in s["by_lane"]:
                print(f"  {lane['lane']:12s}  {lane['calls']:4d} calls  "
                      f"{lane['tokens']:8d} tokens  ${lane['cost_usd']:.4f}")
        else:
            print("  No usage recorded")
        t = s["totals"]
        print(f"\n  {'TOTAL':12s}  {t['calls']:4d} calls  "
              f"{t['tokens']:8d} tokens  ${t['cost_usd']:.4f}\n")
