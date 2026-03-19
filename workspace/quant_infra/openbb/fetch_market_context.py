#!/usr/bin/env python3
"""Fetch market context via OpenBB and store in DuckDB warehouse.

Run with the OpenBB venv:
    workspace/quant_infra/env/.venv-openbb/bin/python3 \\
        workspace/quant_infra/openbb/fetch_market_context.py

Or from project root (uses subprocess to call OpenBB venv):
    .venv/bin/python3 workspace/quant_infra/openbb/fetch_market_context.py --subprocess
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Resolve paths
THIS_DIR = Path(__file__).resolve().parent
QUANT_INFRA = THIS_DIR.parent
PROJECT_ROOT = QUANT_INFRA.parent.parent
WAREHOUSE_PATH = QUANT_INFRA / "warehouse" / "quant.duckdb"
PACKETS_DIR = QUANT_INFRA / "packets"
RESEARCH_DIR = QUANT_INFRA / "research"


def _run_fetch() -> dict:
    """Execute the OpenBB fetch and return the snapshot."""
    from adapter import fetch_market_snapshot, build_environment_record
    print("[openbb] Fetching market snapshot...")
    snapshot = fetch_market_snapshot()
    print(f"[openbb] Snapshot captured at {snapshot['captured_at']}")
    return snapshot


def _store_to_duckdb(snapshot: dict) -> None:
    """Store environment snapshot in DuckDB warehouse."""
    try:
        import duckdb
    except ImportError:
        print("[openbb] WARN: duckdb not available in this venv, skipping warehouse store")
        return

    if not WAREHOUSE_PATH.exists():
        print(f"[openbb] WARN: warehouse not found at {WAREHOUSE_PATH}, skipping")
        return

    from adapter import build_environment_record
    record = build_environment_record(snapshot)

    con = duckdb.connect(str(WAREHOUSE_PATH))
    try:
        con.execute("""
            INSERT INTO market_environment_snapshots
            (snapshot_id, captured_at, symbol, last_close, vix_level,
             trend_5d, range_5d_pct, regime, macro_summary, data_source,
             freshness_hours, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            record["snapshot_id"],
            record["captured_at"],
            record["symbol"],
            record["last_close"],
            record["vix_level"],
            record["trend_5d"],
            record["range_5d_pct"],
            record["regime"],
            record["macro_summary"],
            record["data_source"],
            record["freshness_hours"],
            record["raw_json"],
        ])
        print(f"[openbb] Stored environment snapshot {record['snapshot_id']} in DuckDB")
    finally:
        con.close()


def _store_news_to_duckdb(snapshot: dict) -> None:
    """Store news items in DuckDB warehouse."""
    try:
        import duckdb
    except ImportError:
        return

    if not WAREHOUSE_PATH.exists():
        return

    news_data = snapshot.get("news", {})
    if news_data.get("status") != "ok":
        return

    items = news_data.get("data", [])
    if not isinstance(items, list):
        return

    import uuid
    con = duckdb.connect(str(WAREHOUSE_PATH))
    try:
        count = 0
        for item in items[:20]:
            if not isinstance(item, dict):
                continue
            item_id = f"news-{uuid.uuid4().hex[:12]}"
            headline = item.get("title") or item.get("headline") or ""
            if not headline:
                continue
            try:
                con.execute("""
                    INSERT INTO market_news_items
                    (item_id, published_at, source, headline, summary, symbols, url, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    item_id,
                    item.get("date") or item.get("published_at"),
                    item.get("source") or news_data.get("provider", "unknown"),
                    headline,
                    item.get("text") or item.get("summary") or "",
                    item.get("symbols") or "",
                    item.get("url") or "",
                    json.dumps(item, default=str),
                ])
                count += 1
            except Exception:
                continue
        print(f"[openbb] Stored {count} news items in DuckDB")
    finally:
        con.close()


def _write_hermes_packet(snapshot: dict) -> None:
    """Write a Hermes-style environment synthesis packet."""
    from adapter import build_environment_record
    record = build_environment_record(snapshot)
    now = datetime.now(timezone.utc).isoformat()

    packet = {
        "packet_type": "hermes_synthesis",
        "lane": "hermes",
        "timestamp": now,
        "version": "1.0.0",
        "summary": f"Market environment: NQ={record['last_close']}, VIX={record['vix_level']}, regime={record['regime']}",
        "upstream": ["scout_recon"],
        "data": {
            "nq_close": record["last_close"],
            "vix_level": record["vix_level"],
            "regime": record["regime"],
            "macro_summary": record["macro_summary"],
        },
        "metadata": {
            "source_module": "openbb.fetch_market_context",
            "data_freshness_hours": record["freshness_hours"],
            "confidence": 0.7 if record["last_close"] else 0.3,
        },
    }

    out = PACKETS_DIR / "hermes" / "latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(packet, indent=2, default=str) + "\n")
    print(f"[openbb] Wrote hermes packet → {out}")


def _write_research_artifact(snapshot: dict) -> None:
    """Write a human-readable market environment summary."""
    from adapter import build_environment_record
    record = build_environment_record(snapshot)
    now = datetime.now(timezone.utc)

    md = f"""# Market Environment — {now.strftime('%Y-%m-%d %H:%M UTC')}

## Snapshot
- **NQ Close**: {record['last_close']}
- **VIX**: {record['vix_level']}
- **Regime**: {record['regime']}
- **Data Source**: {record['data_source']}

## News Summary
"""
    news = snapshot.get("news", {}).get("data", [])
    if isinstance(news, list):
        for item in news[:10]:
            if isinstance(item, dict):
                title = item.get("title") or item.get("headline") or "untitled"
                md += f"- {title}\n"
    else:
        md += "- No news available\n"

    out = RESEARCH_DIR / "environment" / "latest.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    print(f"[openbb] Wrote environment research → {out}")


def main():
    # Ensure we can import from this directory
    if str(THIS_DIR) not in sys.path:
        sys.path.insert(0, str(THIS_DIR))

    snapshot = _run_fetch()

    # Store to DuckDB
    _store_to_duckdb(snapshot)
    _store_news_to_duckdb(snapshot)

    # Write packets and research artifacts
    _write_hermes_packet(snapshot)
    _write_research_artifact(snapshot)

    # Save raw snapshot for debugging
    raw_out = QUANT_INFRA / "warehouse" / "snapshots" / "latest_openbb.json"
    raw_out.parent.mkdir(parents=True, exist_ok=True)
    raw_out.write_text(json.dumps(snapshot, indent=2, default=str) + "\n")
    print(f"[openbb] Raw snapshot → {raw_out}")

    print("[openbb] Done.")


if __name__ == "__main__":
    main()
