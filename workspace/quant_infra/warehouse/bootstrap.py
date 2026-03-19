#!/usr/bin/env python3
"""Bootstrap the DuckDB quant warehouse.

Creates the database file, applies schema and views, and loads
existing OHLCV CSV data from the cron pipeline.

Usage:
    .venv/bin/python3 workspace/quant_infra/warehouse/bootstrap.py
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import duckdb
except ImportError:
    print("ERROR: duckdb not installed. Run: .venv/bin/pip install duckdb")
    sys.exit(1)

THIS_DIR = Path(__file__).resolve().parent
QUANT_INFRA = THIS_DIR.parent
DB_PATH = THIS_DIR / "quant.duckdb"
SQL_DIR = THIS_DIR / "sql"
DATA_DIR = Path.home() / ".openclaw" / "workspace" / "data"


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL line comments while preserving statement structure."""
    lines = []
    for line in sql.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("--"):
            lines.append(line)
    return "\n".join(lines)


def apply_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Apply schema.sql to create tables."""
    schema_file = SQL_DIR / "schema.sql"
    if not schema_file.exists():
        print(f"ERROR: schema file not found at {schema_file}")
        sys.exit(1)
    sql = _strip_sql_comments(schema_file.read_text())
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if stmt:
            con.execute(stmt)
    print("[warehouse] Schema applied.")


def apply_migrations(con: duckdb.DuckDBPyConnection) -> None:
    """Apply incremental schema migrations for existing databases."""
    migrations = [
        # 2026-03-19: Add fill_status for live trading fill rate tracking
        ("kitt_paper_positions", "fill_status",
         "ALTER TABLE kitt_paper_positions ADD COLUMN fill_status VARCHAR NOT NULL DEFAULT 'filled'"),
        # 2026-03-19: Add strategy_id for multi-strategy tracking
        ("kitt_paper_positions", "strategy_id",
         "ALTER TABLE kitt_paper_positions ADD COLUMN strategy_id VARCHAR"),
    ]
    for table, column, sql in migrations:
        try:
            cols = [r[0] for r in con.execute(
                f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'"
            ).fetchall()]
            if column not in cols:
                con.execute(sql)
                print(f"[warehouse] Migration: added {table}.{column}")
        except Exception as exc:
            print(f"[warehouse] Migration skip ({table}.{column}): {exc}")


def apply_views(con: duckdb.DuckDBPyConnection) -> None:
    """Apply views.sql to create analytical views."""
    views_file = SQL_DIR / "views.sql"
    if not views_file.exists():
        print(f"WARN: views file not found at {views_file}")
        return
    sql = _strip_sql_comments(views_file.read_text())
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if stmt:
            con.execute(stmt)
    print("[warehouse] Views applied.")


def load_csv_ohlcv(con: duckdb.DuckDBPyConnection, csv_path: Path, symbol: str = "NQ") -> int:
    """Load OHLCV CSV data into ohlcv_daily table.

    Expected CSV format: open,high,low,close,volume,vix (no date column — index-based).
    Falls back to checking for a 'date' column if present.
    """
    if not csv_path.exists():
        print(f"WARN: CSV not found: {csv_path}")
        return 0

    # Read CSV to check structure
    with open(csv_path, "r") as f:
        reader = csv.reader(f)
        header = [h.strip().lower() for h in next(reader)]

    has_date = "date" in header

    # Use DuckDB's CSV reader for speed
    if has_date:
        # CSV has date column — use it directly
        con.execute(f"""
            INSERT INTO ohlcv_daily (symbol, bar_date, open, high, low, close, volume, vix)
            SELECT
                '{symbol}' as symbol,
                CAST(date AS DATE) as bar_date,
                CAST(open AS DOUBLE),
                CAST(high AS DOUBLE),
                CAST(low AS DOUBLE),
                CAST(close AS DOUBLE),
                CAST(volume AS BIGINT),
                CAST(vix AS DOUBLE)
            FROM read_csv_auto('{csv_path}')
            WHERE open IS NOT NULL
            ON CONFLICT DO NOTHING
        """)
    else:
        # CSV has no date column — synthesize dates from row index
        # Read all rows, assign sequential trading dates
        rows = []
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    rows.append((
                        float(row.get("open", 0)),
                        float(row.get("high", 0)),
                        float(row.get("low", 0)),
                        float(row.get("close", 0)),
                        int(float(row.get("volume", 0))),
                        float(row.get("vix", 0)) if row.get("vix") else None,
                    ))
                except (ValueError, TypeError):
                    continue

        if not rows:
            return 0

        # Generate trading dates (skip weekends) counting back from today
        from datetime import timedelta
        today = datetime.now(timezone.utc).date()
        dates = []
        d = today
        for _ in range(len(rows)):
            while d.weekday() >= 5:  # skip weekends
                d -= timedelta(days=1)
            dates.insert(0, d)
            d -= timedelta(days=1)

        for date, (o, h, l, c, v, vix) in zip(dates, rows):
            try:
                con.execute("""
                    INSERT INTO ohlcv_daily (symbol, bar_date, open, high, low, close, volume, vix)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                """, [symbol, str(date), o, h, l, c, v, vix])
            except Exception:
                continue

    count = con.execute(f"SELECT COUNT(*) FROM ohlcv_daily WHERE symbol = '{symbol}'").fetchone()[0]
    return count


def main():
    print(f"[warehouse] Bootstrapping DuckDB at {DB_PATH}")

    con = duckdb.connect(str(DB_PATH))
    try:
        apply_schema(con)
        apply_migrations(con)
        apply_views(con)

        # Load NQ daily CSV if available
        nq_csv = DATA_DIR / "NQ_daily.csv"
        if nq_csv.exists():
            count = load_csv_ohlcv(con, nq_csv, symbol="NQ")
            print(f"[warehouse] Loaded {count} NQ daily bars from {nq_csv}")
        else:
            print(f"[warehouse] No NQ_daily.csv found at {DATA_DIR}")

        # Show summary
        tables = con.execute("SHOW TABLES").fetchall()
        print(f"\n[warehouse] Tables: {[t[0] for t in tables]}")
        for table in tables:
            count = con.execute(f"SELECT COUNT(*) FROM {table[0]}").fetchone()[0]
            print(f"  {table[0]}: {count} rows")

        # Show views
        views = con.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_type = 'VIEW'
        """).fetchall()
        print(f"\n[warehouse] Views: {[v[0] for v in views]}")

    finally:
        con.close()

    print(f"\n[warehouse] Bootstrap complete. DB at {DB_PATH}")


if __name__ == "__main__":
    main()
