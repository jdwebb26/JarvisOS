"""Automated free market data ingestion for NQ Strategy Factory.

Data sources (all free, all automated):
    - yfinance NQ=F daily:  ~6400 bars since 2000-09-18
    - yfinance ^VIX daily:  ~9100 bars since 1990-01-02
    - yfinance NQ=F hourly: ~1100 bars, rolling 60-day window

Data storage layout (under DATA_DIR):
    nq_daily.csv        — NQ=F daily OHLCV + VIX (merged)
    nq_hourly.csv       — NQ=F hourly OHLCV + VIX (accumulated)
    NQ_1min.csv         — canonical file for Strategy Factory (symlink/copy of best available)
    metadata.json       — source provenance, coverage, last update times

Limitations (honest):
    - No free source provides historical 1-minute NQ bars (7-day yfinance limit).
    - Hourly data only covers the last ~60 days per fetch; accumulated over time.
    - VIX is daily-close only; hourly bars get the day's VIX forward-filled.
    - NQ=F is a continuous front-month contract, not individual expiries.
"""

import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .data import DATA_DIR

# yfinance is an optional dependency for ingestion
_YF_AVAILABLE = None


def _ensure_yfinance():
    global _YF_AVAILABLE
    if _YF_AVAILABLE is None:
        try:
            import yfinance  # noqa: F401
            _YF_AVAILABLE = True
        except ImportError:
            _YF_AVAILABLE = False
    if not _YF_AVAILABLE:
        raise ImportError(
            "yfinance is required for data ingestion. Install: pip install yfinance"
        )


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _flatten_yf_columns(df):
    """Flatten yfinance's MultiIndex columns to simple names."""
    if df.columns.nlevels > 1:
        df.columns = df.columns.droplevel(1)
    return df


# ---------------------------------------------------------------------------
# Fetch functions
# ---------------------------------------------------------------------------

def fetch_nq_daily(start="2000-01-01"):
    """Fetch NQ=F daily OHLCV from yfinance.

    Returns pandas DataFrame with columns: open, high, low, close, volume.
    Index is DatetimeIndex (date).
    """
    _ensure_yfinance()
    import yfinance as yf

    df = yf.download("NQ=F", start=start, interval="1d", progress=False)
    if df.empty:
        return df
    df = _flatten_yf_columns(df)
    df.columns = [c.lower() for c in df.columns]
    df.index.name = "date"
    return df[["open", "high", "low", "close", "volume"]]


def fetch_vix_daily(start="2000-01-01"):
    """Fetch ^VIX daily close from yfinance.

    Returns pandas DataFrame with column: vix.
    Index is DatetimeIndex (date).
    """
    _ensure_yfinance()
    import yfinance as yf

    df = yf.download("^VIX", start=start, interval="1d", progress=False)
    if df.empty:
        return df
    df = _flatten_yf_columns(df)
    df.columns = [c.lower() for c in df.columns]
    df.index.name = "date"
    return df[["close"]].rename(columns={"close": "vix"})


def fetch_nq_hourly():
    """Fetch NQ=F hourly OHLCV from yfinance (max ~60 days).

    Returns pandas DataFrame with columns: open, high, low, close, volume.
    Index is DatetimeIndex (datetime with tz).
    """
    _ensure_yfinance()
    import yfinance as yf

    df = yf.download("NQ=F", period="60d", interval="1h", progress=False)
    if df.empty:
        return df
    df = _flatten_yf_columns(df)
    df.columns = [c.lower() for c in df.columns]
    df.index.name = "datetime"
    return df[["open", "high", "low", "close", "volume"]]


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------

def merge_nq_vix_daily(nq_df, vix_df):
    """Merge NQ daily bars with VIX daily close.

    Joins on date index. VIX is forward-filled for any NQ trading days
    where VIX data is missing (e.g., futures trade on days VIX doesn't).
    """
    import pandas as pd

    merged = nq_df.join(vix_df, how="left")
    merged["vix"] = merged["vix"].ffill()
    # Backfill any leading NaNs (before first VIX date)
    merged["vix"] = merged["vix"].bfill()
    # If still NaN (shouldn't happen), default to 20.0
    merged["vix"] = merged["vix"].fillna(20.0)
    return merged


