#!/usr/bin/env python3
"""Kitt Signal Registry — multi-strategy signal generation framework.

Provides a pluggable signal system with multiple strategy families:
  - ema_mean_reversion: Original 8/21 EMA mean-reversion (default)
  - momentum: RSI-based momentum entries
  - trend_following: MACD + EMA slope trend detection
  - breakout: Opening range breakout
  - vwap_reversion: VWAP deviation mean-reversion

Each signal generator follows the same interface:
    compute(bars) -> SignalResult

Strategy selection is driven by:
  1. strategy_config.json (explicit assignment)
  2. Regime-based selection (certain strategies suit certain regimes)
  3. Fallback to default (ema_mean_reversion)

Usage:
    from kitt.signals import get_signal, compute_signal_for_strategy
    signal = compute_signal_for_strategy("momentum", bars)
    # or
    signal = get_signal("ema_mean_reversion").compute(bars)
"""
from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SignalResult:
    """Standardized signal output from any strategy family."""
    family: str                   # strategy family name
    signal: str                   # "long", "short", or "none"
    entry: float | None = None    # suggested entry price
    stop: float | None = None     # suggested stop loss
    target: float | None = None   # suggested take profit
    confidence: float = 0.5       # 0-1 signal confidence
    reason: str = ""              # human-readable explanation
    # Technical context
    atr: float = 0.0
    deviation: float = 0.0
    current_price: float = 0.0
    regime: str = "normal"
    indicators: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "family": self.family,
            "signal": self.signal,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "confidence": self.confidence,
            "reason": self.reason,
            "atr": self.atr,
            "deviation": self.deviation,
            "current_price": self.current_price,
            "regime": self.regime,
            "indicators": self.indicators,
        }


# ---------------------------------------------------------------------------
# Helper computations
# ---------------------------------------------------------------------------

def _ema(values: list[float], period: int) -> float:
    """Compute exponential moving average."""
    if not values:
        return 0.0
    mult = 2.0 / (period + 1)
    result = values[0]
    for v in values[1:]:
        result = v * mult + result * (1 - mult)
    return result


def _sma(values: list[float], period: int) -> float:
    """Simple moving average of last `period` values."""
    if len(values) < period:
        return sum(values) / len(values) if values else 0.0
    return sum(values[-period:]) / period


def _atr(bars: list[dict], period: int = 14) -> float:
    """Average True Range."""
    if len(bars) < 2:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    return sum(trs[-period:]) / period


def _rsi(closes: list[float], period: int = 14) -> float:
    """Relative Strength Index."""
    if len(closes) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _macd(closes: list[float], fast: int = 12, slow: int = 26, signal_period: int = 9) -> dict:
    """MACD indicator."""
    if len(closes) < slow + signal_period:
        return {"macd": 0, "signal": 0, "histogram": 0}
    fast_ema = _ema(closes, fast)
    slow_ema = _ema(closes, slow)
    macd_line = fast_ema - slow_ema

    # Approximate signal line from recent MACD values
    macd_vals = []
    for i in range(slow + signal_period, len(closes) + 1):
        fe = _ema(closes[:i], fast)
        se = _ema(closes[:i], slow)
        macd_vals.append(fe - se)
    signal_line = _ema(macd_vals, signal_period) if macd_vals else 0
    histogram = macd_line - signal_line

    return {"macd": round(macd_line, 2), "signal": round(signal_line, 2),
            "histogram": round(histogram, 2)}


def _vwap(bars: list[dict]) -> float:
    """Volume-weighted average price from intraday bars."""
    total_vp = 0.0
    total_vol = 0
    for b in bars:
        typical = (b["high"] + b["low"] + b["close"]) / 3
        vol = b.get("volume", 1)
        total_vp += typical * vol
        total_vol += vol
    return round(total_vp / total_vol, 2) if total_vol > 0 else bars[-1]["close"]


def _classify_regime(atr_val: float, deviation: float, min_atr: float = 20.0) -> str:
    """Classify regime from ATR and deviation."""
    if atr_val < min_atr:
        return "low_vol"
    if abs(deviation) > atr_val * 2.5:
        return "trending"
    if abs(deviation) > atr_val * 1.8:
        return "extended"
    return "normal"


# ---------------------------------------------------------------------------
# Signal generators
# ---------------------------------------------------------------------------

