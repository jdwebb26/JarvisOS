"""Regime-filter experiments for daily research.

Evaluates candidates under various trade-level filters WITHOUT changing
core gates or evidence tiers.  Filters skip individual trades that occur
during filtered-out conditions; the remaining trades are re-evaluated
through the standard gate stack.

This is a research tool only — filters are explicit, opt-in, and all
results are recorded in artifacts for inspection.
"""

import json
import statistics
from pathlib import Path

from .strategies import run_strategy
from .features import compute_features
from .sim import (
    run_candidate_simulation, _compute_fold_metrics, _cost_per_trade,
    _candidate_seed_salt,
)
from .gates import evaluate_fold_gates, evaluate_all_folds
from .optimizer import optimize_params
from .candidate_gen import FAMILY_TIMEFRAME


# ---------------------------------------------------------------------------
# Trade-level regime filters
# ---------------------------------------------------------------------------

def _bar_vix(bar):
    return bar.get("vix", 20.0)


REGIME_FILTERS = {
    "baseline": {
        "description": "No filter — standard evaluation",
        "skip_trade": lambda bar: False,
    },
    "vix_gt_30_skip": {
        "description": "Skip trades entered when VIX > 30",
        "skip_trade": lambda bar: _bar_vix(bar) > 30,
    },
    "vix_gt_25_skip": {
        "description": "Skip trades entered when VIX > 25",
        "skip_trade": lambda bar: _bar_vix(bar) > 25,
    },
    "high_vol_only": {
        "description": "Keep only trades entered when VIX > 25 (inversion test)",
        "skip_trade": lambda bar: _bar_vix(bar) <= 25,
    },
}


def _apply_trade_filter(trade_list, oos_bars, filter_fn):
    """Filter trades by entry-bar condition.

    Returns (kept_trades, skipped_count).
    Trade dicts have ``entry_bar`` = index into the OOS bar slice.
    """
    kept = []
    skipped = 0
    for t in trade_list:
        entry_idx = t.get("entry_bar", 0)
        if entry_idx < len(oos_bars):
            bar = oos_bars[entry_idx]
        else:
            bar = {}
        if filter_fn(bar):
            skipped += 1
        else:
            kept.append(t)
    return kept, skipped


# ---------------------------------------------------------------------------
# Run one candidate through all regime filters on all folds
# ---------------------------------------------------------------------------

