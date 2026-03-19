"""In-sample parameter optimization.

Strictly operates on TRAIN data only. Evaluates candidates by running
the strategy on train bars and computing reward_proxy. Returns the best
params found, which are then evaluated OOS by the sim.

This maintains the leakage firewall: optimizer never sees test bars.
"""
import random
import math

from .strategies import run_strategy
from .candidate_gen import PARAM_SPACES


def _evaluate_on_bars(family_id, bars, params, cost_per_trade=0.0):
    """Run strategy on bars and compute quick metrics for optimization.

    Args:
        family_id: strategy family name
        bars: enriched bar data
        params: strategy params
        cost_per_trade: round-trip cost per trade in points (default 0.0)

    Returns dict with trades, pnl, profit_factor, reward_proxy, or None if
    the strategy produced no trades.
    """
    trade_list = run_strategy(family_id, bars, params)
    if not trade_list:
        return None

    gross_profit = 0.0
    gross_loss = 0.0
    equity = 0.0
    peak = 0.0
    max_dd = 0.0

    for t in trade_list:
        pnl = t["pnl"] - cost_per_trade
        equity += pnl
        peak = max(peak, equity)
        dd = max(0.0, peak - equity)
        max_dd = max(max_dd, dd)
        if pnl > 0:
            gross_profit += pnl
        else:
            gross_loss += abs(pnl)

    n = len(trade_list)
    total_pnl = equity
    pf = (gross_profit / gross_loss) if gross_loss > 0 else 999.0
    expectancy = total_pnl / n
    n_eff = 200.0 * (1 - math.exp(-n / 200.0))
    reward_proxy = (expectancy * n_eff) / (1 + max_dd / 1000.0)

    return {
        "trades": n,
        "pnl": total_pnl,
        "profit_factor": pf,
        "max_dd": max_dd,
        "reward_proxy": reward_proxy,
    }


def optimize_params(family_id, train_bars, base_params, n_trials=20, seed=None,
                    cost_per_trade=0.0):
    """Random search optimization over param space using TRAIN data only.

    Generates n_trials random param sets around the base_params,
    evaluates each on train_bars, returns the best by reward_proxy.

    Args:
        family_id: strategy family name
        train_bars: enriched bars from train period ONLY
        base_params: starting params dict
        n_trials: number of random trials
        seed: random seed
        cost_per_trade: round-trip cost per trade in points (default 0.0)

    Returns:
        dict with:
            best_params: optimized params
            best_reward: best reward_proxy on train data
            trials_evaluated: number of trials run
            baseline_reward: reward of base_params
    """
    rng = random.Random(seed)
    space = PARAM_SPACES.get(family_id, {})

    # Evaluate baseline
    baseline = _evaluate_on_bars(family_id, train_bars, base_params, cost_per_trade)
    best_params = dict(base_params)
    best_reward = baseline["reward_proxy"] if baseline else -1e9

    trials_evaluated = 0

    for _ in range(n_trials):
        # Generate random params within space bounds
        trial_params = {}
        for pname, val in base_params.items():
            if pname in space:
                lo, hi, ptype, _ = space[pname]
                new_val = rng.uniform(lo, hi)
                if ptype == "int":
                    new_val = int(round(new_val))
                else:
                    new_val = round(new_val, 4)
                trial_params[pname] = new_val
            else:
                trial_params[pname] = val

        result = _evaluate_on_bars(family_id, train_bars, trial_params, cost_per_trade)
        trials_evaluated += 1

        if result is not None and result["reward_proxy"] > best_reward:
            best_reward = result["reward_proxy"]
            best_params = dict(trial_params)

    return {
        "best_params": best_params,
        "best_reward": round(best_reward, 6),
        "trials_evaluated": trials_evaluated,
        "baseline_reward": round(baseline["reward_proxy"], 6) if baseline else None,
    }