class SignalGenerator(ABC):
    """Base class for all signal generators."""
    family: str = "base"

    @abstractmethod
    def compute(self, bars: list[dict]) -> SignalResult:
        ...


class EMAMeanReversion(SignalGenerator):
    """Original 8/21 EMA mean-reversion signal."""
    family = "ema_mean_reversion"

    def __init__(self, fast: int = 8, slow: int = 21, entry_atr_mult: float = 1.8,
                 stop_atr_mult: float = 2.5, tp_atr_mult: float = 1.5):
        self.fast = fast
        self.slow = slow
        self.entry_atr_mult = entry_atr_mult
        self.stop_atr_mult = stop_atr_mult
        self.tp_atr_mult = tp_atr_mult

    def compute(self, bars: list[dict]) -> SignalResult:
        if len(bars) < max(self.slow, 14) + 5:
            return SignalResult(family=self.family, signal="none",
                                reason=f"insufficient bars ({len(bars)})")

        closes = [b["close"] for b in bars]
        atr_val = _atr(bars)
        ema_f = _ema(closes, self.fast)
        ema_s = _ema(closes, self.slow)
        price = closes[-1]
        deviation = price - ema_s
        threshold = atr_val * self.entry_atr_mult
        regime = _classify_regime(atr_val, deviation)

        result = SignalResult(
            family=self.family, signal="none", current_price=price,
            atr=round(atr_val, 2), deviation=round(deviation, 2), regime=regime,
            indicators={"ema_fast": round(ema_f, 2), "ema_slow": round(ema_s, 2)},
        )

        if atr_val < 20.0:
            result.reason = f"ATR too low ({atr_val:.2f})"
            return result

        if deviation < -threshold:
            result.signal = "long"
            result.entry = price
            result.stop = round(price - atr_val * self.stop_atr_mult, 2)
            result.target = round(price + atr_val * self.tp_atr_mult, 2)
            result.confidence = min(0.7, 0.4 + abs(deviation) / (threshold * 3))
            result.reason = (f"Mean reversion long: price {price:.2f} is {abs(deviation):.2f} "
                             f"below EMA({self.slow}), ATR={atr_val:.2f}")
        elif deviation > threshold:
            result.signal = "short"
            result.entry = price
            result.stop = round(price + atr_val * self.stop_atr_mult, 2)
            result.target = round(price - atr_val * self.tp_atr_mult, 2)
            result.confidence = min(0.7, 0.4 + abs(deviation) / (threshold * 3))
            result.reason = (f"Mean reversion short: price {price:.2f} is {deviation:.2f} "
                             f"above EMA({self.slow}), ATR={atr_val:.2f}")
        else:
            result.reason = f"No signal: deviation {deviation:.2f} within +/-{threshold:.2f}"

        return result


class MomentumRSI(SignalGenerator):
    """RSI-based momentum signal with trend confirmation."""
    family = "momentum"

    def __init__(self, rsi_period: int = 14, oversold: float = 30.0,
                 overbought: float = 70.0, stop_atr_mult: float = 2.0,
                 tp_atr_mult: float = 2.5):
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.stop_atr_mult = stop_atr_mult
        self.tp_atr_mult = tp_atr_mult

    def compute(self, bars: list[dict]) -> SignalResult:
        if len(bars) < self.rsi_period + 5:
            return SignalResult(family=self.family, signal="none",
                                reason=f"insufficient bars ({len(bars)})")

        closes = [b["close"] for b in bars]
        price = closes[-1]
        atr_val = _atr(bars)
        rsi = _rsi(closes, self.rsi_period)
        ema_50 = _ema(closes, 50) if len(closes) >= 50 else _ema(closes, len(closes))
        trend = "bullish" if price > ema_50 else "bearish"
        deviation = price - ema_50
        regime = _classify_regime(atr_val, deviation)

        result = SignalResult(
            family=self.family, signal="none", current_price=price,
            atr=round(atr_val, 2), deviation=round(deviation, 2), regime=regime,
            indicators={"rsi": rsi, "ema_50": round(ema_50, 2), "trend": trend},
        )

        if atr_val < 20.0:
            result.reason = f"ATR too low ({atr_val:.2f})"
            return result

        # Long: RSI oversold + bullish trend (buy the dip in uptrend)
        if rsi <= self.oversold and trend == "bullish":
            result.signal = "long"
            result.entry = price
            result.stop = round(price - atr_val * self.stop_atr_mult, 2)
            result.target = round(price + atr_val * self.tp_atr_mult, 2)
            result.confidence = min(0.7, 0.3 + (self.oversold - rsi) / 30)
            result.reason = (f"Momentum long: RSI={rsi:.1f} (oversold) in {trend} trend, "
                             f"ATR={atr_val:.2f}")

        # Short: RSI overbought + bearish trend (sell the rip in downtrend)
        elif rsi >= self.overbought and trend == "bearish":
            result.signal = "short"
            result.entry = price
            result.stop = round(price + atr_val * self.stop_atr_mult, 2)
            result.target = round(price - atr_val * self.tp_atr_mult, 2)
            result.confidence = min(0.7, 0.3 + (rsi - self.overbought) / 30)
            result.reason = (f"Momentum short: RSI={rsi:.1f} (overbought) in {trend} trend, "
                             f"ATR={atr_val:.2f}")
        else:
            result.reason = f"No momentum signal: RSI={rsi:.1f}, trend={trend}"

        return result


