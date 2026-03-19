"""Tests for the data ingestion pipeline.

These tests cover merge logic, storage, canonical output, and metadata —
without hitting the network (no yfinance calls).
"""

import csv
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

# pandas is required for ingestion tests (installed with yfinance)
pd = pytest.importorskip("pandas")

from strategy_factory.ingest import (
    merge_nq_vix_daily,
    merge_hourly_with_daily_vix,
    _merge_incremental,
    _write_canonical,
    _read_existing_csv,
    _df_to_csv,
    _write_metadata,
    inspect,
)


def _make_nq_daily(n=50, start="2025-01-01"):
    """Create a fake NQ daily DataFrame."""
    dates = pd.date_range(start, periods=n, freq="B")
    import numpy as np
    rng = np.random.RandomState(42)
    close = 18000.0 + np.cumsum(rng.randn(n) * 50)
    return pd.DataFrame({
        "open": close - rng.uniform(10, 50, n),
        "high": close + rng.uniform(10, 80, n),
        "low": close - rng.uniform(10, 80, n),
        "close": close,
        "volume": rng.randint(100000, 500000, n),
    }, index=dates)


def _make_vix_daily(n=50, start="2025-01-01"):
    """Create a fake VIX daily DataFrame."""
    dates = pd.date_range(start, periods=n, freq="B")
    import numpy as np
    rng = np.random.RandomState(99)
    vix = 20.0 + rng.randn(n) * 3
    return pd.DataFrame({"vix": vix}, index=dates)


def _make_nq_hourly(n=200, start="2025-03-01"):
    """Create a fake NQ hourly DataFrame."""
    dates = pd.date_range(start, periods=n, freq="h")
    import numpy as np
    rng = np.random.RandomState(7)
    close = 18000.0 + np.cumsum(rng.randn(n) * 10)
    return pd.DataFrame({
        "open": close - rng.uniform(1, 10, n),
        "high": close + rng.uniform(1, 15, n),
        "low": close - rng.uniform(1, 15, n),
        "close": close,
        "volume": rng.randint(10000, 50000, n),
    }, index=dates)


# --- Merge tests ---

def test_merge_nq_vix_daily():
    nq = _make_nq_daily(50)
    vix = _make_vix_daily(50)
    merged = merge_nq_vix_daily(nq, vix)

    assert "vix" in merged.columns
    assert len(merged) == len(nq)
    assert merged["vix"].isna().sum() == 0


def test_merge_nq_vix_daily_missing_vix_dates():
    """NQ has more dates than VIX (futures trade some days VIX doesn't)."""
    nq = _make_nq_daily(50)
    vix = _make_vix_daily(30)  # fewer dates
    merged = merge_nq_vix_daily(nq, vix)

    assert len(merged) == len(nq)
    # VIX should be forward-filled, no NaNs
    assert merged["vix"].isna().sum() == 0


def test_merge_hourly_with_daily_vix():
    hourly = _make_nq_hourly(100)
    vix = _make_vix_daily(50, start="2025-02-01")
    merged = merge_hourly_with_daily_vix(hourly, vix)

    assert "vix" in merged.columns
    assert len(merged) == len(hourly)
    # All VIX values should be numeric (forward-filled from daily)
    assert all(isinstance(v, (int, float)) for v in merged["vix"])


# --- Incremental merge tests ---

def test_merge_incremental_new_only():
    new = _make_nq_daily(10)
    result = _merge_incremental(None, new)
    assert len(result) == 10


def test_merge_incremental_existing_only():
    existing = _make_nq_daily(10)
    result = _merge_incremental(existing, None)
    assert len(result) == 10


def test_merge_incremental_dedup():
    """Overlapping dates should keep the new data."""
    existing = _make_nq_daily(20, start="2025-01-01")
    # New data overlaps last 5 days + adds 5 new
    new = _make_nq_daily(10, start="2025-01-22")  # overlap starts ~Jan 22

    result = _merge_incremental(existing, new)
    # Should have no duplicate indices
    assert not result.index.duplicated().any()
    assert result.index.is_monotonic_increasing


