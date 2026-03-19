#!/usr/bin/env python3
"""Fetch market context via OpenBB and store in DuckDB warehouse.

Produces outputs for Scout, Hermes, and operator consumption.
Each fetch section degrades independently — partial data is always
better than no data.

Run with the OpenBB venv:
    workspace/quant_infra/env/.venv-openbb/bin/python3 \
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
    from adapter import fetch_market_snapshot
    print("[openbb] Fetching market snapshot...")
    snapshot = fetch_market_snapshot()
    print(f"[openbb] Snapshot captured at {snapshot['captured_at']}")

    # Print fetch report
    report = snapshot.get("fetch_report", {})
    for section, info in report.items():
        status = info.get("status", "?")
        source = info.get("source", "?")
        marker = "OK" if status == "ok" else "FAIL"
        print(f"[openbb]   {section}: {marker} (source: {source})")

    return snapshot


# ---------------------------------------------------------------------------
# DuckDB storage
# ---------------------------------------------------------------------------

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
    except Exception as e:
        print(f"[openbb] WARN: DuckDB insert failed: {e}")
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


# ---------------------------------------------------------------------------
# Scout packet — headlines, market-moving items, event watchlist
# ---------------------------------------------------------------------------

def _write_scout_packet(snapshot: dict) -> None:
    """Write a Scout recon packet emphasizing headlines and events."""
    from adapter import build_environment_record
    record = build_environment_record(snapshot)
    now = datetime.now(timezone.utc).isoformat()
    report = snapshot.get("fetch_report", {})

    # Build headline list from news
    headlines = []
    news_data = snapshot.get("news", {})
    news_source = news_data.get("source", "unknown")
    if news_data.get("status") == "ok":
        for item in (news_data.get("data") or [])[:15]:
            if isinstance(item, dict):
                title = item.get("title") or item.get("headline") or ""
                if title:
                    headlines.append({
                        "title": title,
                        "source": item.get("source") or item.get("publisher") or news_source,
                        "url": item.get("url") or item.get("link") or "",
                        "date": str(item.get("date") or item.get("published_at") or ""),
                        "symbols": item.get("symbols") or "",
                    })

    # Build event watchlist from calendar
    events = []
    cal_data = snapshot.get("calendar", {})
    if cal_data.get("status") == "ok":
        for ev in (cal_data.get("data") or [])[:10]:
            if isinstance(ev, dict):
                events.append({
                    "event": ev.get("event") or ev.get("name") or ev.get("description") or "unknown",
                    "date": str(ev.get("date") or ev.get("event_date") or ""),
                    "country": ev.get("country") or "",
                    "impact": ev.get("impact") or ev.get("importance") or "",
                })

    # Source confidence based on what actually worked
    sections_ok = sum(1 for s in report.values() if s.get("status") == "ok")
    sections_total = max(len(report), 1)
    confidence = round(0.3 + 0.7 * (sections_ok / sections_total), 2)

    # Fetch path summary
    fetch_paths = {k: v.get("source", "unknown") for k, v in report.items()}

    data = {
        "headlines": headlines,
        "headline_count": len(headlines),
        "market_movers": {
            "nq_close": record["last_close"],
            "vix_level": record["vix_level"],
            "spy_close": record.get("spy_close"),
            "qqq_close": record.get("qqq_close"),
            "regime": record["regime"],
        },
        "event_watchlist": events,
        "event_count": len(events),
        "fetch_paths": fetch_paths,
        "options_chain": {"status": "not configured", "note": "Options chain fetch not yet implemented"},
        "premium_news": {"status": "not configured", "note": "Premium news provider not yet configured"},
    }

    packet = {
        "packet_type": "scout_recon",
        "lane": "scout",
        "timestamp": now,
        "version": "1.1.0",
        "summary": f"Scout: {len(headlines)} headlines, {len(events)} events | NQ={record['last_close']}, VIX={record['vix_level']}",
        "upstream": [],
        "data": data,
        "metadata": {
            "source_module": "openbb.fetch_market_context",
            "data_freshness_hours": record["freshness_hours"],
            "confidence": confidence,
        },
    }

    out = PACKETS_DIR / "scout" / "latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(packet, indent=2, default=str) + "\n")

    # Timestamped copy
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    ts_path = PACKETS_DIR / "scout" / f"scout_recon_{ts}.json"
    ts_path.write_text(json.dumps(packet, indent=2, default=str) + "\n")

    print(f"[openbb] Wrote scout packet -> {out}")


# ---------------------------------------------------------------------------
# Hermes packet — synthesized environment, macro/risk regime, actionable items
# ---------------------------------------------------------------------------

def _write_hermes_packet(snapshot: dict) -> None:
    """Write a Hermes synthesis packet emphasizing environment and risk regime."""
    from adapter import build_environment_record
    record = build_environment_record(snapshot)
    now = datetime.now(timezone.utc).isoformat()
    report = snapshot.get("fetch_report", {})

    # Build actionable bullets from market data
    bullets: list[str] = []
    uncertainties: list[str] = []

    if record["vix_level"] is not None:
        vix = record["vix_level"]
        if vix > 30:
            bullets.append(f"VIX at {vix} — crisis-level volatility, extreme caution warranted")
        elif vix > 25:
            bullets.append(f"VIX at {vix} — elevated volatility, tighten risk parameters")
        elif vix < 15:
            bullets.append(f"VIX at {vix} — unusually low vol, watch for complacency snap")
        else:
            bullets.append(f"VIX at {vix} — normal volatility regime")
    else:
        uncertainties.append("VIX data unavailable — regime classification unreliable")

    if record["last_close"] is not None:
        bullets.append(f"NQ last close: {record['last_close']}")
    else:
        uncertainties.append("NQ price data unavailable")

    if record.get("spy_close") is not None:
        bullets.append(f"SPY: {record['spy_close']}")
    if record.get("qqq_close") is not None:
        bullets.append(f"QQQ: {record['qqq_close']}")

    # Track missing data
    for section, info in report.items():
        if info.get("status") != "ok":
            uncertainties.append(f"{section} fetch failed (source: {info.get('source', 'unknown')})")

    sections_ok = sum(1 for s in report.values() if s.get("status") == "ok")
    sections_total = max(len(report), 1)
    confidence = round(0.3 + 0.7 * (sections_ok / sections_total), 2)

    # News digest for Hermes (condensed)
    news_digest: list[str] = []
    news_data = snapshot.get("news", {})
    if news_data.get("status") == "ok":
        for item in (news_data.get("data") or [])[:5]:
            if isinstance(item, dict):
                title = item.get("title") or item.get("headline") or ""
                if title:
                    news_digest.append(title)

    data = {
        "environment": {
            "nq_close": record["last_close"],
            "vix_level": record["vix_level"],
            "spy_close": record.get("spy_close"),
            "qqq_close": record.get("qqq_close"),
            "regime": record["regime"],
        },
        "macro_summary": record["macro_summary"],
        "actionable_bullets": bullets,
        "uncertainties": uncertainties,
        "news_digest": news_digest,
        "data_sources": record["data_source"],
        "options_risk": {"status": "not configured", "note": "Options/risk analysis not yet implemented"},
    }

    packet = {
        "packet_type": "hermes_synthesis",
        "lane": "hermes",
        "timestamp": now,
        "version": "1.1.0",
        "summary": f"Market environment: {record['macro_summary']}",
        "upstream": ["scout_recon"],
        "data": data,
        "metadata": {
            "source_module": "openbb.fetch_market_context",
            "data_freshness_hours": record["freshness_hours"],
            "confidence": confidence,
        },
    }

    out = PACKETS_DIR / "hermes" / "latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(packet, indent=2, default=str) + "\n")

    # Timestamped copy
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    ts_path = PACKETS_DIR / "hermes" / f"hermes_synthesis_{ts}.json"
    ts_path.write_text(json.dumps(packet, indent=2, default=str) + "\n")

    print(f"[openbb] Wrote hermes packet -> {out}")


# ---------------------------------------------------------------------------
# Research artifacts — clean, operator-readable markdown
# ---------------------------------------------------------------------------

def _write_environment_artifact(snapshot: dict) -> None:
    """Write a clean, operator-readable market environment summary."""
    from adapter import build_environment_record
    record = build_environment_record(snapshot)
    now = datetime.now(timezone.utc)
    report = snapshot.get("fetch_report", {})

    # Section status markers
    def _marker(section: str) -> str:
        info = report.get(section, {})
        if info.get("status") == "ok":
            return info.get("source", "ok")
        return "UNAVAILABLE"

    md = f"""# Market Environment — {now.strftime('%Y-%m-%d %H:%M UTC')}

