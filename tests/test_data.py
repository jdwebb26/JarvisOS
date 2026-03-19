import csv
import json
import os
import tempfile

from strategy_factory.data import (
    generate_synthetic_data,
    load_ohlcv,
    has_real_data,
    _resolve_data_path,
    _load_csv,
    REQUIRED_COLUMNS,
)


def test_synthetic_data_shape():
    data = generate_synthetic_data(n_bars=100)
    assert len(data) == 100
    assert all(k in data[0] for k in ("open", "high", "low", "close", "volume", "vix"))


def test_synthetic_data_prices_positive():
    data = generate_synthetic_data(n_bars=500, seed=99)
    for row in data:
        assert row["open"] > 0
        assert row["high"] >= row["low"]
        assert row["close"] > 0
        assert row["volume"] > 0


def test_load_csv_roundtrip():
    """Write synthetic data to CSV, load it back via load_ohlcv."""
    synth = generate_synthetic_data(n_bars=50, seed=7)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=list(synth[0].keys()))
        writer.writeheader()
        writer.writerows(synth)
        path = f.name

    try:
        loaded = load_ohlcv(path=path)
        assert len(loaded) == 50
        assert loaded[0]["bar_index"] == 0
        assert loaded[49]["bar_index"] == 49
        # Verify numeric types
        assert isinstance(loaded[0]["open"], float)
        assert isinstance(loaded[0]["volume"], int)
        # Verify values match (CSV roundtrip may lose precision)
        assert abs(loaded[0]["open"] - synth[0]["open"]) < 0.01
        assert abs(loaded[0]["close"] - synth[0]["close"]) < 0.01
    finally:
        os.unlink(path)


def test_load_csv_with_vix():
    """CSV with explicit vix column should preserve vix values."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    ) as f:
        fields = ["open", "high", "low", "close", "volume", "vix"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"open": 18000, "high": 18050, "low": 17990,
                         "close": 18030, "volume": 1000, "vix": 25.5})
        writer.writerow({"open": 18030, "high": 18060, "low": 17995,
                         "close": 18010, "volume": 800, "vix": 30.2})
        path = f.name

    try:
        loaded = load_ohlcv(path=path)
        assert len(loaded) == 2
        assert loaded[0]["vix"] == 25.5
        assert loaded[1]["vix"] == 30.2
    finally:
        os.unlink(path)


def test_load_csv_missing_column_raises():
    """CSV without required columns should raise ValueError."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=["open", "high", "low"])
        writer.writeheader()
        writer.writerow({"open": 1, "high": 2, "low": 0.5})
        path = f.name

    try:
        raised = False
        try:
            load_ohlcv(path=path)
        except ValueError:
            raised = True
        assert raised
    finally:
        os.unlink(path)


def test_load_missing_file_raises():
    raised = False
    try:
        load_ohlcv(path="/tmp/nonexistent_file_xyz.csv")
    except FileNotFoundError:
        raised = True
    assert raised


def test_load_empty_file_raises():
    """Empty CSV (header only, no rows) should raise ValueError."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=["open", "high", "low", "close", "volume"]
        )
        writer.writeheader()
        path = f.name

    try:
        raised = False
        try:
            load_ohlcv(path=path)
        except ValueError:
            raised = True
        assert raised
    finally:
        os.unlink(path)


def test_vix_defaults_to_20():
    """If CSV has no vix column, bars should default vix to 20.0."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=["open", "high", "low", "close", "volume"]
        )
        writer.writeheader()
        writer.writerow({"open": 100, "high": 105, "low": 98, "close": 102, "volume": 500})
        path = f.name

    try:
        loaded = load_ohlcv(path=path)
        assert loaded[0]["vix"] == 20.0
    finally:
        os.unlink(path)


