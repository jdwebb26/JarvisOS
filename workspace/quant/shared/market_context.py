#!/usr/bin/env python3
"""Quant Lanes — Market Context Reader.

Reads real OHLCV+VIX data from the strategy factory data directory
(populated by the daily 4:00 AM cron_ingest.sh via yfinance) and
produces a structured market snapshot for autonomous lane consumption.

This is NOT live streaming market data. It is the most recent daily bar
from the cron-ingested CSV files. Freshness depends on the cron schedule.

Data source: ~/.openclaw/workspace/data/NQ_daily.csv + metadata.json
Updated by: strategy_factory/scripts/cron_ingest.sh (daily 4:00 AM UTC)
Provider: yfinance (NQ=F continuous front-month, ^VIX daily close)

The snapshot includes:
  - last_close, prev_close, daily_change_pct
  - vix_level
  - recent 5-day high/low range
  - simple trend direction (up/down/flat based on 5-day slope)
  - data_freshness_hours (how old the latest bar is)
  - full provenance (source, file path, metadata)
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Default data directory (strategy factory's cron output)
_DEFAULT_DATA_DIR = Path.home() / ".openclaw" / "workspace" / "data"


def _find_data_dir(root: Path) -> Path:
    """Resolve the market data directory.

    Checks:
      1. root / "data" (for isolated test roots or co-located data)
      2. The default ~/.openclaw/workspace/data/ (production — only if root
         looks like the real jarvis-v5 repo, not an isolated test tmpdir)
    """
    local = root / "data"
    if local.exists() and (local / "NQ_daily.csv").exists():
        return local
    # Only fall through to production data if root is the actual repo
    # (has workspace/quant/shared/ structure AND is not under /tmp/)
    is_real_repo = (root / "workspace" / "quant" / "shared").exists() and "/tmp" not in str(root)
    if is_real_repo and _DEFAULT_DATA_DIR.exists() and (_DEFAULT_DATA_DIR / "NQ_daily.csv").exists():
        return _DEFAULT_DATA_DIR
    return local  # Will fail gracefully on read


def _read_tail_csv(path: Path, n: int = 20) -> list[dict]:
    """Read the last n data rows of a CSV file efficiently.

    Skips the header row and any rows where numeric columns fail to parse.
    """
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        if len(lines) < 2:
            return []
        header = lines[0].split(",")
        # Take last n lines from data rows (everything after header)
        data_lines = lines[1:]
        tail = data_lines[-n:]
        rows = []
        for line in tail:
            vals = line.split(",")
            if len(vals) != len(header):
                continue
            row = {}
            all_numeric = True
            for k, v in zip(header, vals):
                try:
                    row[k] = float(v)
                except ValueError:
                    all_numeric = False
                    break
            if all_numeric:
                rows.append(row)
        return rows
    except (OSError, ValueError):
        return []


def _load_metadata(data_dir: Path) -> dict:
    """Load metadata.json if available."""
    path = data_dir / "metadata.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        return {}


def read_market_snapshot(root: Path) -> Optional[dict]:
    """Read the current market snapshot from cron-ingested OHLCV+VIX data.

    Returns a structured dict or None if no data is available.

    The dict includes:
        symbol: "NQ"
        last_close: float
        prev_close: float
        daily_change_pct: float
        high_5d: float
        low_5d: float
        range_5d_pct: float  (5-day range as % of last close)
        vix: float
        trend_5d: "up" | "down" | "flat"
        data_source: str ("yfinance/NQ=F daily via cron_ingest")
        data_file: str (path to CSV)
        data_updated_at: str (ISO timestamp from metadata.json)
        data_freshness_hours: float (how old the data is)
        snapshot_at: str (ISO timestamp of this snapshot computation)
        bars_available: int
    """
    data_dir = _find_data_dir(root)
    csv_path = data_dir / "NQ_daily.csv"
    rows = _read_tail_csv(csv_path, n=10)

    if len(rows) < 2:
        return None

    latest = rows[-1]
    prev = rows[-2]

    last_close = latest.get("close")
    prev_close = prev.get("close")
    if last_close is None or prev_close is None:
        return None

    daily_change_pct = ((last_close - prev_close) / prev_close) * 100 if prev_close else 0.0

    # 5-day window
    window = rows[-5:] if len(rows) >= 5 else rows
    high_5d = max(r.get("high", 0) for r in window)
    low_5d = min(r.get("low", float("inf")) for r in window)
    range_5d_pct = ((high_5d - low_5d) / last_close) * 100 if last_close else 0.0

    # Simple trend: compare first and last close in the 5d window
    first_close = window[0].get("close", last_close)
    slope_pct = ((last_close - first_close) / first_close) * 100 if first_close else 0.0
    if slope_pct > 0.3:
        trend = "up"
    elif slope_pct < -0.3:
        trend = "down"
    else:
        trend = "flat"

    vix = latest.get("vix", 0.0)

    # Freshness from metadata
    metadata = _load_metadata(data_dir)
    data_updated_at = metadata.get("last_updated", "")
    freshness_hours = None
    if data_updated_at:
        try:
            updated = datetime.fromisoformat(data_updated_at)
            freshness_hours = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
        except (ValueError, TypeError):
            pass

    nq_meta = metadata.get("sources", {}).get("nq_daily", {})

    return {
        "symbol": "NQ",
        "last_close": round(last_close, 2),
        "prev_close": round(prev_close, 2),
        "daily_change_pct": round(daily_change_pct, 2),
        "high_5d": round(high_5d, 2),
        "low_5d": round(low_5d, 2),
        "range_5d_pct": round(range_5d_pct, 2),
        "vix": round(vix, 2),
        "trend_5d": trend,
        "data_source": f"yfinance/{nq_meta.get('symbol', 'NQ=F')} daily via cron_ingest",
        "data_file": str(csv_path),
        "data_updated_at": data_updated_at,
        "data_freshness_hours": round(freshness_hours, 1) if freshness_hours is not None else None,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "bars_available": nq_meta.get("bars", len(rows)),
    }


def format_market_read(snapshot: Optional[dict]) -> str:
    """Format a market snapshot into a human-readable market read for Kitt brief.

    Returns a short, phone-scannable string.
    """
    if snapshot is None:
        return "No market data available (cron data pull may not have run yet)."

    parts = [
        f"NQ last {snapshot['last_close']:.0f}",
        f"({snapshot['daily_change_pct']:+.1f}%)",
        f"VIX {snapshot['vix']:.1f}",
        f"5d trend {snapshot['trend_5d']}",
        f"5d range {snapshot['range_5d_pct']:.1f}%",
    ]
    line1 = "  ".join(parts)

    freshness = snapshot.get("data_freshness_hours")
    if freshness is not None:
        if freshness < 1:
            age = "< 1h old"
        elif freshness < 24:
            age = f"{freshness:.0f}h old"
        else:
            age = f"{freshness / 24:.1f}d old"
    else:
        age = "unknown age"

    line2 = f"  Source: {snapshot['data_source']} ({age})"

    return f"{line1}\n{line2}"