class TrendFollowing(SignalGenerator):
    """MACD + EMA slope trend-following signal."""
    family = "trend_following"

    def __init__(self, macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9,
                 stop_atr_mult: float = 3.0, tp_atr_mult: float = 4.0):
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.stop_atr_mult = stop_atr_mult
        self.tp_atr_mult = tp_atr_mult

    def compute(self, bars: list[dict]) -> SignalResult:
        min_bars = self.macd_slow + self.macd_signal + 5
        if len(bars) < min_bars:
            return SignalResult(family=self.family, signal="none",
                                reason=f"insufficient bars ({len(bars)})")

        closes = [b["close"] for b in bars]
        price = closes[-1]
        atr_val = _atr(bars)
        macd_data = _macd(closes, self.macd_fast, self.macd_slow, self.macd_signal)
        ema_21 = _ema(closes, 21)
        ema_50 = _ema(closes, 50) if len(closes) >= 50 else _ema(closes, len(closes))
        ema_slope = ema_21 - _ema(closes[:-3], 21) if len(closes) > 24 else 0
        deviation = price - ema_50
        regime = _classify_regime(atr_val, deviation)

        result = SignalResult(
            family=self.family, signal="none", current_price=price,
            atr=round(atr_val, 2), deviation=round(deviation, 2), regime=regime,
            indicators={
                "macd": macd_data["macd"], "macd_signal": macd_data["signal"],
                "macd_histogram": macd_data["histogram"], "ema_slope": round(ema_slope, 2),
            },
        )

        if atr_val < 20.0:
            result.reason = f"ATR too low ({atr_val:.2f})"
            return result

        # Long: MACD above signal + positive histogram + rising EMA
        if (macd_data["histogram"] > 0 and macd_data["macd"] > macd_data["signal"]
                and ema_slope > 0):
            result.signal = "long"
            result.entry = price
            result.stop = round(price - atr_val * self.stop_atr_mult, 2)
            result.target = round(price + atr_val * self.tp_atr_mult, 2)
            result.confidence = min(0.65, 0.3 + abs(macd_data["histogram"]) / 20)
            result.reason = (f"Trend long: MACD={macd_data['macd']:.2f} > signal, "
                             f"histogram={macd_data['histogram']:.2f}, EMA slope positive")

        # Short: MACD below signal + negative histogram + falling EMA
        elif (macd_data["histogram"] < 0 and macd_data["macd"] < macd_data["signal"]
              and ema_slope < 0):
            result.signal = "short"
            result.entry = price
            result.stop = round(price + atr_val * self.stop_atr_mult, 2)
            result.target = round(price - atr_val * self.tp_atr_mult, 2)
            result.confidence = min(0.65, 0.3 + abs(macd_data["histogram"]) / 20)
            result.reason = (f"Trend short: MACD={macd_data['macd']:.2f} < signal, "
                             f"histogram={macd_data['histogram']:.2f}, EMA slope negative")
        else:
            result.reason = (f"No trend signal: MACD={macd_data['macd']:.2f}, "
                             f"hist={macd_data['histogram']:.2f}, slope={ema_slope:.2f}")

        return result


