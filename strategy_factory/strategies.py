"""Param-driven strategy templates for NQ futures.

Each strategy function takes enriched bar data and params, and returns
a list of completed trades. Strategies manage position state internally
(one position at a time, no pyramiding).

Trade dict:
    entry_bar: int (bar_index of entry)
    exit_bar: int (bar_index of exit)
    direction: 1 (long) or -1 (short)
    entry_price: float
    exit_price: float
    pnl: float (points, before costs)
    exit_reason: "signal" | "stop" | "take_profit" | "end_of_data"
"""


STRATEGY_REGISTRY = {}


def register(name):
    def decorator(fn):
        STRATEGY_REGISTRY[name] = fn
        return fn
    return decorator


def run_strategy(family_id, bars, params):
    """Run a registered strategy on enriched bars with given params."""
    if family_id not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy family: {family_id}. "
                         f"Available: {list(STRATEGY_REGISTRY.keys())}")
    return STRATEGY_REGISTRY[family_id](bars, params)


# ---------------------------------------------------------------------------
# Strategy: EMA Crossover
# ---------------------------------------------------------------------------
@register("ema_crossover")
def ema_crossover(bars, params):
    """EMA fast/slow crossover with ATR-based stop and take-profit.

    Params:
        atr_stop_mult: float — stop distance = atr * mult (default 2.0)
        atr_tp_mult: float — take-profit distance = atr * mult (default 3.0)
        min_atr: float — skip trade if ATR below this (default 0.5)
    """
    atr_stop = float(params.get("atr_stop_mult", 2.0))
    atr_tp = float(params.get("atr_tp_mult", 3.0))
    min_atr = float(params.get("min_atr", 0.5))

    trades = []
    position = None  # {direction, entry_price, stop, tp, entry_bar}

    for i, bar in enumerate(bars):
        if i < 1:
            continue

        atr = bar.get("atr", 0.0)
        ema_f = bar.get("ema_fast", 0.0)
        ema_s = bar.get("ema_slow", 0.0)
        prev_ema_f = bars[i - 1].get("ema_fast", 0.0)
        prev_ema_s = bars[i - 1].get("ema_slow", 0.0)

        # Check stops/TP on current bar if in position
        if position is not None:
            hit_stop = False
            hit_tp = False
            exit_price = None

            if position["direction"] == 1:
                if bar["low"] <= position["stop"]:
                    hit_stop = True
                    exit_price = position["stop"]
                elif bar["high"] >= position["tp"]:
                    hit_tp = True
                    exit_price = position["tp"]
            else:
                if bar["high"] >= position["stop"]:
                    hit_stop = True
                    exit_price = position["stop"]
                elif bar["low"] <= position["tp"]:
                    hit_tp = True
                    exit_price = position["tp"]

            if hit_stop or hit_tp:
                pnl = (exit_price - position["entry_price"]) * position["direction"]
                trades.append({
                    "entry_bar": position["entry_bar"],
                    "exit_bar": i,
                    "direction": position["direction"],
                    "entry_price": position["entry_price"],
                    "exit_price": round(exit_price, 2),
                    "pnl": round(pnl, 2),
                    "exit_reason": "stop" if hit_stop else "take_profit",
                })
                position = None

        # Signal generation: crossover
        if position is None and atr >= min_atr:
            cross_up = prev_ema_f <= prev_ema_s and ema_f > ema_s
            cross_down = prev_ema_f >= prev_ema_s and ema_f < ema_s

            if cross_up:
                entry = bar["close"]
                position = {
                    "direction": 1,
                    "entry_price": entry,
                    "stop": round(entry - atr * atr_stop, 2),
                    "tp": round(entry + atr * atr_tp, 2),
                    "entry_bar": i,
                }
            elif cross_down:
                entry = bar["close"]
                position = {
                    "direction": -1,
                    "entry_price": entry,
                    "stop": round(entry + atr * atr_stop, 2),
                    "tp": round(entry - atr * atr_tp, 2),
                    "entry_bar": i,
                }

    # Close any open position at end of data
    if position is not None and bars:
        last = bars[-1]
        exit_price = last["close"]
        pnl = (exit_price - position["entry_price"]) * position["direction"]
        trades.append({
            "entry_bar": position["entry_bar"],
            "exit_bar": len(bars) - 1,
            "direction": position["direction"],
            "entry_price": position["entry_price"],
            "exit_price": round(exit_price, 2),
            "pnl": round(pnl, 2),
            "exit_reason": "end_of_data",
        })

    return trades


