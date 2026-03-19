#!/usr/bin/env python3
"""Options-Aware Quant Layer — volatility surface and hedging signals.

Fetches options-derived data and produces signals for:
  - Implied volatility percentile ranking
  - Put/call ratio (sentiment indicator)
  - VIX term structure (contango/backwardation)
  - Max pain levels
  - Hedging recommendations

Data sources:
  - yfinance: VIX, SPY options (free, no API key)
  - CBOE: VIX futures term structure (via yfinance)

Usage:
    from openbb.options_adapter import fetch_options_context, generate_hedging_signal
    ctx = fetch_options_context()
    signal = generate_hedging_signal(ctx, portfolio_exposure=50000)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


QUANT_INFRA = Path(__file__).resolve().parent.parent
RESEARCH_DIR = QUANT_INFRA / "research" / "options"


@dataclass
class OptionsContext:
    """Aggregated options-derived market context."""
    fetched_at: str = ""
    # VIX
    vix_current: float = 0.0
    vix_5d_avg: float = 0.0
    vix_20d_avg: float = 0.0
    vix_percentile_20d: float = 50.0  # 0-100: where current VIX sits vs last 20 days
    vix_percentile_60d: float = 50.0  # 0-100: where current VIX sits vs last 60 days
    vix_regime: str = "normal"         # low_vol, normal, elevated, extreme
    # Term structure
    vix_term_structure: str = "unknown"  # contango, backwardation, flat
    vix_9d: float = 0.0                 # VIX9D (short-term)
    vix_3m: float = 0.0                 # VIX3M (medium-term)
    # Put/Call
    spy_put_call_ratio: float = 0.0
    spy_put_call_signal: str = "neutral"  # bearish, neutral, bullish (contrarian)
    # IV
    nq_iv_estimate: float = 0.0           # estimated NQ implied vol from VIX relationship
    iv_rank_20d: float = 50.0             # IV rank 0-100
    # Max pain (SPY as proxy)
    spy_max_pain: float = 0.0
    spy_max_pain_distance_pct: float = 0.0
    # Data quality
    data_source: str = "yfinance"
    stale: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HedgingSignal:
    """Hedging recommendation based on options context."""
    recommendation: str = "none"  # none, consider_puts, consider_collars, reduce_exposure
    urgency: str = "low"          # low, medium, high
    reasoning: str = ""
    suggested_actions: list[str] = field(default_factory=list)
    portfolio_exposure_usd: float = 0.0
    options_context_summary: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def fetch_options_context() -> OptionsContext:
    """Fetch options-derived market context from yfinance.

    Returns OptionsContext with VIX data, term structure, put/call ratio.
    Gracefully handles missing data.
    """
    ctx = OptionsContext(fetched_at=datetime.now(timezone.utc).isoformat())

    # 1. VIX current and historical
    try:
        import yfinance as yf
        vix = yf.download("^VIX", period="3mo", interval="1d", progress=False)
        if not vix.empty:
            if vix.columns.nlevels > 1:
                vix.columns = vix.columns.droplevel(1)
            closes = vix["Close" if "Close" in vix.columns else "close"].dropna().tolist()
            if closes:
                ctx.vix_current = round(float(closes[-1]), 2)
                if len(closes) >= 5:
                    ctx.vix_5d_avg = round(sum(closes[-5:]) / 5, 2)
                if len(closes) >= 20:
                    ctx.vix_20d_avg = round(sum(closes[-20:]) / 20, 2)
                    sorted_20 = sorted(closes[-20:])
                    rank = sorted_20.index(min(sorted_20, key=lambda x: abs(x - closes[-1])))
                    ctx.vix_percentile_20d = round(rank / len(sorted_20) * 100, 1)
                if len(closes) >= 60:
                    sorted_60 = sorted(closes[-60:])
                    rank = sorted_60.index(min(sorted_60, key=lambda x: abs(x - closes[-1])))
                    ctx.vix_percentile_60d = round(rank / len(sorted_60) * 100, 1)

                # Classify regime
                if ctx.vix_current < 15:
                    ctx.vix_regime = "low_vol"
                elif ctx.vix_current < 25:
                    ctx.vix_regime = "normal"
                elif ctx.vix_current < 35:
                    ctx.vix_regime = "elevated"
                else:
                    ctx.vix_regime = "extreme"
    except Exception as exc:
        print(f"[options] VIX fetch error: {exc}")

    # 2. VIX term structure (VIX9D vs VIX vs VIX3M)
    try:
        import yfinance as yf
        for sym, attr in [("^VIX9D", "vix_9d"), ("^VIX3M", "vix_3m")]:
            try:
                data = yf.download(sym, period="5d", interval="1d", progress=False)
                if not data.empty:
                    if data.columns.nlevels > 1:
                        data.columns = data.columns.droplevel(1)
                    col = "Close" if "Close" in data.columns else "close"
                    val = float(data[col].dropna().iloc[-1])
                    setattr(ctx, attr, round(val, 2))
            except Exception:
                pass

        # Determine term structure
        if ctx.vix_9d > 0 and ctx.vix_3m > 0:
            if ctx.vix_9d > ctx.vix_current > ctx.vix_3m:
                ctx.vix_term_structure = "backwardation"
            elif ctx.vix_9d < ctx.vix_current < ctx.vix_3m:
                ctx.vix_term_structure = "contango"
            elif ctx.vix_9d > ctx.vix_3m:
                ctx.vix_term_structure = "backwardation"
            else:
                ctx.vix_term_structure = "contango"
        elif ctx.vix_current > 0 and ctx.vix_3m > 0:
            ctx.vix_term_structure = "backwardation" if ctx.vix_current > ctx.vix_3m else "contango"
    except Exception:
        pass

    # 3. SPY put/call ratio estimate (from option volume)
    try:
        import yfinance as yf
        spy = yf.Ticker("SPY")
        expirations = spy.options
        if expirations:
            # Use nearest expiration
            nearest = expirations[0]
            chain = spy.option_chain(nearest)
            put_vol = chain.puts["volume"].sum() if "volume" in chain.puts.columns else 0
            call_vol = chain.calls["volume"].sum() if "volume" in chain.calls.columns else 0
            if call_vol > 0:
                ctx.spy_put_call_ratio = round(float(put_vol / call_vol), 2)
                # Contrarian: high P/C = bearish sentiment = bullish contrarian signal
                if ctx.spy_put_call_ratio > 1.2:
                    ctx.spy_put_call_signal = "bullish"   # contrarian
                elif ctx.spy_put_call_ratio < 0.7:
                    ctx.spy_put_call_signal = "bearish"   # contrarian
                else:
                    ctx.spy_put_call_signal = "neutral"

            # Estimate max pain from nearest expiration
            ctx.spy_max_pain = _estimate_max_pain(chain)
            spy_price = float(spy.fast_info.get("lastPrice", 0) or 0)
            if spy_price > 0 and ctx.spy_max_pain > 0:
                ctx.spy_max_pain_distance_pct = round(
                    (spy_price - ctx.spy_max_pain) / spy_price * 100, 2
                )
    except Exception as exc:
        print(f"[options] SPY options fetch error: {exc}")

    # 4. NQ IV estimate (VIX * 1.3 as rough NQ/SPX beta adjustment)
    if ctx.vix_current > 0:
        ctx.nq_iv_estimate = round(ctx.vix_current * 1.3, 2)
        if ctx.vix_20d_avg > 0:
            ctx.iv_rank_20d = ctx.vix_percentile_20d  # proxy

    # Write research artifact
    _write_options_artifact(ctx)

    return ctx


def _estimate_max_pain(chain) -> float:
    """Estimate max pain strike from options chain."""
    try:
        calls = chain.calls
        puts = chain.puts

        strikes = sorted(set(calls["strike"].tolist()) & set(puts["strike"].tolist()))
        if not strikes:
            return 0.0

        min_pain = float("inf")
        max_pain_strike = 0.0

        for strike in strikes:
            # Total pain = sum of ITM call value + sum of ITM put value
            call_pain = sum(
                max(0, strike - s) * oi
                for s, oi in zip(calls["strike"], calls.get("openInterest", calls.get("volume", [0] * len(calls))))
            )
            put_pain = sum(
                max(0, s - strike) * oi
                for s, oi in zip(puts["strike"], puts.get("openInterest", puts.get("volume", [0] * len(puts))))
            )
            total = call_pain + put_pain
            if total < min_pain:
                min_pain = total
                max_pain_strike = strike

        return float(max_pain_strike)
    except Exception:
        return 0.0


def generate_hedging_signal(
    ctx: OptionsContext,
    portfolio_exposure_usd: float = 0.0,
    open_position_count: int = 0,
) -> HedgingSignal:
    """Generate hedging recommendation from options context.

    Logic:
    - VIX extreme + backwardation = consider reducing exposure
    - VIX elevated + high P/C ratio = consider protective puts
    - VIX low + contango = conditions favorable, no hedge needed
    - IV rank > 80 = options expensive, prefer collars over outright puts
    """
    signal = HedgingSignal(
        portfolio_exposure_usd=portfolio_exposure_usd,
        options_context_summary=(
            f"VIX={ctx.vix_current} ({ctx.vix_regime}), "
            f"term={ctx.vix_term_structure}, "
            f"P/C={ctx.spy_put_call_ratio} ({ctx.spy_put_call_signal}), "
            f"IV rank={ctx.iv_rank_20d:.0f}%"
        ),
    )

    if ctx.vix_current == 0:
        signal.recommendation = "none"
        signal.reasoning = "No VIX data available"
        return signal

    # Extreme volatility + backwardation = reduce exposure
    if ctx.vix_regime == "extreme" and ctx.vix_term_structure == "backwardation":
        signal.recommendation = "reduce_exposure"
        signal.urgency = "high"
        signal.reasoning = (
            f"VIX at {ctx.vix_current} (extreme) in backwardation — "
            f"near-term vol exceeds longer-term expectations. "
            f"Market pricing imminent risk event."
        )
        signal.suggested_actions = [
            "Reduce position sizes by 50%",
            "Tighten stops on all open positions",
            "Pause new entries until VIX normalizes below 30",
        ]
        return signal

    # Elevated vol + bearish sentiment = protective puts
    if ctx.vix_regime == "elevated":
        if ctx.iv_rank_20d < 70:
            signal.recommendation = "consider_puts"
            signal.urgency = "medium"
            signal.reasoning = (
                f"VIX at {ctx.vix_current} (elevated) but IV rank {ctx.iv_rank_20d:.0f}% "
                f"is below 70 — puts reasonably priced for protection."
            )
            signal.suggested_actions = [
                "Consider 5-delta protective puts (2-3 weeks out)",
                "Size hedge to cover 50% of portfolio notional",
                "Tighten stops on larger positions",
            ]
        else:
            signal.recommendation = "consider_collars"
            signal.urgency = "medium"
            signal.reasoning = (
                f"VIX at {ctx.vix_current} (elevated) with IV rank {ctx.iv_rank_20d:.0f}% "
                f"— puts expensive. Collar (sell call + buy put) reduces net cost."
            )
            signal.suggested_actions = [
                "Consider zero-cost collar (sell OTM call, buy OTM put)",
                "Reduce position sizes for new entries",
            ]
        return signal

    # Low vol + contango = no hedge needed
    if ctx.vix_regime == "low_vol" and ctx.vix_term_structure == "contango":
        signal.recommendation = "none"
        signal.urgency = "low"
        signal.reasoning = (
            f"VIX at {ctx.vix_current} (low vol) in contango — "
            f"favorable conditions, standard risk management sufficient."
        )
        return signal

    # Normal conditions
    signal.recommendation = "none"
    signal.urgency = "low"
    signal.reasoning = (
        f"VIX at {ctx.vix_current} ({ctx.vix_regime}), "
        f"term structure {ctx.vix_term_structure} — "
        f"no hedging action needed."
    )
    return signal


def _write_options_artifact(ctx: OptionsContext) -> None:
    """Write options context to research directory."""
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = RESEARCH_DIR / "latest.json"
    json_path.write_text(json.dumps(ctx.to_dict(), indent=2) + "\n")

    # Markdown
    md = f"""# Options Context — {ctx.fetched_at[:19]}