def merge_hourly_with_daily_vix(hourly_df, vix_df):
    """Merge hourly NQ bars with daily VIX.

    Each hourly bar gets the VIX from its calendar date.
    VIX is forward-filled for weekends/holidays.
    """
    import pandas as pd

    # Extract date from hourly datetime for join
    hourly_dates = hourly_df.index.date
    vix_lookup = vix_df.copy()
    vix_lookup.index = vix_lookup.index.date

    # Map VIX to each hourly bar by date
    vix_values = []
    last_vix = 20.0
    for d in hourly_dates:
        if d in vix_lookup.index:
            last_vix = float(vix_lookup.loc[d, "vix"])
            # Handle case where loc returns a Series (duplicate dates)
            if hasattr(last_vix, '__len__'):
                last_vix = float(last_vix.iloc[-1])
        vix_values.append(last_vix)

    hourly_df = hourly_df.copy()
    hourly_df["vix"] = vix_values
    return hourly_df


# ---------------------------------------------------------------------------
# Storage (CSV, idempotent, dedup)
# ---------------------------------------------------------------------------

def _df_to_csv(df, path):
    """Write DataFrame to CSV. Overwrites existing file."""
    df.to_csv(path)


def _read_existing_csv(path):
    """Read existing CSV into DataFrame, or return None if missing."""
    import pandas as pd

    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df
    except Exception:
        return None


def _merge_incremental(existing_df, new_df):
    """Merge new data into existing, deduplicating by index.

    New data wins for any overlapping dates/timestamps.
    """
    import pandas as pd

    if existing_df is None or existing_df.empty:
        return new_df
    if new_df is None or new_df.empty:
        return existing_df

    combined = pd.concat([existing_df, new_df])
    # Keep last occurrence (new data wins)
    combined = combined[~combined.index.duplicated(keep="last")]
    combined = combined.sort_index()
    return combined