# ---------------------------------------------------------------------------
# Strategy: EMA Crossover with Cooldown (ema_crossover_cd)
# ---------------------------------------------------------------------------
@register("ema_crossover_cd")
def ema_crossover_cd(bars, params):
    """EMA crossover with post-stopout cooldown.

    Identical to ema_crossover except: after a stop-loss exit, the
    strategy pauses for ``cooldown_bars`` bars before allowing new
    entries.  This avoids revenge re-entry during whipsaw conditions
    that were identified as the primary source of fold failures in
    mutation experiments (operator_report_8).

    Params:
        atr_stop_mult: float — stop distance = atr * mult (default 2.0)
        atr_tp_mult: float — take-profit distance = atr * mult (default 3.0)
        min_atr: float — skip trade if ATR below this (default 0.5)
        cooldown_bars: int — bars to wait after stopout (default 10)
    """
    atr_stop = float(params.get("atr_stop_mult", 2.0))
    atr_tp = float(params.get("atr_tp_mult", 3.0))
    min_atr = float(params.get("min_atr", 0.5))
    cooldown = int(params.get("cooldown_bars", 10))

    trades = []
    position = None
    cooldown_until = -1

    for i, bar in enumerate(bars):
        if i < 1:
            continue

        atr = bar.get("atr", 0.0)
        ema_f = bar.get("ema_fast", 0.0)
        ema_s = bar.get("ema_slow", 0.0)
        prev_ema_f = bars[i - 1].get("ema_fast", 0.0)
        prev_ema_s = bars[i - 1].get("ema_slow", 0.0)

        # Check stops/TP on current bar if in position
        if position is not None:
            hit_stop = False
            hit_tp = False
            exit_price = None

            if position["direction"] == 1:
                if bar["low"] <= position["stop"]:
                    hit_stop = True
                    exit_price = position["stop"]
                elif bar["high"] >= position["tp"]:
                    hit_tp = True
                    exit_price = position["tp"]
            else:
                if bar["high"] >= position["stop"]:
                    hit_stop = True
                    exit_price = position["stop"]
                elif bar["low"] <= position["tp"]:
                    hit_tp = True
                    exit_price = position["tp"]

            if hit_stop or hit_tp:
                pnl = (exit_price - position["entry_price"]) * position["direction"]
                trades.append({
                    "entry_bar": position["entry_bar"],
                    "exit_bar": i,
                    "direction": position["direction"],
                    "entry_price": position["entry_price"],
                    "exit_price": round(exit_price, 2),
                    "pnl": round(pnl, 2),
                    "exit_reason": "stop" if hit_stop else "take_profit",
                })
                if hit_stop:
                    cooldown_until = i + cooldown
                position = None

        # Signal generation: crossover (with cooldown check)
        if position is None and atr >= min_atr and i > cooldown_until:
            cross_up = prev_ema_f <= prev_ema_s and ema_f > ema_s
            cross_down = prev_ema_f >= prev_ema_s and ema_f < ema_s

            if cross_up:
                entry = bar["close"]
                position = {
                    "direction": 1,
                    "entry_price": entry,
                    "stop": round(entry - atr * atr_stop, 2),
                    "tp": round(entry + atr * atr_tp, 2),
                    "entry_bar": i,
                }
            elif cross_down:
                entry = bar["close"]
                position = {
                    "direction": -1,
                    "entry_price": entry,
                    "stop": round(entry + atr * atr_stop, 2),
                    "tp": round(entry - atr * atr_tp, 2),
                    "entry_bar": i,
                }

    # Close any open position at end of data
    if position is not None and bars:
        last = bars[-1]
        exit_price = last["close"]
        pnl = (exit_price - position["entry_price"]) * position["direction"]
        trades.append({
            "entry_bar": position["entry_bar"],
            "exit_bar": len(bars) - 1,
            "direction": position["direction"],
            "entry_price": position["entry_price"],
            "exit_price": round(exit_price, 2),
            "pnl": round(pnl, 2),
            "exit_reason": "end_of_data",
        })

    return trades


