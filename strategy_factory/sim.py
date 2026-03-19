import hashlib
import json
import math

from .strategies import run_strategy
from .features import compute_features
from .optimizer import optimize_params


def soft_saturation(n_trades, n_cap):
    return n_cap * (1 - math.exp(-float(n_trades) / float(n_cap)))


def _compute_sharpe(trade_returns):
    if len(trade_returns) < 2:
        return 0.0
    mean = sum(trade_returns) / len(trade_returns)
    var = sum((r - mean) ** 2 for r in trade_returns) / (len(trade_returns) - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std == 0.0:
        return 0.0
    return mean / std


def _compute_sortino(trade_returns):
    if len(trade_returns) < 2:
        return 0.0
    mean = sum(trade_returns) / len(trade_returns)
    downside = [min(0.0, r) ** 2 for r in trade_returns]
    down_var = sum(downside) / (len(trade_returns) - 1)
    down_std = math.sqrt(down_var) if down_var > 0 else 0.0
    if down_std == 0.0:
        return 0.0
    return mean / down_std


def _cost_per_trade(cost_model):
    """Compute round-trip cost per trade in NQ points from cost_model config."""
    if not cost_model:
        return 0.0
    comm = float(cost_model.get("commission_per_side_points", 0.0))
    slip = float(cost_model.get("slippage_per_side_points", 0.0))
    return 2.0 * (comm + slip)


def _compute_fold_metrics(trade_list, fold_id, n_cap, cost_model=None):
    """Compute all metrics from a list of trade dicts for one fold.

    When cost_model is provided, each trade's PnL is reduced by the
    round-trip cost (commission + slippage, both sides).  All downstream
    metrics (PF, Sharpe, Sortino, expectancy, drawdown) reflect post-cost
    returns.  Raw (pre-cost) PnL is preserved in ``pnl_gross``.
    """
    trades = len(trade_list)

    if trades == 0:
        return None

    rt_cost = _cost_per_trade(cost_model)

    pnl = 0.0
    pnl_gross = 0.0
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    gross_profit = 0.0
    gross_loss = 0.0
    winners = 0
    losers = 0
    trade_returns = []
    total_cost = 0.0

    for t in trade_list:
        raw_pnl = t["pnl"]
        pnl_gross += raw_pnl
        net_pnl = raw_pnl - rt_cost
        total_cost += rt_cost

        pnl += net_pnl
        equity += net_pnl
        peak = max(peak, equity)
        dd = max(0.0, peak - equity)
        max_dd = max(max_dd, dd)
        trade_returns.append(net_pnl)
        if net_pnl > 0:
            gross_profit += net_pnl
            winners += 1
        else:
            gross_loss += abs(net_pnl)
            losers += 1

    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    win_rate = winners / max(1, trades)
    avg_winner = gross_profit / max(1, winners)
    avg_loser = gross_loss / max(1, losers)
    expectancy = pnl / max(1, trades)
    n_eff = soft_saturation(trades, n_cap)
    reward_proxy = (expectancy * n_eff) / (1 + max_dd / 1000.0)
    sharpe = _compute_sharpe(trade_returns)
    sortino = _compute_sortino(trade_returns)

    return {
        "fold_id": fold_id,
        "trades": trades,
        "pnl": round(pnl, 4),
        "pnl_gross": round(pnl_gross, 4),
        "total_cost": round(total_cost, 4),
        "gross_profit": round(gross_profit, 4),
        "gross_loss": round(gross_loss, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 999.0,
        "win_rate": round(win_rate, 4),
        "winners": winners,
        "losers": losers,
        "avg_winner": round(avg_winner, 4),
        "avg_loser": round(avg_loser, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "expectancy": round(expectancy, 6),
        "n_eff": round(n_eff, 4),
        "max_drawdown_proxy": round(max_dd, 4),
        "reward_proxy": round(reward_proxy, 6),
        "trade_returns": [round(r, 4) for r in trade_returns],
    }


def _candidate_seed_salt(family_id, params):
    """Compute a stable integer salt from candidate identity.

    Uses SHA-256 of the normalised (family, params) payload — the same
    representation used by ``compute_candidate_signature`` — so that:
    - same candidate always produces the same salt (reproducible)
    - different params produce a different salt (diverse search)
    - result is a positive 32-bit int suitable for seed arithmetic
    """
    norm = {}
    for k in sorted(params.keys()):
        v = params[k]
        if isinstance(v, float):
            norm[k] = round(v, 4)
        elif isinstance(v, int):
            norm[k] = v
        else:
            norm[k] = v
    payload = json.dumps({"family": family_id, "params": norm}, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return int(digest[:8], 16)  # 32-bit positive int


def run_candidate_simulation(candidate, data, folds, config, refit=False):
    """Run a candidate strategy across walk-forward folds.

    When ``refit=True`` (walk-forward mode), each fold's train window is used
    to re-optimise params before evaluating on that fold's OOS window.  This
    is true walk-forward: every fold gets its own trained params, and OOS bars
    never influence the optimiser.

    When ``refit=False`` (legacy mode), a single set of params is used across
    all folds — the caller is responsible for any upstream optimisation.

    The optimizer seed for each fold is:
        ``opt_seed_base + fold_idx + candidate_salt``
    where ``candidate_salt`` is a stable hash of (family, params).
    This ensures different candidates explore different random search
    paths while remaining fully reproducible.

    Args:
        candidate: dict with candidate_id, logic_family_id, params
        data: list of bar dicts (raw or enriched)
        folds: walk-forward fold list from folds.py
        config: pipeline config
        refit: if True, optimise per-fold on each fold's train window

    Returns:
        dict with candidate_id, logic_family_id, status, reject_reason,
        fold_results (list of per-fold metric dicts),
        per_fold_params (list of param dicts, one per fold — only when refit=True),
        optimizer_seeds (list of seeds used, one per fold — only when refit=True)
    """
    min_any_fold = int(config.get("minimum_any_fold_trades", 50))
    n_cap = int(config.get("n_cap", 200))
    features_cfg = config.get("features", {})
    cost_model = config.get("cost_model")
    family_id = candidate.get("logic_family_id", "ema_crossover")
    base_params = candidate.get("params", {})

    opt_n_trials = int(config.get("optimizer_n_trials", 15))
    opt_seed_base = int(config.get("optimizer_seed", 42))
    candidate_salt = _candidate_seed_salt(family_id, base_params)

    fold_results = []
    per_fold_params = []
    optimizer_seeds = []
    reject_reason = None

    # Enrich full data with features once (features only look backward,
    # so computing on the full series doesn't leak forward)
    enriched = compute_features(data, features_cfg)

    for fold_idx, fold in enumerate(folds):
        # --- Per-fold refit on TRAIN window ---
        if refit and not fold.get("invalid_for_selection"):
            train_start = fold["train_start"]
            train_end = fold["train_end"]
            train_bars = enriched[train_start:train_end]

            fold_seed = opt_seed_base + fold_idx + candidate_salt
            opt_result = optimize_params(
                family_id, train_bars, base_params,
                n_trials=opt_n_trials,
                seed=fold_seed,
                cost_per_trade=_cost_per_trade(cost_model),
            )
            fold_params = opt_result["best_params"]
            optimizer_seeds.append(fold_seed)
        else:
            fold_params = dict(base_params)
            optimizer_seeds.append(None)

        per_fold_params.append(fold_params)

        # --- Evaluate on OOS window ---
        test_start = fold["test_start"]
        test_end = fold["test_end"]
        fold_bars = enriched[test_start:test_end]

        if not fold_bars:
            reject_reason = "EMPTY_FOLD"
            break

        # Run strategy on OOS bars with this fold's params
        trade_list = run_strategy(family_id, fold_bars, fold_params)

        if not trade_list:
            reject_reason = "NO_TRADES"
            break

        metrics = _compute_fold_metrics(trade_list, fold["fold_id"], n_cap, cost_model)
        if metrics is None:
            reject_reason = "NO_TRADES"
            break

        # Hard rejection checks
        if metrics["max_drawdown_proxy"] > 1000:
            reject_reason = "DD_BREACH"
            break

        if metrics["trades"] < min_any_fold:
            reject_reason = "ANY_FOLD_TRADES_LT_50"
            break

        fold_results.append(metrics)

    status = "PASS" if not reject_reason else "REJECT"
    result = {
        "candidate_id": candidate.get("candidate_id", "unknown"),
        "logic_family_id": family_id,
        "status": status,
        "reject_reason": reject_reason,
        "fold_results": fold_results,
    }
    if refit:
        result["per_fold_params"] = per_fold_params
        result["optimizer_seeds"] = optimizer_seeds
    return result