## Prices
| Symbol | Value | Source |
|--------|-------|--------|
| NQ (E-mini Nasdaq) | {record['last_close'] or 'unavailable'} | {_marker('quotes')} |
| VIX | {record['vix_level'] or 'unavailable'} | {_marker('vix')} |
| SPY | {record.get('spy_close') or 'unavailable'} | {_marker('quotes')} |
| QQQ | {record.get('qqq_close') or 'unavailable'} | {_marker('quotes')} |

## Regime
- **Classification**: {record['regime']}
- **Macro Summary**: {record['macro_summary']}

## Data Provenance
| Section | Status | Source |
|---------|--------|--------|
"""
    for section, info in report.items():
        status = "OK" if info.get("status") == "ok" else "FAILED"
        source = info.get("source", "unknown")
        md += f"| {section} | {status} | {source} |\n"

    # Calendar events
    cal_data = snapshot.get("calendar", {})
    if cal_data.get("status") == "ok" and cal_data.get("data"):
        md += "\n## Upcoming Economic Events\n"
        for ev in (cal_data.get("data") or [])[:8]:
            if isinstance(ev, dict):
                name = ev.get("event") or ev.get("name") or ev.get("description") or "?"
                date = ev.get("date") or ev.get("event_date") or ""
                md += f"- **{date}** — {name}\n"
    else:
        md += "\n## Upcoming Economic Events\n- Calendar data unavailable\n"

    # Options / Risk stubs
    md += """
