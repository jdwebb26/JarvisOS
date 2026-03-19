"""Strategy mutation / ablation experiments for daily research.

Tests structural strategy changes that might improve fold consistency.
Each mutation wraps the base strategy logic with a specific behavioral
change, producing a new trade list from the same bars+params.

This is research-only — mutations do NOT modify registered strategies.

Available bar features: open, high, low, close, volume, vix,
ema_fast, ema_slow, atr, vix_regime.
"""

import math
import statistics
from copy import deepcopy

from .strategies import run_strategy
from .features import compute_features
from .sim import (
    _compute_fold_metrics, _cost_per_trade, _candidate_seed_salt,
)
from .gates import evaluate_fold_gates
from .optimizer import optimize_params
from .candidate_gen import FAMILY_TIMEFRAME


# ---------------------------------------------------------------------------
# Mutation wrappers — each takes (bars, params) and returns trade list
# ---------------------------------------------------------------------------

def _base_ema_crossover(bars, params):
    """Baseline ema_crossover — delegates to registered strategy."""
    return run_strategy("ema_crossover", bars, params)


def _base_breakout(bars, params):
    """Baseline breakout — delegates to registered strategy."""
    return run_strategy("breakout", bars, params)


def _ema_with_trend_filter(bars, params):
    """EMA crossover that only enters in the direction of the slow EMA trend.

    Skips cross_up when ema_slow is falling, skips cross_down when rising.
    Trend measured as ema_slow change over last 5 bars.
    """
    atr_stop = float(params.get("atr_stop_mult", 2.0))
    atr_tp = float(params.get("atr_tp_mult", 3.0))
    min_atr = float(params.get("min_atr", 0.5))
    trend_lb = int(params.get("trend_lookback", 5))

    trades = []
    position = None

    for i, bar in enumerate(bars):
        if i < max(1, trend_lb):
            continue

        atr = bar.get("atr", 0.0)
        ema_f = bar.get("ema_fast", 0.0)
        ema_s = bar.get("ema_slow", 0.0)
        prev_ema_f = bars[i - 1].get("ema_fast", 0.0)
        prev_ema_s = bars[i - 1].get("ema_slow", 0.0)

        # Trend direction from slow EMA slope
        ema_s_back = bars[i - trend_lb].get("ema_slow", ema_s)
        trend_up = ema_s > ema_s_back
        trend_down = ema_s < ema_s_back

        # Exit logic (same as base)
        if position is not None:
            hit_stop = hit_tp = False
            exit_price = None
            if position["direction"] == 1:
                if bar["low"] <= position["stop"]:
                    hit_stop, exit_price = True, position["stop"]
                elif bar["high"] >= position["tp"]:
                    hit_tp, exit_price = True, position["tp"]
            else:
                if bar["high"] >= position["stop"]:
                    hit_stop, exit_price = True, position["stop"]
                elif bar["low"] <= position["tp"]:
                    hit_tp, exit_price = True, position["tp"]
            if hit_stop or hit_tp:
                pnl = (exit_price - position["entry_price"]) * position["direction"]
                trades.append({
                    "entry_bar": position["entry_bar"], "exit_bar": i,
                    "direction": position["direction"],
                    "entry_price": position["entry_price"],
                    "exit_price": round(exit_price, 2),
                    "pnl": round(pnl, 2),
                    "exit_reason": "stop" if hit_stop else "take_profit",
                })
                position = None

        # Entry with trend filter
        if position is None and atr >= min_atr:
            cross_up = prev_ema_f <= prev_ema_s and ema_f > ema_s
            cross_down = prev_ema_f >= prev_ema_s and ema_f < ema_s

            if cross_up and trend_up:
                entry = bar["close"]
                position = {
                    "direction": 1, "entry_price": entry,
                    "stop": round(entry - atr * atr_stop, 2),
                    "tp": round(entry + atr * atr_tp, 2),
                    "entry_bar": i,
                }
            elif cross_down and trend_down:
                entry = bar["close"]
                position = {
                    "direction": -1, "entry_price": entry,
                    "stop": round(entry + atr * atr_stop, 2),
                    "tp": round(entry - atr * atr_tp, 2),
                    "entry_bar": i,
                }

    if position is not None and bars:
        last = bars[-1]
        exit_price = last["close"]
        pnl = (exit_price - position["entry_price"]) * position["direction"]
        trades.append({
            "entry_bar": position["entry_bar"], "exit_bar": len(bars) - 1,
            "direction": position["direction"],
            "entry_price": position["entry_price"],
            "exit_price": round(exit_price, 2), "pnl": round(pnl, 2),
            "exit_reason": "end_of_data",
        })
    return trades