## VIX
- **Current**: {ctx.vix_current}
- **5D avg**: {ctx.vix_5d_avg} | **20D avg**: {ctx.vix_20d_avg}
- **20D percentile**: {ctx.vix_percentile_20d:.0f}% | **60D percentile**: {ctx.vix_percentile_60d:.0f}%
- **Regime**: {ctx.vix_regime}

## Term Structure
- **Structure**: {ctx.vix_term_structure}
- **VIX9D**: {ctx.vix_9d} | **VIX**: {ctx.vix_current} | **VIX3M**: {ctx.vix_3m}

## Put/Call Ratio (SPY)
- **Ratio**: {ctx.spy_put_call_ratio}
- **Signal**: {ctx.spy_put_call_signal} (contrarian interpretation)

## Implied Volatility
- **NQ IV estimate**: {ctx.nq_iv_estimate}%
- **IV rank (20D)**: {ctx.iv_rank_20d:.0f}%

## Max Pain (SPY)
- **Level**: {ctx.spy_max_pain}
- **Distance**: {ctx.spy_max_pain_distance_pct:+.2f}%
"""
    (RESEARCH_DIR / "latest.md").write_text(md)


def write_strategy_config_default() -> Path:
    """Write default strategy configuration file."""
    config = {
        "default_family": "ema_mean_reversion",
        "regime_assignments": {
            "low_vol": ["ema_mean_reversion", "vwap_reversion"],
            "normal": ["ema_mean_reversion", "momentum", "trend_following"],
            "trending": ["trend_following", "breakout"],
            "extended": ["ema_mean_reversion", "vwap_reversion"],
        },
        "strategy_overrides": {},
        "family_parameters": {
            "ema_mean_reversion": {"fast": 8, "slow": 21, "entry_atr_mult": 1.8},
            "momentum": {"rsi_period": 14, "oversold": 30, "overbought": 70},
            "trend_following": {"macd_fast": 12, "macd_slow": 26, "macd_signal": 9},
            "breakout": {"range_bars": 6},
            "vwap_reversion": {"deviation_threshold": 1.5},
        },
    }
    config_dir = Path(__file__).resolve().parent.parent.parent / "quant" / "shared" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "strategy_config.json"
    path.write_text(json.dumps(config, indent=2) + "\n")
    return path