## Options Chain
- Status: **not configured** — options chain fetch not yet implemented

## Risk Assessment
- Status: **not configured** — premium risk analysis not yet implemented
"""

    md += f"\n---\n*Generated at {now.isoformat()} by openbb.fetch_market_context*\n"

    out = RESEARCH_DIR / "environment" / "latest.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)

    # Timestamped copy
    ts = now.strftime("%Y%m%dT%H%M%S")
    ts_out = RESEARCH_DIR / "environment" / f"environment_{ts}.md"
    ts_out.write_text(md)

    print(f"[openbb] Wrote environment research -> {out}")


def _write_news_artifact(snapshot: dict) -> None:
    """Write a clean, operator-readable news summary."""
    now = datetime.now(timezone.utc)
    news_data = snapshot.get("news", {})
    report = snapshot.get("fetch_report", {})
    news_source = report.get("news", {}).get("source", "unknown")

    md = f"""# Market News — {now.strftime('%Y-%m-%d %H:%M UTC')}

**Source**: {news_source}
**Status**: {"OK" if news_data.get("status") == "ok" else "FAILED"}

"""

    if news_data.get("status") == "ok":
        items = news_data.get("data") or []
        if isinstance(items, list) and items:
            md += "## Headlines\n\n"
            for i, item in enumerate(items[:20], 1):
                if isinstance(item, dict):
                    title = item.get("title") or item.get("headline") or "untitled"
                    source = item.get("source") or item.get("publisher") or ""
                    date = item.get("date") or item.get("published_at") or ""
                    md += f"{i}. **{title}**\n"
                    parts = []
                    if source:
                        parts.append(f"Source: {source}")
                    if date:
                        parts.append(f"Date: {date}")
                    if parts:
                        md += f"   - {' | '.join(parts)}\n"
        else:
            md += "No headlines available.\n"
    else:
        error = news_data.get("error", "unknown error")
        md += f"News fetch failed: {error}\n"

    md += """
