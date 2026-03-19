import csv
import math
import os
import random
from pathlib import Path

# Default location for real OHLCV data files
DATA_DIR = Path(os.environ.get(
    "OPENCLAW_DATA_DIR",
    os.path.expanduser("~/.openclaw/workspace/data"),
))

# Required columns in real data files (order doesn't matter)
REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}


def load_ohlcv(path=None, instrument="NQ"):
    """Load real OHLCV+VIX bar data from Parquet or CSV.

    Resolution order:
        1. Explicit ``path`` argument
        2. ``DATA_DIR/<instrument>_1min.parquet``
        3. ``DATA_DIR/<instrument>_1min.csv``

    The file must contain at least: open, high, low, close, volume.
    A ``vix`` column is optional (defaults to 20.0 if absent).

    Returns:
        list[dict] — same bar-dict format used elsewhere, with bar_index added.

    Raises:
        FileNotFoundError: no data file found at any candidate path.
        ValueError: file is missing required columns or is empty.
    """
    resolved = _resolve_data_path(path, instrument)

    if resolved.suffix == ".parquet":
        rows = _load_parquet(resolved)
    else:
        rows = _load_csv(resolved)

    if not rows:
        raise ValueError(f"Data file is empty: {resolved}")

    missing = REQUIRED_COLUMNS - set(rows[0].keys())
    if missing:
        raise ValueError(
            f"Data file {resolved} missing columns: {sorted(missing)}"
        )

    # Normalise: add bar_index, ensure vix default, cast numerics
    out = []
    for i, row in enumerate(rows):
        out.append({
            "bar_index": i,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(float(row["volume"])),
            "vix": float(row.get("vix", 20.0)),
        })
    return out


def _resolve_data_path(path, instrument):
    """Find the real data file, raising FileNotFoundError if absent."""
    if path is not None:
        p = Path(path)
        if p.is_file():
            return p
        raise FileNotFoundError(f"Explicit data path not found: {p}")

    stem = f"{instrument.upper()}_1min"
    for ext in (".parquet", ".csv"):
        candidate = DATA_DIR / f"{stem}{ext}"
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        f"No data file found for {instrument}. "
        f"Looked in {DATA_DIR} for {stem}.parquet or {stem}.csv"
    )


def _load_parquet(path):
    """Load a Parquet file into list[dict]. Requires pyarrow or pandas."""
    try:
        import pyarrow.parquet as pq
        table = pq.read_table(str(path))
        # to_pydict() returns {col: [vals]} — transpose to list[dict]
        col_dict = table.to_pydict()
        cols = list(col_dict.keys())
        n_rows = len(next(iter(col_dict.values()))) if col_dict else 0
        return [{c: col_dict[c][i] for c in cols} for i in range(n_rows)]
    except ImportError:
        pass

    try:
        import pandas as pd
        df = pd.read_parquet(str(path))
        return df.to_dict("records")
    except ImportError:
        raise ImportError(
            "Reading Parquet requires pyarrow or pandas. "
            "Install one: pip install pyarrow"
        )


def _load_csv(path):
    """Load a CSV file into list[dict]."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def load_dataset_metadata(path=None, instrument="NQ"):
    """Load the sidecar .meta.json for a dataset file.

    Resolution: looks for ``<data_file>.meta.json`` next to the resolved
    data file.  Returns the parsed dict, or None if no sidecar exists.
    """
    import json as _json

    try:
        data_path = _resolve_data_path(path, instrument)
    except FileNotFoundError:
        return None

    sidecar = Path(str(data_path) + ".meta.json")
    if not sidecar.is_file():
        return None

    try:
        return _json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_named_dataset(dataset_id, data_dir=None):
    """Load a named dataset (e.g., 'NQ_daily', 'NQ_hourly') from DATA_DIR.

    Looks for ``<dataset_id>.csv`` with optional ``.meta.json`` sidecar.

    Returns:
        (bars, metadata) where bars is list[dict] and metadata is dict or None.

    Raises:
        FileNotFoundError if dataset file doesn't exist.
    """
    d = Path(data_dir) if data_dir else DATA_DIR
    csv_path = d / f"{dataset_id}.csv"

    if not csv_path.is_file():
        raise FileNotFoundError(f"Dataset not found: {csv_path}")

    bars = load_ohlcv(path=str(csv_path))
    meta = load_dataset_metadata(path=str(csv_path))
    return bars, meta


def list_datasets(data_dir=None):
    """List available named datasets in DATA_DIR.

    Returns list of dicts with dataset_id, file, bars (if sidecar exists).
    """
    import json as _json
    d = Path(data_dir) if data_dir else DATA_DIR
    if not d.is_dir():
        return []

    datasets = []
    for csv_file in sorted(d.glob("NQ_*.csv")):
        # Skip sidecars and legacy files
        if csv_file.name == "NQ_1min.csv":
            continue
        dataset_id = csv_file.stem
        meta_path = Path(str(csv_file) + ".meta.json")
        meta = None
        if meta_path.is_file():
            try:
                meta = _json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        datasets.append({
            "dataset_id": dataset_id,
            "file": str(csv_file),
            "granularity": meta.get("data_granularity") if meta else None,
            "row_count": meta.get("row_count") if meta else None,
            "coverage_start": meta.get("coverage_start") if meta else None,
            "coverage_end": meta.get("coverage_end") if meta else None,
        })
    return datasets


def has_real_data(instrument="NQ"):
    """Return True if a real data file exists for the given instrument."""
    try:
        _resolve_data_path(None, instrument)
        return True
    except FileNotFoundError:
        return False


def generate_synthetic_data(n_bars=30000, seed=42):
    """Generate synthetic NQ-like bar data for testing / fallback."""
    rng = random.Random(seed)
    rows = []
    price = 18000.0

    for i in range(n_bars):
        drift = math.sin(i / 60.0) * 2.0
        shock = rng.uniform(-8.0, 8.0)
        delta = drift + shock
        o = price
        c = max(100.0, price + delta)
        h = max(o, c) + abs(rng.uniform(0.0, 4.0))
        l = min(o, c) - abs(rng.uniform(0.0, 4.0))
        v = int(100 + abs(shock) * 25 + rng.uniform(0, 100))
        vix = max(10.0, min(60.0, 18.0 + abs(shock) * 0.8 + rng.uniform(-2.0, 2.0)))
        rows.append({
            "bar_index": i,
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": v,
            "vix": round(vix, 2),
        })
        price = c

    return rows
