"""OpenBB adapter — structured market data fetching.

Uses OpenBB Platform SDK to pull market context, news, economic data.
Requires Python 3.12 venv with OpenBB installed.

This module is designed to be imported by fetch_market_context.py (which runs
in the 3.12 venv) or called via subprocess from the main runtime (Python 3.14).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _to_serializable(obj: Any) -> Any:
    """Convert OpenBB result objects to JSON-serializable dicts."""
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "results") and obj.results is not None:
        items = obj.results
        if isinstance(items, list):
            return [_to_serializable(i) for i in items]
        return _to_serializable(items)
    return obj


def fetch_equity_quote(symbols: list[str], provider: str = "yfinance") -> dict:
    """Fetch latest equity/futures quotes via OpenBB."""
    from openbb import obb
    try:
        result = obb.equity.price.quote(symbol=",".join(symbols), provider=provider)
        data = _to_serializable(result)
        return {"status": "ok", "data": data, "provider": provider}
    except Exception as e:
        logger.error("equity quote failed: %s", e)
        return {"status": "error", "error": str(e), "provider": provider}


def fetch_equity_historical(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    interval: str = "1d",
    provider: str = "yfinance",
) -> dict:
    """Fetch historical OHLCV data."""
    from openbb import obb
    try:
        kwargs: dict[str, Any] = {"symbol": symbol, "provider": provider, "interval": interval}
        if start_date:
            kwargs["start_date"] = start_date
        if end_date:
            kwargs["end_date"] = end_date
        result = obb.equity.price.historical(**kwargs)
        data = _to_serializable(result)
        return {"status": "ok", "data": data, "symbol": symbol, "provider": provider}
    except Exception as e:
        logger.error("equity historical failed for %s: %s", symbol, e)
        return {"status": "error", "error": str(e), "symbol": symbol, "provider": provider}


def fetch_index_quote(symbols: list[str], provider: str = "yfinance") -> dict:
    """Fetch latest index quotes (VIX, etc.)."""
    from openbb import obb
    try:
        result = obb.index.price.historical(
            symbol=",".join(symbols), provider=provider, interval="1d"
        )
        data = _to_serializable(result)
        return {"status": "ok", "data": data, "provider": provider}
    except Exception as e:
        logger.error("index quote failed: %s", e)
        return {"status": "error", "error": str(e), "provider": provider}


def fetch_economic_calendar(provider: str = "yfinance") -> dict:
    """Fetch upcoming economic events."""
    from openbb import obb
    try:
        # Try fmp first (richer), fall back
        try:
            result = obb.economy.calendar(provider="fmp")
        except Exception:
            result = obb.economy.calendar(provider=provider)
        data = _to_serializable(result)
        return {"status": "ok", "data": data}
    except Exception as e:
        logger.error("economic calendar failed: %s", e)
        return {"status": "error", "error": str(e)}


def fetch_news(search_term: str = "nasdaq", provider: str = "yfinance") -> dict:
    """Fetch market news."""
    from openbb import obb
    try:
        # Try tiingo or benzinga first, fall back to yfinance
        for prov in ["tiingo", "benzinga", provider]:
            try:
                result = obb.news.world(query=search_term, provider=prov, limit=20)
                data = _to_serializable(result)
                return {"status": "ok", "data": data, "provider": prov, "query": search_term}
            except Exception:
                continue
        return {"status": "error", "error": "all news providers failed", "query": search_term}
    except Exception as e:
        logger.error("news fetch failed: %s", e)
        return {"status": "error", "error": str(e), "query": search_term}


def fetch_market_snapshot(provider: str = "yfinance") -> dict:
    """Pull a comprehensive market snapshot suitable for quant lane consumption.

    Returns a structured dict with:
    - quotes: latest prices for NQ, VIX, SPY, QQQ
    - news: recent market news
    - timestamp: when this snapshot was taken
    """
    now = datetime.now(timezone.utc).isoformat()

    # Pull quotes for key symbols
    quotes = fetch_equity_quote(["NQ=F", "SPY", "QQQ"], provider=provider)

    # Pull VIX separately (it's an index)
    vix = fetch_index_quote(["^VIX"], provider=provider)

    # Pull news
    news = fetch_news("nasdaq", provider=provider)

    snapshot = {
        "snapshot_type": "market_context",
        "captured_at": now,
        "provider": provider,
        "quotes": quotes,
        "vix": vix,
        "news": news,
    }

    return snapshot


def build_environment_record(snapshot: dict) -> dict:
    """Transform a raw market snapshot into a DuckDB-ready environment record."""
    import uuid
    now = datetime.now(timezone.utc)

    # Extract NQ close from quotes
    nq_close = None
    vix_level = None

    if snapshot.get("quotes", {}).get("status") == "ok":
        for item in snapshot["quotes"].get("data", []):
            if isinstance(item, dict):
                sym = item.get("symbol", "")
                if "NQ" in sym:
                    nq_close = item.get("regular_market_previous_close") or item.get("close") or item.get("last_price")

    if snapshot.get("vix", {}).get("status") == "ok":
        vix_data = snapshot["vix"].get("data", [])
        if isinstance(vix_data, list) and vix_data:
            last_vix = vix_data[-1] if isinstance(vix_data[-1], dict) else {}
            vix_level = last_vix.get("close") or last_vix.get("last_price")

    # Determine regime from VIX
    regime = "normal"
    if vix_level is not None:
        if vix_level < 15:
            regime = "low_vol"
        elif vix_level > 30:
            regime = "crisis"
        elif vix_level > 25:
            regime = "high_vol"

    return {
        "snapshot_id": f"env-{uuid.uuid4().hex[:12]}",
        "captured_at": now.isoformat(),
        "symbol": "NQ",
        "last_close": nq_close,
        "vix_level": vix_level,
        "trend_5d": None,  # computed from DuckDB after load
        "range_5d_pct": None,
        "regime": regime,
        "macro_summary": f"VIX={vix_level}, NQ_close={nq_close}",
        "data_source": f"openbb/{snapshot.get('provider', 'unknown')}",
        "freshness_hours": 0.0,
        "raw_json": json.dumps(snapshot, default=str),
    }