## Premium News
- Status: **not configured** — premium news provider not yet set up

"""
    md += f"---\n*Generated at {now.isoformat()} by openbb.fetch_market_context*\n"

    out = RESEARCH_DIR / "news" / "latest.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)

    # Timestamped copy
    ts = now.strftime("%Y%m%dT%H%M%S")
    ts_out = RESEARCH_DIR / "news" / f"news_{ts}.md"
    ts_out.write_text(md)

    print(f"[openbb] Wrote news research -> {out}")


def _write_risk_stub() -> None:
    """Write a clean stub for risk research."""
    now = datetime.now(timezone.utc)
    md = f"""# Risk Assessment — {now.strftime('%Y-%m-%d %H:%M UTC')}

## Status
**Not configured** — risk analysis module is not yet implemented.

When implemented, this will include:
- Portfolio risk metrics
- Correlation analysis
- Tail risk estimates
- Regime-specific risk adjustments

---
*Generated at {now.isoformat()} by openbb.fetch_market_context*
"""
    out = RESEARCH_DIR / "risk" / "latest.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)


def _write_options_stub() -> None:
    """Write a clean stub for options research."""
    now = datetime.now(timezone.utc)
    md = f"""# Options Chain — {now.strftime('%Y-%m-%d %H:%M UTC')}

## Status
**Not configured** — options chain fetch is not yet implemented.

When implemented, this will include:
- NQ options chain (key strikes)
- Put/call ratio
- Implied volatility surface
- Max pain levels
- Notable open interest concentrations

---
*Generated at {now.isoformat()} by openbb.fetch_market_context*
"""
    out = RESEARCH_DIR / "options" / "latest.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def main():
    # Ensure we can import from this directory
    if str(THIS_DIR) not in sys.path:
        sys.path.insert(0, str(THIS_DIR))

    snapshot = _run_fetch()

    # Store to DuckDB (non-fatal if it fails)
    try:
        _store_to_duckdb(snapshot)
    except Exception as e:
        print(f"[openbb] WARN: DuckDB environment store failed: {e}")

    try:
        _store_news_to_duckdb(snapshot)
    except Exception as e:
        print(f"[openbb] WARN: DuckDB news store failed: {e}")

    # Write packets (Scout + Hermes)
    try:
        _write_scout_packet(snapshot)
    except Exception as e:
        print(f"[openbb] WARN: Scout packet write failed: {e}")

    try:
        _write_hermes_packet(snapshot)
    except Exception as e:
        print(f"[openbb] WARN: Hermes packet write failed: {e}")

    # Write research artifacts
    try:
        _write_environment_artifact(snapshot)
    except Exception as e:
        print(f"[openbb] WARN: Environment artifact write failed: {e}")

    try:
        _write_news_artifact(snapshot)
    except Exception as e:
        print(f"[openbb] WARN: News artifact write failed: {e}")

    # Write stubs for not-yet-implemented sections
    try:
        _write_risk_stub()
        _write_options_stub()
    except Exception as e:
        print(f"[openbb] WARN: Stub write failed: {e}")

    # Save raw snapshot for debugging
    raw_out = QUANT_INFRA / "warehouse" / "snapshots" / "latest_openbb.json"
    raw_out.parent.mkdir(parents=True, exist_ok=True)
    raw_out.write_text(json.dumps(snapshot, indent=2, default=str) + "\n")
    print(f"[openbb] Raw snapshot -> {raw_out}")

    # Print summary
    report = snapshot.get("fetch_report", {})
    ok = sum(1 for s in report.values() if s.get("status") == "ok")
    total = len(report)
    print(f"[openbb] Done. {ok}/{total} sections succeeded.")


if __name__ == "__main__":
    main()