# ---------------------------------------------------------------------------
# Strategy: Mean Reversion
# ---------------------------------------------------------------------------
@register("mean_reversion")
def mean_reversion(bars, params):
    """Mean reversion: enter when price deviates from EMA by K*ATR,
    exit when price returns to EMA (or stop hit).

    Params:
        entry_atr_mult: float — enter when |price - ema| > atr * mult (default 1.5)
        atr_stop_mult: float — stop distance beyond entry (default 2.0)
        ema_key: str — which EMA to revert to (default "ema_slow")
        min_atr: float — minimum ATR to trade (default 0.5)
    """
    entry_mult = float(params.get("entry_atr_mult", 1.5))
    atr_stop = float(params.get("atr_stop_mult", 2.0))
    ema_key = params.get("ema_key", "ema_slow")
    min_atr = float(params.get("min_atr", 0.5))

    trades = []
    position = None

    for i, bar in enumerate(bars):
        atr = bar.get("atr", 0.0)
        ema = bar.get(ema_key, bar["close"])
        price = bar["close"]

        # Check exits
        if position is not None:
            hit_stop = False
            reverted = False
            exit_price = None

            if position["direction"] == 1:
                if bar["low"] <= position["stop"]:
                    hit_stop = True
                    exit_price = position["stop"]
                elif price >= ema:
                    reverted = True
                    exit_price = price
            else:
                if bar["high"] >= position["stop"]:
                    hit_stop = True
                    exit_price = position["stop"]
                elif price <= ema:
                    reverted = True
                    exit_price = price

            if hit_stop or reverted:
                pnl = (exit_price - position["entry_price"]) * position["direction"]
                trades.append({
                    "entry_bar": position["entry_bar"],
                    "exit_bar": i,
                    "direction": position["direction"],
                    "entry_price": position["entry_price"],
                    "exit_price": round(exit_price, 2),
                    "pnl": round(pnl, 2),
                    "exit_reason": "stop" if hit_stop else "signal",
                })
                position = None

        # Entry signals
        if position is None and atr >= min_atr:
            deviation = price - ema
            threshold = atr * entry_mult

            if deviation < -threshold:
                # Price below EMA — buy (mean revert up)
                entry = price
                position = {
                    "direction": 1,
                    "entry_price": entry,
                    "stop": round(entry - atr * atr_stop, 2),
                    "entry_bar": i,
                }
            elif deviation > threshold:
                # Price above EMA — sell (mean revert down)
                entry = price
                position = {
                    "direction": -1,
                    "entry_price": entry,
                    "stop": round(entry + atr * atr_stop, 2),
                    "entry_bar": i,
                }

    if position is not None and bars:
        last = bars[-1]
        exit_price = last["close"]
        pnl = (exit_price - position["entry_price"]) * position["direction"]
        trades.append({
            "entry_bar": position["entry_bar"],
            "exit_bar": len(bars) - 1,
            "direction": position["direction"],
            "entry_price": position["entry_price"],
            "exit_price": round(exit_price, 2),
            "pnl": round(pnl, 2),
            "exit_reason": "end_of_data",
        })

    return trades


# ---------------------------------------------------------------------------
# Strategy: Breakout
# ---------------------------------------------------------------------------
@register("breakout")
def breakout(bars, params):
    """N-bar high/low breakout with ATR-based stop and take-profit.

    Params:
        lookback: int — N-bar lookback for high/low channel (default 20)
        atr_stop_mult: float — stop distance (default 1.5)
        atr_tp_mult: float — take-profit distance (default 3.0)
        min_atr: float — minimum ATR to trade (default 0.5)
    """
    lookback = int(params.get("lookback", 20))
    atr_stop = float(params.get("atr_stop_mult", 1.5))
    atr_tp = float(params.get("atr_tp_mult", 3.0))
    min_atr = float(params.get("min_atr", 0.5))

    trades = []
    position = None

    for i, bar in enumerate(bars):
        if i < lookback:
            continue

        atr = bar.get("atr", 0.0)
        window = bars[i - lookback:i]
        chan_high = max(b["high"] for b in window)
        chan_low = min(b["low"] for b in window)

        # Check exits
        if position is not None:
            hit_stop = False
            hit_tp = False
            exit_price = None

            if position["direction"] == 1:
                if bar["low"] <= position["stop"]:
                    hit_stop = True
                    exit_price = position["stop"]
                elif bar["high"] >= position["tp"]:
                    hit_tp = True
                    exit_price = position["tp"]
            else:
                if bar["high"] >= position["stop"]:
                    hit_stop = True
                    exit_price = position["stop"]
                elif bar["low"] <= position["tp"]:
                    hit_tp = True
                    exit_price = position["tp"]

            if hit_stop or hit_tp:
                pnl = (exit_price - position["entry_price"]) * position["direction"]
                trades.append({
                    "entry_bar": position["entry_bar"],
                    "exit_bar": i,
                    "direction": position["direction"],
                    "entry_price": position["entry_price"],
                    "exit_price": round(exit_price, 2),
                    "pnl": round(pnl, 2),
                    "exit_reason": "stop" if hit_stop else "take_profit",
                })
                position = None

        # Entry: breakout above channel high or below channel low
        if position is None and atr >= min_atr:
            if bar["close"] > chan_high:
                entry = bar["close"]
                position = {
                    "direction": 1,
                    "entry_price": entry,
                    "stop": round(entry - atr * atr_stop, 2),
                    "tp": round(entry + atr * atr_tp, 2),
                    "entry_bar": i,
                }
            elif bar["close"] < chan_low:
                entry = bar["close"]
                position = {
                    "direction": -1,
                    "entry_price": entry,
                    "stop": round(entry + atr * atr_stop, 2),
                    "tp": round(entry - atr * atr_tp, 2),
                    "entry_bar": i,
                }

    if position is not None and bars:
        last = bars[-1]
        exit_price = last["close"]
        pnl = (exit_price - position["entry_price"]) * position["direction"]
        trades.append({
            "entry_bar": position["entry_bar"],
            "exit_bar": len(bars) - 1,
            "direction": position["direction"],
            "entry_price": position["entry_price"],
            "exit_price": round(exit_price, 2),
            "pnl": round(pnl, 2),
            "exit_reason": "end_of_data",
        })

    return trades