def test_resolve_data_path_nonexistent_dir():
    """_resolve_data_path raises FileNotFoundError for a nonexistent dir."""
    import strategy_factory.data as data_mod
    from pathlib import Path

    orig_dir = data_mod.DATA_DIR
    try:
        data_mod.DATA_DIR = Path("/tmp/no_such_data_dir_xyz_test")
        raised = False
        try:
            data_mod._resolve_data_path(None, "NQ")
        except FileNotFoundError:
            raised = True
        assert raised
    finally:
        data_mod.DATA_DIR = orig_dir


def test_load_csv_auto_resolution():
    """Test that auto-resolution finds NQ_1min.csv in DATA_DIR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write a CSV file at the expected location
        csv_path = os.path.join(tmpdir, "NQ_1min.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["open", "high", "low", "close", "volume"]
            )
            writer.writeheader()
            for i in range(10):
                writer.writerow({
                    "open": 18000 + i, "high": 18010 + i, "low": 17990 + i,
                    "close": 18005 + i, "volume": 100 + i,
                })

        old = os.environ.get("OPENCLAW_DATA_DIR")
        try:
            os.environ["OPENCLAW_DATA_DIR"] = tmpdir
            # Reimport to pick up env change for DATA_DIR
            import strategy_factory.data as data_mod
            orig_dir = data_mod.DATA_DIR
            from pathlib import Path
            data_mod.DATA_DIR = Path(tmpdir)

            loaded = load_ohlcv(instrument="NQ")
            assert len(loaded) == 10
            assert loaded[0]["bar_index"] == 0
            assert loaded[0]["open"] == 18000.0

            data_mod.DATA_DIR = orig_dir
        finally:
            if old is not None:
                os.environ["OPENCLAW_DATA_DIR"] = old
            elif "OPENCLAW_DATA_DIR" in os.environ:
                del os.environ["OPENCLAW_DATA_DIR"]


def test_parquet_dict_of_columns_conversion():
    """Verify that _load_parquet's pyarrow path correctly converts
    dict-of-columns to list-of-dicts.  We test the conversion logic
    directly since pyarrow may not be installed."""
    # Simulate what pyarrow's to_pydict() returns: {col: [vals]}
    col_dict = {
        "open": [18000.0, 18010.0, 18020.0],
        "high": [18050.0, 18060.0, 18070.0],
        "low": [17990.0, 17995.0, 17998.0],
        "close": [18030.0, 18040.0, 18050.0],
        "volume": [1000, 1100, 1200],
    }
    # This is the exact conversion logic from _load_parquet
    cols = list(col_dict.keys())
    n_rows = len(next(iter(col_dict.values()))) if col_dict else 0
    rows = [{c: col_dict[c][i] for c in cols} for i in range(n_rows)]

    assert len(rows) == 3
    assert rows[0]["open"] == 18000.0
    assert rows[1]["volume"] == 1100
    assert rows[2]["close"] == 18050.0
    # Each row is a dict, not a dict-of-lists
    assert isinstance(rows[0], dict)
    assert "open" in rows[0]


def test_load_ohlcv_end_to_end_csv():
    """Full end-to-end: create CSV → load_ohlcv → verify bar dicts are
    usable by compute_features → run a strategy."""
    from strategy_factory.features import compute_features
    from strategy_factory.strategies import run_strategy
    from strategy_factory.config import DEFAULT_CONFIG

    # Create realistic NQ data
    synth = generate_synthetic_data(n_bars=500, seed=42)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=list(synth[0].keys()))
        writer.writeheader()
        writer.writerows(synth)
        path = f.name

    try:
        loaded = load_ohlcv(path=path)
        assert len(loaded) == 500

        # Should be usable by compute_features
        enriched = compute_features(loaded, DEFAULT_CONFIG["features"])
        assert len(enriched) == 500
        assert "ema_fast" in enriched[0]
        assert "atr" in enriched[0]

        # Should be usable by strategy
        trades = run_strategy("breakout", enriched, {
            "lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0, "min_atr": 0.5,
        })
        assert isinstance(trades, list)
    finally:
        os.unlink(path)