# --- Storage tests ---

def test_csv_roundtrip(tmp_path):
    df = _make_nq_daily(20)
    path = tmp_path / "test.csv"
    _df_to_csv(df, path)

    loaded = _read_existing_csv(path)
    assert loaded is not None
    assert len(loaded) == 20
    assert list(loaded.columns) == list(df.columns)


def test_read_nonexistent_csv(tmp_path):
    result = _read_existing_csv(tmp_path / "nope.csv")
    assert result is None


# --- Canonical output tests ---

def test_write_canonical_format(tmp_path):
    """Canonical file should be readable by data.py's load_ohlcv."""
    nq = _make_nq_daily(30)
    vix = _make_vix_daily(30)
    merged = merge_nq_vix_daily(nq, vix)

    canonical_path = tmp_path / "NQ_1min.csv"
    _write_canonical(merged, canonical_path, granularity="daily")

    # Should be loadable by our existing loader
    from strategy_factory.data import load_ohlcv
    loaded = load_ohlcv(path=str(canonical_path))

    assert len(loaded) == 30
    assert loaded[0]["bar_index"] == 0
    assert isinstance(loaded[0]["open"], float)
    assert isinstance(loaded[0]["volume"], int)
    assert isinstance(loaded[0]["vix"], float)
    assert loaded[0]["vix"] != 20.0 or loaded[1]["vix"] != 20.0  # real VIX, not default


def test_canonical_usable_by_strategy(tmp_path):
    """Full pipeline: canonical CSV → features → strategy run."""
    from strategy_factory.data import load_ohlcv
    from strategy_factory.features import compute_features
    from strategy_factory.strategies import run_strategy
    from strategy_factory.config import DEFAULT_CONFIG

    nq = _make_nq_daily(200)
    vix = _make_vix_daily(200)
    merged = merge_nq_vix_daily(nq, vix)

    canonical_path = tmp_path / "NQ_1min.csv"
    _write_canonical(merged, canonical_path, granularity="daily")

    loaded = load_ohlcv(path=str(canonical_path))
    enriched = compute_features(loaded, DEFAULT_CONFIG["features"])
    trades = run_strategy("breakout", enriched, {
        "lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0, "min_atr": 0.5,
    })
    assert isinstance(trades, list)


# --- Metadata tests ---

def test_write_metadata(tmp_path):
    meta_path = tmp_path / "metadata.json"
    _write_metadata(
        meta_path,
        daily_info={"bars": 100, "source": "yfinance"},
        hourly_info={"bars": 500, "source": "yfinance"},
        canonical_info={"bars": 100, "granularity": "daily"},
    )

    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["sources"]["nq_daily"]["bars"] == 100
    assert meta["sources"]["nq_hourly"]["bars"] == 500
    assert "limitations" in meta
    assert len(meta["limitations"]) > 0


# --- Inspect tests ---

def test_inspect_empty_dir(tmp_path):
    info = inspect(data_dir=str(tmp_path))
    assert info["data_dir"] == str(tmp_path)
    for name, finfo in info["files"].items():
        assert finfo.get("exists") is False or finfo.get("bars", 0) == 0


def test_inspect_with_data(tmp_path):
    nq = _make_nq_daily(50)
    vix = _make_vix_daily(50)
    merged = merge_nq_vix_daily(nq, vix)

    daily_path = tmp_path / "nq_daily.csv"
    _df_to_csv(merged, daily_path)

    canonical_path = tmp_path / "NQ_1min.csv"
    _write_canonical(merged, canonical_path, granularity="daily")

    info = inspect(data_dir=str(tmp_path))
    assert info["files"]["nq_daily.csv"]["bars"] == 50
    assert info["files"]["NQ_1min.csv"]["bars"] == 50