class BreakoutORB(SignalGenerator):
    """Opening Range Breakout signal.

    Identifies range from first N bars of session, then signals on breakout.
    """
    family = "breakout"

    def __init__(self, range_bars: int = 6, stop_atr_mult: float = 1.5,
                 tp_atr_mult: float = 2.0):
        self.range_bars = range_bars
        self.stop_atr_mult = stop_atr_mult
        self.tp_atr_mult = tp_atr_mult

    def compute(self, bars: list[dict]) -> SignalResult:
        if len(bars) < self.range_bars + 5:
            return SignalResult(family=self.family, signal="none",
                                reason=f"insufficient bars ({len(bars)})")

        closes = [b["close"] for b in bars]
        price = closes[-1]
        atr_val = _atr(bars)

        # Use last 20 bars to define recent range, first N as "opening range"
        recent = bars[-20:] if len(bars) >= 20 else bars
        range_bars = recent[:self.range_bars]
        range_high = max(b["high"] for b in range_bars)
        range_low = min(b["low"] for b in range_bars)
        range_width = range_high - range_low
        deviation = price - (range_high + range_low) / 2
        regime = _classify_regime(atr_val, deviation)

        result = SignalResult(
            family=self.family, signal="none", current_price=price,
            atr=round(atr_val, 2), deviation=round(deviation, 2), regime=regime,
            indicators={"range_high": range_high, "range_low": range_low,
                        "range_width": round(range_width, 2)},
        )

        if atr_val < 20.0 or range_width < atr_val * 0.3:
            result.reason = f"Range too narrow ({range_width:.2f} vs ATR {atr_val:.2f})"
            return result

        # Long breakout: price above range high
        if price > range_high and price < range_high + atr_val:
            result.signal = "long"
            result.entry = price
            result.stop = round(range_low - atr_val * 0.5, 2)
            result.target = round(price + range_width * self.tp_atr_mult, 2)
            result.confidence = min(0.6, 0.3 + (price - range_high) / atr_val)
            result.reason = (f"Breakout long: price {price:.2f} above range "
                             f"[{range_low:.2f}, {range_high:.2f}]")

        # Short breakout: price below range low
        elif price < range_low and price > range_low - atr_val:
            result.signal = "short"
            result.entry = price
            result.stop = round(range_high + atr_val * 0.5, 2)
            result.target = round(price - range_width * self.tp_atr_mult, 2)
            result.confidence = min(0.6, 0.3 + (range_low - price) / atr_val)
            result.reason = (f"Breakout short: price {price:.2f} below range "
                             f"[{range_low:.2f}, {range_high:.2f}]")
        else:
            result.reason = (f"No breakout: price {price:.2f} within range "
                             f"[{range_low:.2f}, {range_high:.2f}]")

        return result


class VWAPReversion(SignalGenerator):
    """VWAP deviation mean-reversion signal."""
    family = "vwap_reversion"

    def __init__(self, deviation_threshold: float = 1.5, stop_atr_mult: float = 2.0,
                 tp_atr_mult: float = 1.0):
        self.deviation_threshold = deviation_threshold
        self.stop_atr_mult = stop_atr_mult
        self.tp_atr_mult = tp_atr_mult

    def compute(self, bars: list[dict]) -> SignalResult:
        if len(bars) < 20:
            return SignalResult(family=self.family, signal="none",
                                reason=f"insufficient bars ({len(bars)})")

        closes = [b["close"] for b in bars]
        price = closes[-1]
        atr_val = _atr(bars)
        vwap = _vwap(bars)
        vwap_dev = price - vwap
        dev_ratio = vwap_dev / atr_val if atr_val > 0 else 0
        regime = _classify_regime(atr_val, vwap_dev)

        result = SignalResult(
            family=self.family, signal="none", current_price=price,
            atr=round(atr_val, 2), deviation=round(vwap_dev, 2), regime=regime,
            indicators={"vwap": vwap, "vwap_deviation": round(vwap_dev, 2),
                        "deviation_ratio": round(dev_ratio, 2)},
        )

        if atr_val < 20.0:
            result.reason = f"ATR too low ({atr_val:.2f})"
            return result

        # Long: price significantly below VWAP (mean revert up)
        if dev_ratio < -self.deviation_threshold:
            result.signal = "long"
            result.entry = price
            result.stop = round(price - atr_val * self.stop_atr_mult, 2)
            result.target = round(vwap + atr_val * self.tp_atr_mult * 0.5, 2)
            result.confidence = min(0.65, 0.3 + abs(dev_ratio) / 5)
            result.reason = (f"VWAP reversion long: price {price:.2f} is {abs(vwap_dev):.2f} "
                             f"below VWAP {vwap:.2f} ({dev_ratio:.1f}x ATR)")

        # Short: price significantly above VWAP (mean revert down)
        elif dev_ratio > self.deviation_threshold:
            result.signal = "short"
            result.entry = price
            result.stop = round(price + atr_val * self.stop_atr_mult, 2)
            result.target = round(vwap - atr_val * self.tp_atr_mult * 0.5, 2)
            result.confidence = min(0.65, 0.3 + abs(dev_ratio) / 5)
            result.reason = (f"VWAP reversion short: price {price:.2f} is {vwap_dev:.2f} "
                             f"above VWAP {vwap:.2f} ({dev_ratio:.1f}x ATR)")
        else:
            result.reason = (f"No VWAP signal: deviation {vwap_dev:.2f} "
                             f"({dev_ratio:.1f}x ATR, threshold +/-{self.deviation_threshold})")

        return result