def _ema_with_cooldown(bars, params):
    """EMA crossover with cooldown after a stop-loss exit.

    Skips the next N bars after a stop-out before allowing new entries.
    """
    base_trades = run_strategy("ema_crossover", bars, params)
    cooldown_bars = int(params.get("cooldown_bars", 10))

    # Replay: suppress entries that occur within cooldown of a stopout
    atr_stop = float(params.get("atr_stop_mult", 2.0))
    atr_tp = float(params.get("atr_tp_mult", 3.0))
    min_atr = float(params.get("min_atr", 0.5))

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

        if position is not None:
            hit_stop = hit_tp = False
            exit_price = None
            if position["direction"] == 1:
                if bar["low"] <= position["stop"]:
                    hit_stop, exit_price = True, position["stop"]
                elif bar["high"] >= position["tp"]:
                    hit_tp, exit_price = True, position["tp"]
            else:
                if bar["high"] >= position["stop"]:
                    hit_stop, exit_price = True, position["stop"]
                elif bar["low"] <= position["tp"]:
                    hit_tp, exit_price = True, position["tp"]
            if hit_stop or hit_tp:
                pnl = (exit_price - position["entry_price"]) * position["direction"]
                trades.append({
                    "entry_bar": position["entry_bar"], "exit_bar": i,
                    "direction": position["direction"],
                    "entry_price": position["entry_price"],
                    "exit_price": round(exit_price, 2),
                    "pnl": round(pnl, 2),
                    "exit_reason": "stop" if hit_stop else "take_profit",
                })
                if hit_stop:
                    cooldown_until = i + cooldown_bars
                position = None

        if position is None and atr >= min_atr and i > cooldown_until:
            cross_up = prev_ema_f <= prev_ema_s and ema_f > ema_s
            cross_down = prev_ema_f >= prev_ema_s and ema_f < ema_s
            if cross_up:
                entry = bar["close"]
                position = {
                    "direction": 1, "entry_price": entry,
                    "stop": round(entry - atr * atr_stop, 2),
                    "tp": round(entry + atr * atr_tp, 2),
                    "entry_bar": i,
                }
            elif cross_down:
                entry = bar["close"]
                position = {
                    "direction": -1, "entry_price": entry,
                    "stop": round(entry + atr * atr_stop, 2),
                    "tp": round(entry - atr * atr_tp, 2),
                    "entry_bar": i,
                }

    if position is not None and bars:
        last = bars[-1]
        exit_price = last["close"]
        pnl = (exit_price - position["entry_price"]) * position["direction"]
        trades.append({
            "entry_bar": position["entry_bar"], "exit_bar": len(bars) - 1,
            "direction": position["direction"],
            "entry_price": position["entry_price"],
            "exit_price": round(exit_price, 2), "pnl": round(pnl, 2),
            "exit_reason": "end_of_data",
        })
    return trades


