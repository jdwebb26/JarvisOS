#!/usr/bin/env python3
"""Tests for intraday market context seam.

Proves:
  1. Intraday snapshot reads from NQ_hourly.csv
  2. Daily and intraday snapshots are distinct with different fields
  3. Provenance and freshness are explicit and tagged
  4. Intraday snapshot is NOT live streaming (source tag proves it)
  5. read_full_context returns both layers
  6. format_intraday_read produces readable output
  7. format_full_market_read combines both layers
  8. Intraday context changes when hourly data changes
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.market_context import (
    read_market_snapshot, read_intraday_snapshot, read_full_context,
    format_market_read, format_intraday_read, format_full_market_read,
)


def _write_hourly_csv(data_dir: Path, rows: list[dict]):
    """Write test NQ_hourly.csv data."""
    header = "open,high,low,close,volume,vix"
    lines = [header]
    for r in rows:
        lines.append(f"{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']},{r['vix']}")
    (data_dir / "NQ_hourly.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_daily_csv(data_dir: Path, rows: list[dict]):
    """Write test NQ_daily.csv data."""
    header = "open,high,low,close,volume,vix"
    lines = [header]
    for r in rows:
        lines.append(f"{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']},{r['vix']}")
    (data_dir / "NQ_daily.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def data_root(tmp_path):
    """Create a test root with both daily and hourly data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    daily = [
        {"open": 18200, "high": 18350, "low": 18150, "close": 18300, "volume": 100000, "vix": 20.5},
        {"open": 18300, "high": 18400, "low": 18250, "close": 18350, "volume": 120000, "vix": 19.8},
        {"open": 18350, "high": 18500, "low": 18300, "close": 18450, "volume": 110000, "vix": 19.2},
    ]
    _write_daily_csv(data_dir, daily)

    hourly = [
        {"open": 18400, "high": 18420, "low": 18380, "close": 18410, "volume": 5000, "vix": 19.2},
        {"open": 18410, "high": 18430, "low": 18390, "close": 18420, "volume": 4500, "vix": 19.1},
        {"open": 18420, "high": 18450, "low": 18400, "close": 18440, "volume": 6000, "vix": 19.0},
        {"open": 18440, "high": 18460, "low": 18420, "close": 18450, "volume": 5500, "vix": 18.9},
        {"open": 18450, "high": 18470, "low": 18430, "close": 18460, "volume": 4000, "vix": 18.8},
    ]
    _write_hourly_csv(data_dir, hourly)

    return tmp_path


class TestIntradaySnapshot:
    def test_reads_hourly_data(self, data_root):
        snap = read_intraday_snapshot(data_root)
        assert snap is not None
        assert snap["symbol"] == "NQ"
        assert snap["timeframe"] == "hourly"
        assert snap["last_close"] == 18460.0

    def test_intraday_change(self, data_root):
        snap = read_intraday_snapshot(data_root)
        # Change from first bar (18410) to last (18460) ≈ +0.27%
        assert snap["intraday_change_pct"] > 0

    def test_intraday_range(self, data_root):
        snap = read_intraday_snapshot(data_root)
        assert snap["intraday_high"] == 18470.0
        assert snap["intraday_low"] == 18380.0
        assert snap["intraday_range_pct"] > 0

    def test_hourly_trend(self, data_root):
        snap = read_intraday_snapshot(data_root)
        # Small monotonic rise with only 5 bars → may be "flat" or "up" depending on threshold
        assert snap["hourly_trend"] in ("up", "flat")

    def test_vix_from_latest_bar(self, data_root):
        snap = read_intraday_snapshot(data_root)
        assert snap["vix"] == 18.8

    def test_bars_used(self, data_root):
        snap = read_intraday_snapshot(data_root)
        assert snap["bars_used"] == 5

    def test_no_hourly_file_returns_none(self, tmp_path):
        (tmp_path / "data").mkdir()
        snap = read_intraday_snapshot(tmp_path)
        assert snap is None


