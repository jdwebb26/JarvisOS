import math


def compute_fingerprint(fold_results):
    """Compute a 34-dimensional behavior fingerprint from fold-level trade data.

    Fingerprint dimensions (34 total):
        [0-3]   PF stats: mean, std, min, max across folds
        [4-7]   Sharpe stats: mean, std, min, max
        [8-11]  Sortino stats: mean, std, min, max
        [12-15] Win rate stats: mean, std, min, max
        [16-19] Expectancy stats: mean, std, min, max
        [20-23] Drawdown stats: mean, std, min, max
        [24-27] Trade count stats: mean, std, min, max
        [28]    PF coefficient of variation
        [29]    Sharpe coefficient of variation
        [30]    Avg winner / avg loser ratio (mean across folds)
        [31]    Gross profit share of total absolute PnL
        [32]    Max single-fold drawdown / mean drawdown ratio (tail risk)
        [33]    Fold-to-fold PnL autocorrelation (momentum/mean-reversion signal)

    Args:
        fold_results: list of fold result dicts from simulation

    Returns:
        list of 34 floats
    """
    if not fold_results:
        return [0.0] * 34

    n = len(fold_results)

    def _stats(values):
        if not values:
            return [0.0, 0.0, 0.0, 0.0]
        mean = sum(values) / len(values)
        if len(values) > 1:
            var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
            std = math.sqrt(var)
        else:
            std = 0.0
        return [mean, std, min(values), max(values)]

    def _cv(values):
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        if mean == 0 or len(values) < 2:
            return 0.0
        var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        return math.sqrt(var) / abs(mean)

    pfs = [fr.get("profit_factor", 0.0) for fr in fold_results]
    sharpes = [fr.get("sharpe", 0.0) for fr in fold_results]
    sortinos = [fr.get("sortino", 0.0) for fr in fold_results]
    win_rates = [fr.get("win_rate", 0.0) for fr in fold_results]
    expectancies = [fr.get("expectancy", 0.0) for fr in fold_results]
    dds = [fr.get("max_drawdown_proxy", 0.0) for fr in fold_results]
    trade_counts = [float(fr.get("trades", 0)) for fr in fold_results]
    pnls = [fr.get("pnl", 0.0) for fr in fold_results]

    fp = []
    fp.extend(_stats(pfs))          # 0-3
    fp.extend(_stats(sharpes))      # 4-7
    fp.extend(_stats(sortinos))     # 8-11
    fp.extend(_stats(win_rates))    # 12-15
    fp.extend(_stats(expectancies)) # 16-19
    fp.extend(_stats(dds))          # 20-23
    fp.extend(_stats(trade_counts)) # 24-27

    fp.append(_cv(pfs))             # 28
    fp.append(_cv(sharpes))         # 29

    # Avg winner/loser ratio across folds
    wl_ratios = []
    for fr in fold_results:
        avg_w = fr.get("avg_winner", 0.0)
        avg_l = fr.get("avg_loser", 0.0)
        if avg_l > 0:
            wl_ratios.append(avg_w / avg_l)
        else:
            wl_ratios.append(0.0)
    fp.append(sum(wl_ratios) / len(wl_ratios) if wl_ratios else 0.0)  # 30

    # Gross profit share
    total_gp = sum(fr.get("gross_profit", 0.0) for fr in fold_results)
    total_gl = sum(fr.get("gross_loss", 0.0) for fr in fold_results)
    total_abs = total_gp + total_gl
    fp.append(total_gp / total_abs if total_abs > 0 else 0.5)  # 31

    # Tail risk: max dd / mean dd
    mean_dd = sum(dds) / n if n > 0 else 0.0
    max_dd = max(dds) if dds else 0.0
    fp.append(max_dd / mean_dd if mean_dd > 0 else 0.0)  # 32

    # PnL autocorrelation (lag-1)
    if len(pnls) > 2:
        pnl_mean = sum(pnls) / len(pnls)
        num = sum((pnls[i] - pnl_mean) * (pnls[i + 1] - pnl_mean) for i in range(len(pnls) - 1))
        den = sum((p - pnl_mean) ** 2 for p in pnls)
        fp.append(num / den if den > 0 else 0.0)  # 33
    else:
        fp.append(0.0)  # 33

    return [round(v, 6) for v in fp]