def run_regime_experiment(candidate, data, folds, config, gate_profile,
                          filters=None):
    """Evaluate a candidate under multiple regime filters.

    For each filter, re-runs the strategy on each fold's OOS window,
    applies the trade filter, then evaluates gates on the remaining
    trades.  The optimizer refit is done ONCE (baseline) and reused
    across filters — filters only affect OOS trade selection.

    Args:
        candidate: dict with candidate_id, logic_family_id, params
        data: raw bar data (will be enriched)
        folds: fold list from folds.py
        config: pipeline config dict
        gate_profile: gate threshold dict
        filters: dict of filter_name -> filter_spec.
                 Defaults to all REGIME_FILTERS.

    Returns:
        dict with per-filter results, fold coverage, and metadata.
    """
    if filters is None:
        filters = REGIME_FILTERS

    family_id = candidate.get("logic_family_id", "ema_crossover")
    base_params = candidate.get("params", {})
    cid = candidate.get("candidate_id", "unknown")
    features_cfg = config.get("features", {})
    cost_model = config.get("cost_model")
    n_cap = int(config.get("n_cap", 200))
    opt_n_trials = int(config.get("optimizer_n_trials", 15))
    opt_seed_base = int(config.get("optimizer_seed", 42))
    candidate_salt = _candidate_seed_salt(family_id, base_params)
    tf_bucket = FAMILY_TIMEFRAME.get(family_id, config.get("timeframe_bucket",
                                                            "multi_hour_overnight"))
    min_fold_trades = int(config.get("minimum_any_fold_trades", 1))

    enriched = compute_features(data, features_cfg)

    # --- Phase 1: refit per fold (done once, shared across filters) ---
    per_fold_params = []
    for fold_idx, fold in enumerate(folds):
        train_bars = enriched[fold["train_start"]:fold["train_end"]]
        fold_seed = opt_seed_base + fold_idx + candidate_salt
        opt = optimize_params(
            family_id, train_bars, base_params,
            n_trials=opt_n_trials,
            seed=fold_seed,
            cost_per_trade=_cost_per_trade(cost_model),
        )
        per_fold_params.append(opt["best_params"])

    # --- Phase 2: for each filter, run OOS with trade filtering ---
    filter_results = {}
    for fname, fspec in filters.items():
        skip_fn = fspec["skip_trade"]
        fold_details = []

        for fold_idx, fold in enumerate(folds):
            fold_params = per_fold_params[fold_idx]
            test_bars = enriched[fold["test_start"]:fold["test_end"]]

            # Run strategy to get all trades
            trade_list = run_strategy(family_id, test_bars, fold_params)
            if not trade_list:
                fold_details.append({
                    "fold_id": fold["fold_id"],
                    "status": "no_trades",
                    "trades_total": 0, "trades_kept": 0,
                    "trades_skipped": 0, "gate_overall": "FAIL",
                })
                continue

            # Apply filter
            kept, skipped = _apply_trade_filter(trade_list, test_bars, skip_fn)

            if not kept:
                fold_details.append({
                    "fold_id": fold["fold_id"],
                    "status": "all_filtered",
                    "trades_total": len(trade_list), "trades_kept": 0,
                    "trades_skipped": skipped, "gate_overall": "SKIP",
                })
                continue

            # Compute metrics on kept trades
            metrics = _compute_fold_metrics(kept, fold["fold_id"], n_cap,
                                            cost_model)
            if metrics is None or metrics["trades"] < min_fold_trades:
                fold_details.append({
                    "fold_id": fold["fold_id"],
                    "status": "insufficient_trades",
                    "trades_total": len(trade_list), "trades_kept": len(kept),
                    "trades_skipped": skipped, "gate_overall": "SKIP",
                })
                continue

            # Evaluate gates
            gates = evaluate_fold_gates(metrics, tf_bucket,
                                        gate_profile=gate_profile)

            fold_details.append({
                "fold_id": fold["fold_id"],
                "status": "evaluated",
                "trades_total": len(trade_list),
                "trades_kept": len(kept),
                "trades_skipped": skipped,
                "pf": round(metrics["profit_factor"], 4),
                "sharpe": round(metrics["sharpe"], 4),
                "sortino": round(metrics["sortino"], 4),
                "max_dd": round(metrics["max_drawdown_proxy"], 2),
                "gate_overall": gates["overall"],
                "gate_fails": [k for k, v in gates.items()
                               if k != "overall" and isinstance(v, dict)
                               and not v.get("pass")],
            })

        # Summarise this filter
        evaluated = [f for f in fold_details if f["status"] == "evaluated"]
        skipped_folds = [f for f in fold_details
                         if f["status"] in ("all_filtered",
                                            "insufficient_trades")]
        passed = [f for f in evaluated if f["gate_overall"] == "PASS"]
        failed = [f for f in evaluated if f["gate_overall"] == "FAIL"]

        avg_pf = (statistics.mean(f["pf"] for f in evaluated)
                  if evaluated else 0.0)
        avg_sharpe = (statistics.mean(f["sharpe"] for f in evaluated)
                      if evaluated else 0.0)
        avg_sortino = (statistics.mean(f["sortino"] for f in evaluated)
                       if evaluated else 0.0)
        total_trades_kept = sum(f.get("trades_kept", 0) for f in fold_details)
        total_trades_total = sum(f.get("trades_total", 0)
                                 for f in fold_details)

        filter_results[fname] = {
            "description": fspec["description"],
            "folds_evaluated": len(evaluated),
            "folds_skipped": len(skipped_folds),
            "folds_passed": len(passed),
            "folds_failed": len(failed),
            "pass_rate": (f"{len(passed)}/{len(evaluated)}"
                          if evaluated else "0/0"),
            "avg_pf": round(avg_pf, 4),
            "avg_sharpe": round(avg_sharpe, 4),
            "avg_sortino": round(avg_sortino, 4),
            "trades_kept": total_trades_kept,
            "trades_total": total_trades_total,
            "coverage_pct": (round(100 * total_trades_kept / total_trades_total,
                                   1)
                             if total_trades_total > 0 else 0.0),
            "per_fold": fold_details,
        }

    return {
        "candidate_id": cid,
        "family": family_id,
        "params": base_params,
        "filter_results": filter_results,
    }


# ---------------------------------------------------------------------------
# Coverage matrix across multiple candidates
# ---------------------------------------------------------------------------

def build_coverage_matrix(experiment_results, filter_name="baseline"):
    """Build a fold-pass matrix across candidates for a given filter.

    Returns dict with:
        matrix: list of {candidate_id, family, fold_passes: [0/1...]}
        fold_union: [0/1...] — 1 if ANY candidate passes that fold
        union_count: how many folds are covered by at least one candidate
    """
    rows = []
    n_folds = 0
    for er in experiment_results:
        fr = er["filter_results"].get(filter_name, {})
        per_fold = fr.get("per_fold", [])
        n_folds = max(n_folds, len(per_fold))
        passes = [1 if f.get("gate_overall") == "PASS" else 0
                  for f in per_fold]
        rows.append({
            "candidate_id": er["candidate_id"],
            "family": er["family"],
            "fold_passes": passes,
            "total_passes": sum(passes),
        })

    # Union across all candidates
    fold_union = [0] * n_folds
    for row in rows:
        for i, p in enumerate(row["fold_passes"]):
            if p:
                fold_union[i] = 1

    return {
        "filter": filter_name,
        "matrix": rows,
        "fold_union": fold_union,
        "union_count": sum(fold_union),
        "total_folds": n_folds,
    }
