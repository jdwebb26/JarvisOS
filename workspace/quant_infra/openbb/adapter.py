"""OpenBB adapter — structured market data fetching with graceful fallback.

Uses OpenBB Platform SDK to pull market context, news, economic data.
Requires Python 3.12 venv with OpenBB installed.

Each fetch section fails independently. When OpenBB endpoints fail,
direct yfinance fallback is used for critical market data (NQ, VIX, SPY, QQQ).
Every returned section carries a 'source' field indicating provenance.

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


# ---------------------------------------------------------------------------
# Individual OpenBB fetch functions (unchanged API, improved error handling)
# ---------------------------------------------------------------------------

def fetch_equity_quote(symbols: list[str], provider: str = "yfinance") -> dict:
    """Fetch latest equity/futures quotes via OpenBB."""
    from openbb import obb
    try:
        result = obb.equity.price.quote(symbol=",".join(symbols), provider=provider)
        data = _to_serializable(result)
        return {"status": "ok", "data": data, "provider": provider, "source": f"openbb/{provider}"}
    except Exception as e:
        logger.error("equity quote failed: %s", e)
        return {"status": "error", "error": str(e), "provider": provider, "source": f"openbb/{provider}"}


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
        return {"status": "ok", "data": data, "symbol": symbol, "provider": provider, "source": f"openbb/{provider}"}
    except Exception as e:
        logger.error("equity historical failed for %s: %s", symbol, e)
        return {"status": "error", "error": str(e), "symbol": symbol, "provider": provider, "source": f"openbb/{provider}"}


def fetch_index_quote(symbols: list[str], provider: str = "yfinance") -> dict:
    """Fetch latest index quotes (VIX, etc.)."""
    from openbb import obb
    try:
        result = obb.index.price.historical(
            symbol=",".join(symbols), provider=provider, interval="1d"
        )
        data = _to_serializable(result)
        return {"status": "ok", "data": data, "provider": provider, "source": f"openbb/{provider}"}
    except Exception as e:
        logger.error("index quote failed: %s", e)
        return {"status": "error", "error": str(e), "provider": provider, "source": f"openbb/{provider}"}


def fetch_economic_calendar(provider: str = "yfinance") -> dict:
    """Fetch upcoming economic events."""
    from openbb import obb
    try:
        try:
            result = obb.economy.calendar(provider="fmp")
            data = _to_serializable(result)
            return {"status": "ok", "data": data, "source": "openbb/fmp"}
        except Exception:
            result = obb.economy.calendar(provider=provider)
            data = _to_serializable(result)
            return {"status": "ok", "data": data, "source": f"openbb/{provider}"}
    except Exception as e:
        logger.error("economic calendar failed: %s", e)
        return {"status": "error", "error": str(e), "source": "openbb"}


def fetch_news(search_term: str = "nasdaq", provider: str = "yfinance") -> dict:
    """Fetch market news via OpenBB."""
    from openbb import obb
    try:
        for prov in ["tiingo", "benzinga", provider]:
            try:
                result = obb.news.world(query=search_term, provider=prov, limit=20)
                data = _to_serializable(result)
                return {"status": "ok", "data": data, "provider": prov, "query": search_term, "source": f"openbb/{prov}"}
            except Exception:
                continue
        return {"status": "error", "error": "all news providers failed", "query": search_term, "source": "openbb"}
    except Exception as e:
        logger.error("news fetch failed: %s", e)
        return {"status": "error", "error": str(e), "query": search_term, "source": "openbb"}


# ---------------------------------------------------------------------------
# Direct yfinance fallback — bypass OpenBB entirely when it fails
# ---------------------------------------------------------------------------

def _yfinance_fallback_quotes(symbols: list[str]) -> dict:
    """Fetch quotes directly from yfinance, bypassing OpenBB."""
    try:
        import yfinance as yf
        results = []
        for sym in symbols:
            try:
                ticker = yf.Ticker(sym)
                info = ticker.fast_info
                results.append({
                    "symbol": sym,
                    "close": getattr(info, "last_price", None) or getattr(info, "previous_close", None),
                    "last_price": getattr(info, "last_price", None),
                    "previous_close": getattr(info, "previous_close", None),
                    "regular_market_previous_close": getattr(info, "previous_close", None),
                    "open": getattr(info, "open", None),
                    "day_high": getattr(info, "day_high", None),
                    "day_low": getattr(info, "day_low", None),
                })
            except Exception as e:
                logger.warning("yfinance fallback failed for %s: %s", sym, e)
                continue
        if results:
            return {"status": "ok", "data": results, "provider": "yfinance-direct", "source": "yfinance-direct"}
        return {"status": "error", "error": "yfinance returned no data", "source": "yfinance-direct"}
    except ImportError:
        return {"status": "error", "error": "yfinance not installed", "source": "yfinance-direct"}
    except Exception as e:
        return {"status": "error", "error": str(e), "source": "yfinance-direct"}


def _yfinance_fallback_vix() -> dict:
    """Fetch VIX directly from yfinance, bypassing OpenBB."""
    try:
        import yfinance as yf
        ticker = yf.Ticker("^VIX")
        info = ticker.fast_info
        close = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
        if close is not None:
            return {
                "status": "ok",
                "data": [{"symbol": "^VIX", "close": close}],
                "provider": "yfinance-direct",
                "source": "yfinance-direct",
            }
        return {"status": "error", "error": "VIX data empty", "source": "yfinance-direct"}
    except Exception as e:
        return {"status": "error", "error": str(e), "source": "yfinance-direct"}


def _yfinance_fallback_news() -> dict:
    """Fetch news directly from yfinance, bypassing OpenBB.

    Handles both the old flat format and the newer nested content format
    returned by recent yfinance versions.
    """
    try:
        import yfinance as yf
        items = []
        for sym in ["NQ=F", "QQQ", "SPY"]:
            try:
                ticker = yf.Ticker(sym)
                news = ticker.news
                if isinstance(news, list):
                    for n in news[:10]:
                        if not isinstance(n, dict):
                            continue
                        # New nested format: {content: {title, provider: {displayName}, ...}}
                        content = n.get("content", {})
                        if isinstance(content, dict) and content.get("title"):
                            provider = content.get("provider", {})
                            pub_name = provider.get("displayName", "yfinance") if isinstance(provider, dict) else "yfinance"
                            canon = content.get("canonicalUrl", {})
                            url = canon.get("url", "") if isinstance(canon, dict) else ""
                            items.append({
                                "title": content["title"],
                                "source": pub_name,
                                "url": url,
                                "date": content.get("pubDate") or content.get("displayTime") or "",
                                "symbols": sym,
                                "summary": content.get("summary") or content.get("description") or "",
                            })
                        # Old flat format fallback
                        elif n.get("title") or n.get("headline"):
                            items.append({
                                "title": n.get("title") or n.get("headline", ""),
                                "source": n.get("publisher") or n.get("source", "yfinance"),
                                "url": n.get("link") or n.get("url", ""),
                                "date": n.get("providerPublishTime") or n.get("published_at", ""),
                                "symbols": sym,
                                "summary": "",
                            })
            except Exception:
                continue
        # Sort by date descending (most recent first), then deduplicate by title
        items.sort(key=lambda x: x.get("date") or "", reverse=True)
        seen = set()
        deduped = []
        for item in items:
            key = item.get("title", "")
            if key and key not in seen:
                seen.add(key)
                deduped.append(item)
        if deduped:
            return {"status": "ok", "data": deduped[:20], "provider": "yfinance-direct", "source": "yfinance-direct"}
        return {"status": "error", "error": "no news from yfinance", "source": "yfinance-direct"}
    except ImportError:
        return {"status": "error", "error": "yfinance not installed", "source": "yfinance-direct"}
    except Exception as e:
        return {"status": "error", "error": str(e), "source": "yfinance-direct"}


# ---------------------------------------------------------------------------
# Main snapshot builder — graceful per-section degradation
# ---------------------------------------------------------------------------

def fetch_market_snapshot(provider: str = "yfinance") -> dict:
    """Pull a comprehensive market snapshot with per-section fault isolation.

    Each section (quotes, vix, news, calendar) is fetched independently.
    If the OpenBB path fails, direct yfinance fallback is attempted for
    critical sections. The returned snapshot carries per-section 'source'
    provenance so downstream consumers know exactly what produced each part.

    Returns a structured dict with:
    - quotes: latest prices for NQ, SPY, QQQ  (source-tagged)
    - vix: VIX level (source-tagged)
    - news: recent market news (source-tagged)
    - calendar: economic events (source-tagged, optional)
    - fetch_report: which sections succeeded/failed and their sources
    """
    now = datetime.now(timezone.utc).isoformat()
    fetch_report: dict[str, dict] = {}

    # --- Quotes (NQ, SPY, QQQ) ---
    quotes = fetch_equity_quote(["NQ=F", "SPY", "QQQ"], provider=provider)
    if quotes.get("status") != "ok":
        logger.warning("OpenBB equity quotes failed, trying yfinance direct fallback")
        quotes = _yfinance_fallback_quotes(["NQ=F", "SPY", "QQQ"])
    fetch_report["quotes"] = {"status": quotes.get("status"), "source": quotes.get("source", "unknown")}

    # --- VIX ---
    vix = fetch_index_quote(["^VIX"], provider=provider)
    if vix.get("status") != "ok":
        logger.warning("OpenBB VIX failed, trying yfinance direct fallback")
        vix = _yfinance_fallback_vix()
    fetch_report["vix"] = {"status": vix.get("status"), "source": vix.get("source", "unknown")}

    # --- News ---
    news = fetch_news("nasdaq", provider=provider)
    if news.get("status") != "ok":
        logger.warning("OpenBB news failed, trying yfinance direct fallback")
        news = _yfinance_fallback_news()
    fetch_report["news"] = {"status": news.get("status"), "source": news.get("source", "unknown")}

    # --- Economic calendar (optional, no fallback) ---
    calendar = fetch_economic_calendar(provider=provider)
    fetch_report["calendar"] = {"status": calendar.get("status"), "source": calendar.get("source", "unknown")}

    snapshot = {
        "snapshot_type": "market_context",
        "captured_at": now,
        "provider": provider,
        "quotes": quotes,
        "vix": vix,
        "news": news,
        "calendar": calendar,
        "fetch_report": fetch_report,
    }

    return snapshot


# ---------------------------------------------------------------------------
# Environment record builder
# ---------------------------------------------------------------------------

def build_environment_record(snapshot: dict) -> dict:
    """Transform a raw market snapshot into a DuckDB-ready environment record.

    Extracts NQ close and VIX from whatever source succeeded, and tracks
    the data_source provenance chain.
    """
    import uuid
    now = datetime.now(timezone.utc)

    nq_close = None
    spy_close = None
    qqq_close = None
    vix_level = None
    sources_used: list[str] = []

    def _round_price(val: Any) -> float | None:
        """Round a price to 2 decimal places, handling None/non-numeric."""
        if val is None:
            return None
        try:
            return round(float(val), 2)
        except (TypeError, ValueError):
            return None

    # Extract equity prices from quotes
    if snapshot.get("quotes", {}).get("status") == "ok":
        source = snapshot["quotes"].get("source", "unknown")
        for item in snapshot["quotes"].get("data", []):
            if isinstance(item, dict):
                sym = item.get("symbol", "")
                price = _round_price(
                    item.get("last_price")
                    or item.get("close")
                    or item.get("regular_market_previous_close")
                    or item.get("previous_close")
                )
                if "NQ" in sym:
                    nq_close = price
                elif sym == "SPY":
                    spy_close = price
                elif sym == "QQQ":
                    qqq_close = price
        if source not in sources_used:
            sources_used.append(source)

    # Extract VIX
    if snapshot.get("vix", {}).get("status") == "ok":
        source = snapshot["vix"].get("source", "unknown")
        vix_data = snapshot["vix"].get("data", [])
        if isinstance(vix_data, list) and vix_data:
            last_vix = vix_data[-1] if isinstance(vix_data[-1], dict) else {}
            vix_level = _round_price(last_vix.get("close") or last_vix.get("last_price"))
        if source not in sources_used:
            sources_used.append(source)

    # Determine regime from VIX
    regime = "unknown"
    if vix_level is not None:
        if vix_level < 15:
            regime = "low_vol"
        elif vix_level > 30:
            regime = "crisis"
        elif vix_level > 25:
            regime = "high_vol"
        else:
            regime = "normal"

    data_source = " + ".join(sources_used) if sources_used else "none"

    parts = []
    if nq_close is not None:
        parts.append(f"NQ={nq_close}")
    if vix_level is not None:
        parts.append(f"VIX={vix_level}")
    if spy_close is not None:
        parts.append(f"SPY={spy_close}")
    if qqq_close is not None:
        parts.append(f"QQQ={qqq_close}")
    parts.append(f"regime={regime}")
    macro_summary = ", ".join(parts) if parts else "no data available"

    return {
        "snapshot_id": f"env-{uuid.uuid4().hex[:12]}",
        "captured_at": now.isoformat(),
        "symbol": "NQ",
        "last_close": nq_close,
        "spy_close": spy_close,
        "qqq_close": qqq_close,
        "vix_level": vix_level,
        "trend_5d": None,  # computed from DuckDB after load
        "range_5d_pct": None,
        "regime": regime,
        "macro_summary": macro_summary,
        "data_source": data_source,
        "freshness_hours": 0.0,
        "raw_json": json.dumps(snapshot, default=str),
    }
