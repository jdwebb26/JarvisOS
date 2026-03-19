from .config import TIMEFRAME_GATES, GATE_PROFILES


def evaluate_fold_gates(metrics, timeframe_bucket="5_60m_intraday",
                        gate_profile=None):
    """Evaluate a single fold's metrics against gates.

    When gate_profile is provided (from GATE_PROFILES), it overrides the
    timeframe_bucket thresholds for min_trades, sharpe_floor, sortino_floor,
    and max_drawdown.  This ensures daily-research data uses daily-appropriate
    thresholds instead of intraday execution-grade thresholds.
    """
    g = TIMEFRAME_GATES[timeframe_bucket]
    results = {}

    # min_trades: use gate_profile if provided, else timeframe gate
    min_trades_threshold = (gate_profile["min_trades_per_oos_fold"]
                            if gate_profile else g["min_trades_per_oos_fold"])
    results["min_trades_per_oos_fold"] = {
        "value": metrics["trades"],
        "threshold": min_trades_threshold,
        "pass": metrics["trades"] >= min_trades_threshold,
    }

    # max_drawdown: use gate_profile if provided
    dd_threshold = (gate_profile["max_drawdown_proxy"]
                    if gate_profile else 1000.0)
    results["max_drawdown_proxy"] = {
        "value": metrics.get("max_drawdown_proxy", 0.0),
        "threshold": dd_threshold,
        "pass": metrics.get("max_drawdown_proxy", 0.0) <= dd_threshold,
    }

    # profit_factor: use gate_profile if provided, else timeframe gate
    pf = metrics.get("profit_factor", 0.0)
    pf_threshold = (gate_profile["pf_floor"]
                    if gate_profile else g["pf_after_costs_2x_slippage"])
    results["profit_factor"] = {
        "value": pf,
        "threshold": pf_threshold,
        "pass": pf >= pf_threshold,
    }

    # sharpe: use gate_profile if provided
    sharpe = metrics.get("sharpe", 0.0)
    sharpe_threshold = (gate_profile["sharpe_floor"]
                        if gate_profile else g["sharpe_floor"])
    results["sharpe"] = {
        "value": sharpe,
        "threshold": sharpe_threshold,
        "pass": sharpe >= sharpe_threshold,
    }

    # sortino: use gate_profile if provided
    sortino = metrics.get("sortino", 0.0)
    sortino_threshold = (gate_profile["sortino_floor"]
                         if gate_profile else g["sortino_floor"])
    results["sortino"] = {
        "value": sortino,
        "threshold": sortino_threshold,
        "pass": sortino >= sortino_threshold,
    }

    results["overall"] = "PASS" if all(
        v["pass"] for k, v in results.items() if k != "overall"
    ) else "FAIL"
    return results


def evaluate_all_folds(fold_results, timeframe_bucket="5_60m_intraday",
                       gate_profile=None):
    """Evaluate gates on every fold and produce an aggregate summary.

    Returns:
        dict with per_fold (list of gate results), aggregate (overall verdict),
        and gate_profile_used.
        A candidate passes only if ALL folds pass ALL gates.
    """
    per_fold = []
    all_pass = True

    for fr in fold_results:
        fold_gates = evaluate_fold_gates(fr, timeframe_bucket,
                                         gate_profile=gate_profile)
        per_fold.append({
            "fold_id": fr["fold_id"],
            "gates": fold_gates,
        })
        if fold_gates["overall"] != "PASS":
            all_pass = False

    # Aggregate cross-fold metrics
    n = len(fold_results)
    if n > 0:
        avg_pf = sum(fr.get("profit_factor", 0.0) for fr in fold_results) / n
        avg_sharpe = sum(fr.get("sharpe", 0.0) for fr in fold_results) / n
        avg_sortino = sum(fr.get("sortino", 0.0) for fr in fold_results) / n
        min_pf = min(fr.get("profit_factor", 0.0) for fr in fold_results)
        max_dd = max(fr.get("max_drawdown_proxy", 0.0) for fr in fold_results)
        pf_values = [fr.get("profit_factor", 0.0) for fr in fold_results]
        pf_mean = avg_pf
        pf_variance = sum((v - pf_mean) ** 2 for v in pf_values) / max(1, n - 1) if n > 1 else 0.0
    else:
        avg_pf = avg_sharpe = avg_sortino = min_pf = max_dd = pf_variance = 0.0

    aggregate = {
        "folds_evaluated": n,
        "folds_passed": sum(1 for pf in per_fold if pf["gates"]["overall"] == "PASS"),
        "folds_failed": sum(1 for pf in per_fold if pf["gates"]["overall"] != "PASS"),
        "avg_profit_factor": round(avg_pf, 4),
        "min_profit_factor": round(min_pf, 4),
        "avg_sharpe": round(avg_sharpe, 4),
        "avg_sortino": round(avg_sortino, 4),
        "max_drawdown_proxy": round(max_dd, 4),
        "pf_variance": round(pf_variance, 6),
        "overall": "PASS" if all_pass and n > 0 else "FAIL",
    }

    return {
        "per_fold": per_fold,
        "aggregate": aggregate,
    }


def hard_gate_summary():
    return {
        "status": "implemented_phase_3",
        "gates": ["min_trades", "max_drawdown", "profit_factor", "sharpe", "sortino"],
        "note": "All folds evaluated with PF/Sharpe/Sortino gates.",
    }