def _ema_with_max_holding(bars, params):
    """EMA crossover with a maximum holding period (time stop).

    Exits at close after max_hold_bars if neither stop nor TP hit.
    """
    atr_stop = float(params.get("atr_stop_mult", 2.0))
    atr_tp = float(params.get("atr_tp_mult", 3.0))
    min_atr = float(params.get("min_atr", 0.5))
    max_hold = int(params.get("max_hold_bars", 20))

    trades = []
    position = None

    for i, bar in enumerate(bars):
        if i < 1:
            continue
        atr = bar.get("atr", 0.0)
        ema_f = bar.get("ema_fast", 0.0)
        ema_s = bar.get("ema_slow", 0.0)
        prev_ema_f = bars[i - 1].get("ema_fast", 0.0)
        prev_ema_s = bars[i - 1].get("ema_slow", 0.0)

        if position is not None:
            bars_held = i - position["entry_bar"]
            hit_stop = hit_tp = time_exit = False
            exit_price = None

            if position["direction"] == 1:
                if bar["low"] <= position["stop"]:
                    hit_stop, exit_price = True, position["stop"]
                elif bar["high"] >= position["tp"]:
                    hit_tp, exit_price = True, position["tp"]
            else:
                if bar["high"] >= position["stop"]:
                    hit_stop, exit_price = True, position["stop"]
                elif bar["low"] <= position["tp"]:
                    hit_tp, exit_price = True, position["tp"]

            if not (hit_stop or hit_tp) and bars_held >= max_hold:
                time_exit = True
                exit_price = bar["close"]

            if hit_stop or hit_tp or time_exit:
                pnl = (exit_price - position["entry_price"]) * position["direction"]
                reason = "stop" if hit_stop else ("take_profit" if hit_tp
                                                   else "time_exit")
                trades.append({
                    "entry_bar": position["entry_bar"], "exit_bar": i,
                    "direction": position["direction"],
                    "entry_price": position["entry_price"],
                    "exit_price": round(exit_price, 2),
                    "pnl": round(pnl, 2),
                    "exit_reason": reason,
                })
                position = None

        if position is None and atr >= min_atr:
            cross_up = prev_ema_f <= prev_ema_s and ema_f > ema_s
            cross_down = prev_ema_f >= prev_ema_s and ema_f < ema_s
            if cross_up:
                entry = bar["close"]
                position = {
                    "direction": 1, "entry_price": entry,
                    "stop": round(entry - atr * atr_stop, 2),
                    "tp": round(entry + atr * atr_tp, 2),
                    "entry_bar": i,
                }
            elif cross_down:
                entry = bar["close"]
                position = {
                    "direction": -1, "entry_price": entry,
                    "stop": round(entry + atr * atr_stop, 2),
                    "tp": round(entry - atr * atr_tp, 2),
                    "entry_bar": i,
                }

    if position is not None and bars:
        last = bars[-1]
        exit_price = last["close"]
        pnl = (exit_price - position["entry_price"]) * position["direction"]
        trades.append({
            "entry_bar": position["entry_bar"], "exit_bar": len(bars) - 1,
            "direction": position["direction"],
            "entry_price": position["entry_price"],
            "exit_price": round(exit_price, 2), "pnl": round(pnl, 2),
            "exit_reason": "end_of_data",
        })
    return trades


def _breakout_with_trend_alignment(bars, params):
    """Breakout that only enters in the direction of the slow EMA trend.

    Skips long breakouts when ema_slow is falling, short when rising.
    """
    lookback = int(params.get("lookback", 20))
    atr_stop = float(params.get("atr_stop_mult", 1.5))
    atr_tp = float(params.get("atr_tp_mult", 3.0))
    min_atr = float(params.get("min_atr", 0.5))
    trend_lb = int(params.get("trend_lookback", 5))

    trades = []
    position = None

    for i, bar in enumerate(bars):
        if i < max(lookback, trend_lb):
            continue

        atr = bar.get("atr", 0.0)
        ema_s = bar.get("ema_slow", 0.0)
        ema_s_back = bars[i - trend_lb].get("ema_slow", ema_s)
        trend_up = ema_s > ema_s_back
        trend_down = ema_s < ema_s_back

        window = bars[i - lookback:i]
        chan_high = max(b["high"] for b in window)
        chan_low = min(b["low"] for b in window)

        if position is not None:
            hit_stop = hit_tp = False
            exit_price = None
            if position["direction"] == 1:
                if bar["low"] <= position["stop"]:
                    hit_stop, exit_price = True, position["stop"]
                elif bar["high"] >= position["tp"]:
                    hit_tp, exit_price = True, position["tp"]
            else:
                if bar["high"] >= position["stop"]:
                    hit_stop, exit_price = True, position["stop"]
                elif bar["low"] <= position["tp"]:
                    hit_tp, exit_price = True, position["tp"]
            if hit_stop or hit_tp:
                pnl = (exit_price - position["entry_price"]) * position["direction"]
                trades.append({
                    "entry_bar": position["entry_bar"], "exit_bar": i,
                    "direction": position["direction"],
                    "entry_price": position["entry_price"],
                    "exit_price": round(exit_price, 2),
                    "pnl": round(pnl, 2),
                    "exit_reason": "stop" if hit_stop else "take_profit",
                })
                position = None

        if position is None and atr >= min_atr:
            if bar["close"] > chan_high and trend_up:
                entry = bar["close"]
                position = {
                    "direction": 1, "entry_price": entry,
                    "stop": round(entry - atr * atr_stop, 2),
                    "tp": round(entry + atr * atr_tp, 2),
                    "entry_bar": i,
                }
            elif bar["close"] < chan_low and trend_down:
                entry = bar["close"]
                position = {
                    "direction": -1, "entry_price": entry,
                    "stop": round(entry + atr * atr_stop, 2),
                    "tp": round(entry - atr * atr_tp, 2),
                    "entry_bar": i,
                }

    if position is not None and bars:
        last = bars[-1]
        exit_price = last["close"]
        pnl = (exit_price - position["entry_price"]) * position["direction"]
        trades.append({
            "entry_bar": position["entry_bar"], "exit_bar": len(bars) - 1,
            "direction": position["direction"],
            "entry_price": position["entry_price"],
            "exit_price": round(exit_price, 2), "pnl": round(pnl, 2),
            "exit_reason": "end_of_data",
        })
    return trades