# ---------------------------------------------------------------------------
# Signal Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[SignalGenerator]] = {
    "ema_mean_reversion": EMAMeanReversion,
    "momentum": MomentumRSI,
    "trend_following": TrendFollowing,
    "breakout": BreakoutORB,
    "vwap_reversion": VWAPReversion,
}


def get_signal(family: str, **kwargs) -> SignalGenerator:
    """Get a signal generator by family name."""
    cls = _REGISTRY.get(family)
    if cls is None:
        raise ValueError(f"Unknown signal family: {family!r}. Available: {list(_REGISTRY.keys())}")
    return cls(**kwargs)


def list_families() -> list[str]:
    """List all registered signal families."""
    return list(_REGISTRY.keys())


def compute_signal_for_strategy(family: str, bars: list[dict], **kwargs) -> SignalResult:
    """Convenience: create generator and compute signal in one call."""
    return get_signal(family, **kwargs).compute(bars)


def compute_all_signals(bars: list[dict]) -> list[SignalResult]:
    """Compute signals from all registered families. Useful for signal comparison."""
    results = []
    for family in _REGISTRY:
        try:
            result = compute_signal_for_strategy(family, bars)
            results.append(result)
        except Exception:
            pass
    return results


def select_best_signal(
    bars: list[dict],
    allowed_families: list[str] | None = None,
    regime_filter: str | None = None,
) -> SignalResult | None:
    """Select the highest-confidence signal from allowed families.

    Args:
        bars: Recent price bars.
        allowed_families: List of family names to consider (None = all).
        regime_filter: Only consider signals matching this regime.

    Returns:
        The SignalResult with highest confidence that has a non-"none" signal,
        or None if no signal is generated.
    """
    families = allowed_families or list(_REGISTRY.keys())
    candidates = []

    for family in families:
        if family not in _REGISTRY:
            continue
        try:
            result = compute_signal_for_strategy(family, bars)
            if result.signal == "none":
                continue
            if regime_filter and result.regime != regime_filter:
                continue
            candidates.append(result)
        except Exception:
            pass

    if not candidates:
        return None

    # Return highest confidence
    return max(candidates, key=lambda r: r.confidence)


# ---------------------------------------------------------------------------
# Strategy config loader
# ---------------------------------------------------------------------------

def load_strategy_config(config_path: Path | None = None) -> dict:
    """Load strategy configuration from JSON file.

    Expected format:
    {
        "default_family": "ema_mean_reversion",
        "regime_assignments": {
            "low_vol": ["ema_mean_reversion", "vwap_reversion"],
            "normal": ["ema_mean_reversion", "momentum", "trend_following"],
            "trending": ["trend_following", "breakout"],
            "extended": ["ema_mean_reversion", "vwap_reversion"]
        },
        "strategy_overrides": {
            "atlas-gap-xxx": "breakout",
            "atlas-mr-xxx": "ema_mean_reversion"
        }
    }
    """
    if config_path is None:
        config_path = (Path(__file__).resolve().parent.parent.parent.parent
                       / "workspace" / "quant" / "shared" / "config" / "strategy_config.json")
    if not config_path.exists():
        return {
            "default_family": "ema_mean_reversion",
            "regime_assignments": {
                "low_vol": ["ema_mean_reversion", "vwap_reversion"],
                "normal": ["ema_mean_reversion", "momentum", "trend_following"],
                "trending": ["trend_following", "breakout"],
                "extended": ["ema_mean_reversion", "vwap_reversion"],
            },
            "strategy_overrides": {},
        }
    try:
        return json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"default_family": "ema_mean_reversion"}