class TestProvenance:
    def test_not_live_streaming(self, data_root):
        snap = read_intraday_snapshot(data_root)
        assert "NOT live streaming" in snap["data_source"]

    def test_daily_source_distinct(self, data_root):
        daily = read_market_snapshot(data_root)
        hourly = read_intraday_snapshot(data_root)
        assert "daily" in daily["data_source"]
        assert "hourly" in hourly["data_source"]

    def test_snapshot_timestamp(self, data_root):
        snap = read_intraday_snapshot(data_root)
        assert "snapshot_at" in snap
        assert "T" in snap["snapshot_at"]  # ISO format

    def test_freshness_field(self, data_root):
        snap = read_intraday_snapshot(data_root)
        # No metadata.json → freshness is None
        assert snap["data_freshness_hours"] is None


class TestDailyVsIntraday:
    def test_different_closes(self, data_root):
        daily = read_market_snapshot(data_root)
        hourly = read_intraday_snapshot(data_root)
        assert daily["last_close"] == 18450.0  # Last daily bar
        assert hourly["last_close"] == 18460.0  # Last hourly bar
        assert daily["last_close"] != hourly["last_close"]

    def test_daily_has_trend_5d(self, data_root):
        daily = read_market_snapshot(data_root)
        assert "trend_5d" in daily
        assert "hourly_trend" not in daily

    def test_hourly_has_hourly_trend(self, data_root):
        hourly = read_intraday_snapshot(data_root)
        assert "hourly_trend" in hourly
        assert "trend_5d" not in hourly


class TestFullContext:
    def test_returns_both(self, data_root):
        ctx = read_full_context(data_root)
        assert ctx["daily"] is not None
        assert ctx["intraday"] is not None

    def test_daily_only(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _write_daily_csv(data_dir, [
            {"open": 18200, "high": 18350, "low": 18150, "close": 18300, "volume": 100000, "vix": 20},
            {"open": 18300, "high": 18400, "low": 18250, "close": 18350, "volume": 120000, "vix": 19},
        ])
        ctx = read_full_context(tmp_path)
        assert ctx["daily"] is not None
        assert ctx["intraday"] is None


class TestFormatting:
    def test_format_intraday_read(self, data_root):
        snap = read_intraday_snapshot(data_root)
        text = format_intraday_read(snap)
        assert text is not None
        assert "hourly" in text
        assert "18460" in text
        assert "NOT live streaming" in text

    def test_format_intraday_none(self):
        assert format_intraday_read(None) is None

    def test_format_full_includes_both(self, data_root):
        text = format_full_market_read(data_root)
        assert "hourly" in text.lower()
        assert "daily" in text.lower() or "yfinance" in text.lower()


class TestIntradayChangesOutput:
    def test_different_data_different_snapshot(self, tmp_path):
        """Changing hourly data changes the intraday snapshot."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Uptrend data
        _write_hourly_csv(data_dir, [
            {"open": 18400, "high": 18420, "low": 18380, "close": 18410, "volume": 5000, "vix": 19},
            {"open": 18410, "high": 18500, "low": 18400, "close": 18490, "volume": 6000, "vix": 19},
        ])
        snap1 = read_intraday_snapshot(tmp_path)
        assert snap1["hourly_trend"] == "up"
        assert snap1["intraday_change_pct"] > 0

        # Replace with downtrend data
        _write_hourly_csv(data_dir, [
            {"open": 18500, "high": 18510, "low": 18400, "close": 18490, "volume": 5000, "vix": 22},
            {"open": 18490, "high": 18495, "low": 18350, "close": 18360, "volume": 7000, "vix": 23},
        ])
        snap2 = read_intraday_snapshot(tmp_path)
        assert snap2["hourly_trend"] == "down"
        assert snap2["intraday_change_pct"] < 0
        assert snap2["vix"] == 23.0