# ---------------------------------------------------------------------------
# Mutation registry
# ---------------------------------------------------------------------------

MUTATIONS = {
    "ema_baseline": {
        "family": "ema_crossover",
        "description": "Baseline EMA crossover (no mutation)",
        "strategy_fn": _base_ema_crossover,
        "extra_params": {},
    },
    "ema_trend_filter": {
        "family": "ema_crossover",
        "description": "Only enter in direction of slow-EMA 5-bar trend",
        "strategy_fn": _ema_with_trend_filter,
        "extra_params": {"trend_lookback": 5},
    },
    "ema_cooldown_10": {
        "family": "ema_crossover",
        "description": "10-bar cooldown after stop-loss exit",
        "strategy_fn": _ema_with_cooldown,
        "extra_params": {"cooldown_bars": 10},
    },
    "ema_cooldown_20": {
        "family": "ema_crossover",
        "description": "20-bar cooldown after stop-loss exit",
        "strategy_fn": _ema_with_cooldown,
        "extra_params": {"cooldown_bars": 20},
    },
    "ema_max_hold_15": {
        "family": "ema_crossover",
        "description": "Force exit after 15 bars if no stop/TP hit",
        "strategy_fn": _ema_with_max_holding,
        "extra_params": {"max_hold_bars": 15},
    },
    "ema_max_hold_30": {
        "family": "ema_crossover",
        "description": "Force exit after 30 bars if no stop/TP hit",
        "strategy_fn": _ema_with_max_holding,
        "extra_params": {"max_hold_bars": 30},
    },
    "brk_baseline": {
        "family": "breakout",
        "description": "Baseline breakout (no mutation)",
        "strategy_fn": _base_breakout,
        "extra_params": {},
    },
    "brk_trend_aligned": {
        "family": "breakout",
        "description": "Only enter breakout aligned with slow-EMA trend",
        "strategy_fn": _breakout_with_trend_alignment,
        "extra_params": {"trend_lookback": 5},
    },
}


# ---------------------------------------------------------------------------
# Run mutation experiment for one candidate across folds
# ---------------------------------------------------------------------------

