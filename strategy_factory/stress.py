from .regimes import label_regime, regime_gate
from .config import REGIMES
from .features import compute_features
from .strategies import run_strategy


def stress_check(candidate, data, folds, config, sim_fn):
    """Run regime-based stress test.

    Runs the real strategy on OOS bars, labels each trade by the VIX regime
    at its entry bar, then checks per-regime PF gates.

    Args:
        candidate: candidate dict with logic_family_id and params
        data: OHLCV + VIX rows
        folds: walk-forward folds
        config: pipeline config
        sim_fn: simulation function (used for baseline pass/fail check)

    Returns:
        dict with per-regime results and overall pass/fail.
    """
    # Run baseline simulation to check pass/fail
    result = sim_fn(candidate, data, folds, config)
    if result["status"] != "PASS" or not result["fold_results"]:
        return {
            "status": "SKIP",
            "reason": f"Baseline {result['status']}: {result.get('reject_reason')}",
            "overall": "FAIL",
            "regimes": {},
        }

    features_cfg = config.get("features", {})
    enriched = compute_features(data, features_cfg)
    family_id = candidate.get("logic_family_id", "ema_crossover")
    params = candidate.get("params", {})

    # Run strategy on each fold's OOS bars and tag trades by regime
    regime_trades = {"low_vol": [], "mid_vol": [], "high_vol": []}

    for fold in folds:
        test_start = fold["test_start"]
        test_end = fold["test_end"]
        fold_bars = enriched[test_start:test_end]

        trade_list = run_strategy(family_id, fold_bars, params)

        for t in trade_list:
            entry_idx = t["entry_bar"]
            if 0 <= entry_idx < len(fold_bars):
                vix = fold_bars[entry_idx].get("vix", 20.0)
            else:
                vix = 20.0
            regime = label_regime(vix)
            regime_trades[regime].append(t["pnl"])

    # Compute per-regime metrics
    regime_results = {}
    all_pass = True
    total_equity = sum(fr["pnl"] for fr in result["fold_results"])

    for regime_name, pnl_list in regime_trades.items():
        n_trades = len(pnl_list)
        if n_trades == 0:
            regime_results[regime_name] = {
                "trades": 0,
                "pnl": 0.0,
                "profit_factor": None,
                "gate_pass": True,
                "note": "No trades in regime",
            }
            continue

        gross_profit = sum(p for p in pnl_list if p > 0)
        gross_loss = sum(abs(p) for p in pnl_list if p <= 0)
        total_pnl = sum(pnl_list)
        pf = (gross_profit / gross_loss) if gross_loss > 0 else 999.0

        pf_threshold = REGIMES[regime_name]["pf_gate"]
        fold_equity = max(abs(total_equity), 1.0)
        gate_pass = regime_gate(n_trades, pf, total_pnl, fold_equity, pf_threshold)

        if not gate_pass:
            all_pass = False

        regime_results[regime_name] = {
            "trades": n_trades,
            "pnl": round(total_pnl, 4),
            "gross_profit": round(gross_profit, 4),
            "gross_loss": round(gross_loss, 4),
            "profit_factor": round(pf, 4) if pf != 999.0 else 999.0,
            "pf_threshold": pf_threshold,
            "gate_pass": gate_pass,
        }

    return {
        "status": "COMPLETE",
        "overall": "PASS" if all_pass else "FAIL",
        "regimes": regime_results,
    }