def _write_metadata(meta_path, daily_info, hourly_info, canonical_info):
    """Write metadata.json with source provenance."""
    meta = {
        "last_updated": _now_iso(),
        "sources": {
            "nq_daily": daily_info,
            "nq_hourly": hourly_info,
        },
        "canonical": canonical_info,
        "limitations": [
            "NQ=F is a continuous front-month futures contract from Yahoo Finance",
            "VIX is daily close only (^VIX); hourly bars use forward-filled daily VIX",
            "No free source provides historical 1-minute NQ futures bars",
            "Hourly data covers only the last ~60 days per fetch; accumulates over time",
        ],
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API: bootstrap, update, inspect, canonical
# ---------------------------------------------------------------------------

def bootstrap(data_dir=None):
    """Full initial data fetch: daily history + hourly window + VIX.

    Safe to rerun — merges incrementally and deduplicates.

    Args:
        data_dir: override data directory (default: DATA_DIR)

    Returns:
        dict with bar counts and file paths.
    """
    _ensure_yfinance()
    d = Path(data_dir) if data_dir else DATA_DIR
    d.mkdir(parents=True, exist_ok=True)

    daily_path = d / "nq_daily.csv"
    hourly_path = d / "nq_hourly.csv"
    canonical_path = d / "NQ_1min.csv"
    meta_path = d / "metadata.json"

    # --- Fetch ---
    print("Fetching NQ=F daily...")
    nq_daily = fetch_nq_daily()
    time.sleep(1)  # rate limit courtesy

    print("Fetching ^VIX daily...")
    vix_daily = fetch_vix_daily()
    time.sleep(1)

    print("Fetching NQ=F hourly (60d window)...")
    nq_hourly = fetch_nq_hourly()

    # --- Merge with VIX ---
    daily_merged = merge_nq_vix_daily(nq_daily, vix_daily)
    hourly_merged = merge_hourly_with_daily_vix(nq_hourly, vix_daily)

    # --- Incremental merge with existing data ---
    existing_daily = _read_existing_csv(daily_path)
    existing_hourly = _read_existing_csv(hourly_path)

    final_daily = _merge_incremental(existing_daily, daily_merged)
    final_hourly = _merge_incremental(existing_hourly, hourly_merged)

    # --- Write raw pandas CSVs ---
    _df_to_csv(final_daily, daily_path)
    _df_to_csv(final_hourly, hourly_path)

    # --- Write named datasets with sidecars ---
    # NQ_daily.csv — first-class dataset
    daily_dataset_path = d / "NQ_daily.csv"
    _write_canonical(final_daily, daily_dataset_path, granularity="daily",
                     instrument="NQ")
    # NQ_hourly.csv — first-class dataset
    hourly_dataset_path = d / "NQ_hourly.csv"
    _write_canonical(final_hourly, hourly_dataset_path, granularity="1h",
                     instrument="NQ",
                     vix_source="yfinance ^VIX daily close, forward-filled to hourly")
    # Legacy canonical (backward compat)
    _write_canonical(final_daily, canonical_path, granularity="daily",
                     instrument="NQ")

    # --- Global metadata ---
    daily_info = {
        "source": "yfinance", "symbol": "NQ=F",
        "vix_source": "yfinance ^VIX daily close, forward-filled",
        "granularity": "daily",
        "bars": len(final_daily),
        "start": str(final_daily.index[0]) if len(final_daily) > 0 else None,
        "end": str(final_daily.index[-1]) if len(final_daily) > 0 else None,
        "file": str(daily_dataset_path),
        "fetched_at": _now_iso(),
    }
    hourly_info = {
        "source": "yfinance", "symbol": "NQ=F",
        "vix_source": "yfinance ^VIX daily close, forward-filled to hourly",
        "granularity": "1h",
        "bars": len(final_hourly),
        "start": str(final_hourly.index[0]) if len(final_hourly) > 0 else None,
        "end": str(final_hourly.index[-1]) if len(final_hourly) > 0 else None,
        "file": str(hourly_dataset_path),
        "fetched_at": _now_iso(),
    }
    canonical_info = {
        "file": str(canonical_path),
        "source_file": str(daily_dataset_path),
        "granularity": "daily",
        "bars": len(final_daily),
        "note": "Daily data used as default canonical; use --dataset for explicit selection",
    }
    _write_metadata(meta_path, daily_info, hourly_info, canonical_info)

    print(f"\nBootstrap complete -> {d}")
    print(f"  NQ_daily:  {len(final_daily)} bars  ({daily_dataset_path})")
    print(f"  NQ_hourly: {len(final_hourly)} bars  ({hourly_dataset_path})")
    print(f"  Canonical: {len(final_daily)} bars  ({canonical_path})")

    return {
        "daily_bars": len(final_daily),
        "hourly_bars": len(final_hourly),
        "daily_path": str(daily_path),
        "hourly_path": str(hourly_path),
        "canonical_path": str(canonical_path),
    }


def update(data_dir=None):
    """Incremental update: fetch recent data and merge.

    Fetches last 30 days of daily + 60 days of hourly to fill gaps.
    Safe to run on cron daily.

    Args:
        data_dir: override data directory (default: DATA_DIR)

    Returns:
        dict with bar counts.
    """
    _ensure_yfinance()
    import pandas as pd

    d = Path(data_dir) if data_dir else DATA_DIR
    d.mkdir(parents=True, exist_ok=True)

    daily_path = d / "nq_daily.csv"
    hourly_path = d / "nq_hourly.csv"
    canonical_path = d / "NQ_1min.csv"
    meta_path = d / "metadata.json"

    # Determine start date for incremental daily fetch
    existing_daily = _read_existing_csv(daily_path)
    if existing_daily is not None and len(existing_daily) > 0:
        # Fetch from 5 days before last date to handle corrections
        last_date = existing_daily.index[-1]
        start = (last_date - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    else:
        start = "2000-01-01"  # full bootstrap

    print(f"Updating daily from {start}...")
    nq_daily = fetch_nq_daily(start=start)
    time.sleep(1)

    print("Updating VIX...")
    vix_daily = fetch_vix_daily(start=start)
    time.sleep(1)

    print("Updating hourly (60d)...")
    nq_hourly = fetch_nq_hourly()

    # Merge
    if not nq_daily.empty and not vix_daily.empty:
        daily_merged = merge_nq_vix_daily(nq_daily, vix_daily)
        final_daily = _merge_incremental(existing_daily, daily_merged)
    elif not nq_daily.empty:
        final_daily = _merge_incremental(existing_daily, nq_daily)
    else:
        final_daily = existing_daily

    # Full VIX for hourly merge
    full_vix = _read_existing_csv(daily_path)
    if full_vix is not None and "vix" in full_vix.columns:
        vix_for_hourly = full_vix[["vix"]]
    else:
        vix_for_hourly = vix_daily

    existing_hourly = _read_existing_csv(hourly_path)
    if not nq_hourly.empty:
        hourly_merged = merge_hourly_with_daily_vix(nq_hourly, vix_for_hourly)
        final_hourly = _merge_incremental(existing_hourly, hourly_merged)
    else:
        final_hourly = existing_hourly

    # Write
    if final_daily is not None:
        _df_to_csv(final_daily, daily_path)
        _write_canonical(final_daily, canonical_path, granularity="daily")

    if final_hourly is not None:
        _df_to_csv(final_hourly, hourly_path)

    # Update metadata
    daily_info = {
        "source": "yfinance",
        "symbol": "NQ=F",
        "granularity": "daily",
        "bars": len(final_daily) if final_daily is not None else 0,
        "start": str(final_daily.index[0]) if final_daily is not None and len(final_daily) > 0 else None,
        "end": str(final_daily.index[-1]) if final_daily is not None and len(final_daily) > 0 else None,
        "fetched_at": _now_iso(),
    }
    hourly_info = {
        "source": "yfinance",
        "symbol": "NQ=F",
        "granularity": "1h",
        "bars": len(final_hourly) if final_hourly is not None else 0,
        "fetched_at": _now_iso(),
    }
    canonical_info = {
        "file": str(canonical_path),
        "granularity": "daily",
        "bars": len(final_daily) if final_daily is not None else 0,
    }
    _write_metadata(meta_path, daily_info, hourly_info, canonical_info)

    daily_n = len(final_daily) if final_daily is not None else 0
    hourly_n = len(final_hourly) if final_hourly is not None else 0
    print(f"\nUpdate complete -> {d}")
    print(f"  Daily:  {daily_n} bars")
    print(f"  Hourly: {hourly_n} bars")

    return {"daily_bars": daily_n, "hourly_bars": hourly_n}


def inspect(data_dir=None):
    """Print current data coverage summary.

    Returns:
        dict with coverage information.
    """
    d = Path(data_dir) if data_dir else DATA_DIR

    meta_path = d / "metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
    else:
        meta = None

    daily_path = d / "nq_daily.csv"
    hourly_path = d / "nq_hourly.csv"
    canonical_path = d / "NQ_1min.csv"

    info = {"data_dir": str(d), "files": {}}

    for name, path in [("nq_daily.csv", daily_path),
                        ("nq_hourly.csv", hourly_path),
                        ("NQ_1min.csv", canonical_path)]:
        if path.exists() and path.stat().st_size > 0:
            df = _read_existing_csv(path)
            if df is not None and len(df) > 0:
                info["files"][name] = {
                    "bars": len(df),
                    "start": str(df.index[0]),
                    "end": str(df.index[-1]),
                    "columns": list(df.columns),
                    "size_mb": round(path.stat().st_size / 1024 / 1024, 2),
                }
            else:
                info["files"][name] = {"bars": 0, "note": "empty or unreadable"}
        else:
            info["files"][name] = {"exists": False}

    if meta:
        info["last_updated"] = meta.get("last_updated")
        info["limitations"] = meta.get("limitations", [])

    # Print
    print(f"Data directory: {d}")
    print()
    for name, finfo in info["files"].items():
        if finfo.get("bars", 0) > 0:
            print(f"  {name}:")
            print(f"    Bars:  {finfo['bars']}")
            print(f"    Range: {finfo['start']} -> {finfo['end']}")
            print(f"    Cols:  {finfo['columns']}")
            print(f"    Size:  {finfo['size_mb']} MB")
        elif finfo.get("exists") is False:
            print(f"  {name}: NOT FOUND")
        else:
            print(f"  {name}: empty")

    if meta:
        print(f"\nLast updated: {meta.get('last_updated', 'unknown')}")
        for lim in meta.get("limitations", []):
            print(f"  ⚠ {lim}")

    return info


def _write_canonical(daily_df, canonical_path, granularity="daily",
                     source_provider="yfinance", instrument="NQ",
                     vix_source="yfinance ^VIX daily close, forward-filled"):
    """Write the canonical NQ_1min.csv file that Strategy Factory reads.

    Also writes a sidecar ``<filename>.meta.json`` with explicit dataset
    metadata so the runtime never has to guess granularity.
    """
    if daily_df is None or daily_df.empty:
        return

    # Write CSV
    rows = []
    for i, (idx, row) in enumerate(daily_df.iterrows()):
        rows.append({
            "open": round(float(row["open"]), 2),
            "high": round(float(row["high"]), 2),
            "low": round(float(row["low"]), 2),
            "close": round(float(row["close"]), 2),
            "volume": int(row["volume"]),
            "vix": round(float(row.get("vix", 20.0)), 2),
        })

    fieldnames = ["open", "high", "low", "close", "volume", "vix"]
    with open(canonical_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Write sidecar metadata
    start_str = str(daily_df.index[0]) if len(daily_df) > 0 else None
    end_str = str(daily_df.index[-1]) if len(daily_df) > 0 else None
    sidecar = {
        "instrument": instrument,
        "source_provider": source_provider,
        "data_source": "real",
        "data_granularity": granularity,
        "vix_source": vix_source,
        "timezone": "exchange_local",
        "coverage_start": start_str,
        "coverage_end": end_str,
        "row_count": len(daily_df),
        "generated_at": _now_iso(),
        "updated_at": _now_iso(),
        "notes": [
            f"NQ=F continuous front-month contract via {source_provider}",
            "VIX is daily close only; forward-filled to match bar dates",
        ],
    }
    sidecar_path = Path(str(canonical_path) + ".meta.json")
    sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