def run_mutation_experiment(candidate, data, folds, config, gate_profile,
                            mutations=None):
    """Evaluate a candidate under multiple strategy mutations.

    The optimizer refit is done once per fold (using the base family's
    registered strategy).  Each mutation then runs its modified strategy
    logic on the OOS window using the same refitted params.

    This isolates the effect of the structural change from param
    differences.
    """
    if mutations is None:
        mutations = MUTATIONS

    fam = candidate["logic_family_id"]
    base_params = candidate["params"]
    cid = candidate["candidate_id"]
    features_cfg = config.get("features", {})
    cost_model = config.get("cost_model")
    cost = _cost_per_trade(cost_model)
    n_cap = int(config.get("n_cap", 200))
    opt_n_trials = int(config.get("optimizer_n_trials", 15))
    opt_seed_base = int(config.get("optimizer_seed", 42))
    salt = _candidate_seed_salt(fam, base_params)
    tf_bucket = FAMILY_TIMEFRAME.get(fam, config.get("timeframe_bucket",
                                                      "multi_hour_overnight"))
    enriched = compute_features(data, features_cfg)

    # Phase 1: refit per fold (once, shared)
    per_fold_params = []
    for fi, fold in enumerate(folds):
        train_bars = enriched[fold["train_start"]:fold["train_end"]]
        fold_seed = opt_seed_base + fi + salt
        opt = optimize_params(fam, train_bars, base_params,
                              n_trials=opt_n_trials, seed=fold_seed,
                              cost_per_trade=cost)
        per_fold_params.append(opt["best_params"])

    # Phase 2: for each mutation, run on OOS
    relevant_mutations = {k: v for k, v in mutations.items()
                          if v["family"] == fam}

    mutation_results = {}
    for mname, mspec in relevant_mutations.items():
        strat_fn = mspec["strategy_fn"]
        extra = mspec["extra_params"]
        fold_details = []

        for fi, fold in enumerate(folds):
            run_params = {**per_fold_params[fi], **extra}
            test_bars = enriched[fold["test_start"]:fold["test_end"]]

            trade_list = strat_fn(test_bars, run_params)

            if not trade_list:
                fold_details.append({
                    "fold_id": fold["fold_id"],
                    "trades": 0, "pf": 0.0, "sharpe": 0.0,
                    "sortino": 0.0, "max_dd": 0.0, "pnl": 0.0,
                    "gate_overall": "FAIL", "gate_fails": ["no_trades"],
                })
                continue

            metrics = _compute_fold_metrics(trade_list, fold["fold_id"],
                                            n_cap, cost_model)
            if metrics is None:
                fold_details.append({
                    "fold_id": fold["fold_id"],
                    "trades": 0, "pf": 0.0, "sharpe": 0.0,
                    "sortino": 0.0, "max_dd": 0.0, "pnl": 0.0,
                    "gate_overall": "FAIL", "gate_fails": ["no_trades"],
                })
                continue

            gates = evaluate_fold_gates(metrics, tf_bucket,
                                        gate_profile=gate_profile)
            fold_details.append({
                "fold_id": fold["fold_id"],
                "trades": metrics["trades"],
                "pf": round(metrics["profit_factor"], 4),
                "sharpe": round(metrics["sharpe"], 4),
                "sortino": round(metrics["sortino"], 4),
                "max_dd": round(metrics["max_drawdown_proxy"], 2),
                "pnl": round(metrics["pnl"], 2),
                "gate_overall": gates["overall"],
                "gate_fails": [k for k, v in gates.items()
                               if k != "overall" and isinstance(v, dict)
                               and not v.get("pass")],
            })

        evaluated = [f for f in fold_details if f["trades"] > 0]
        passed = [f for f in evaluated if f["gate_overall"] == "PASS"]

        mutation_results[mname] = {
            "description": mspec["description"],
            "extra_params": extra,
            "folds_passed": len(passed),
            "folds_evaluated": len(evaluated),
            "folds_no_trades": sum(1 for f in fold_details if f["trades"] == 0),
            "pass_rate": f"{len(passed)}/{len(fold_details)}",
            "avg_pf": (round(statistics.mean(f["pf"] for f in evaluated), 4)
                       if evaluated else 0.0),
            "avg_sharpe": (round(statistics.mean(f["sharpe"] for f in evaluated), 4)
                           if evaluated else 0.0),
            "avg_sortino": (round(statistics.mean(f["sortino"] for f in evaluated), 4)
                            if evaluated else 0.0),
            "total_trades": sum(f["trades"] for f in fold_details),
            "per_fold": fold_details,
        }

    return {
        "candidate_id": cid,
        "family": fam,
        "params": base_params,
        "mutation_results": mutation_results,
    }
