"""Selector / ensemble experiments for daily research.

Tests whether variant complementarity can be converted into honest,
non-leaky improvement over individual candidates.

ANTI-LEAKAGE RULES:
- No experiment may use a fold's OOS result to choose the strategy for
  that same fold.
- Train-window metrics (reward, PF, trade count) are legitimate signals.
- Pre-OOS observables (trailing VIX, recent volatility) are legitimate.
- Everything else requires explicit justification.

This is a research tool only — no production behavior changes.
"""

import json
import statistics
from pathlib import Path

from .strategies import run_strategy
from .features import compute_features
from .sim import (
    _compute_fold_metrics, _cost_per_trade, _candidate_seed_salt,
)
from .gates import evaluate_fold_gates
from .optimizer import optimize_params, _evaluate_on_bars
from .candidate_gen import FAMILY_TIMEFRAME


# ---------------------------------------------------------------------------
# Shared: refit + collect train signals for all candidates on all folds
# ---------------------------------------------------------------------------

def _prepare_candidates(candidates, data, folds, config):
    """Refit all candidates and collect train-window signals.

    Returns list of dicts, one per candidate, each with:
        candidate_id, family, params, per_fold: [{
            fold_id, refitted_params, train_reward, train_pf,
            train_trades, recent_vix_20,
        }]
    """
    features_cfg = config.get("features", {})
    cost_model = config.get("cost_model")
    cost = _cost_per_trade(cost_model)
    opt_n_trials = int(config.get("optimizer_n_trials", 15))
    opt_seed_base = int(config.get("optimizer_seed", 42))

    enriched = compute_features(data, features_cfg)

    prepared = []
    for cand in candidates:
        fam = cand["logic_family_id"]
        params = cand["params"]
        cid = cand["candidate_id"]
        salt = _candidate_seed_salt(fam, params)

        fold_info = []
        for fi, fold in enumerate(folds):
            train_bars = enriched[fold["train_start"]:fold["train_end"]]
            fold_seed = opt_seed_base + fi + salt

            opt = optimize_params(
                fam, train_bars, params,
                n_trials=opt_n_trials, seed=fold_seed,
                cost_per_trade=cost,
            )
            refitted = opt["best_params"]

            # Train-window evaluation (legitimate for selection)
            train_eval = _evaluate_on_bars(fam, train_bars, refitted, cost)
            train_pf = train_eval["profit_factor"] if train_eval else 0.0
            train_reward = opt["best_reward"]
            train_trades = train_eval["trades"] if train_eval else 0

            # Recent VIX (last 20 train bars — observable before OOS)
            vix_vals = [b.get("vix", 20.0) for b in
                        data[max(0, fold["train_end"] - 20):fold["train_end"]]]
            recent_vix = statistics.mean(vix_vals) if vix_vals else 20.0

            fold_info.append({
                "fold_id": fold["fold_id"],
                "refitted_params": refitted,
                "train_reward": round(train_reward, 2),
                "train_pf": round(train_pf, 4),
                "train_trades": train_trades,
                "recent_vix_20": round(recent_vix, 1),
            })

        prepared.append({
            "candidate_id": cid,
            "family": fam,
            "params": params,
            "per_fold": fold_info,
        })

    return prepared, enriched


# ---------------------------------------------------------------------------
# Evaluate a chosen candidate on a fold's OOS window
# ---------------------------------------------------------------------------

def _evaluate_oos(family, refitted_params, enriched, fold, config,
                  gate_profile):
    """Run strategy on OOS bars and evaluate gates.

    Returns dict with trades, pf, sharpe, sortino, gate_overall, etc.
    """
    n_cap = int(config.get("n_cap", 200))
    cost_model = config.get("cost_model")
    tf_bucket = FAMILY_TIMEFRAME.get(family,
                                      config.get("timeframe_bucket",
                                                  "multi_hour_overnight"))

    test_bars = enriched[fold["test_start"]:fold["test_end"]]
    trade_list = run_strategy(family, test_bars, refitted_params)

    if not trade_list:
        return {"status": "no_trades", "trades": 0, "gate_overall": "FAIL"}

    metrics = _compute_fold_metrics(trade_list, fold["fold_id"], n_cap,
                                    cost_model)
    if metrics is None:
        return {"status": "no_trades", "trades": 0, "gate_overall": "FAIL"}

    gates = evaluate_fold_gates(metrics, tf_bucket, gate_profile=gate_profile)

    return {
        "status": "evaluated",
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
    }


# ---------------------------------------------------------------------------
# Experiment A: Static top-k basket
# ---------------------------------------------------------------------------

def experiment_static_basket(prepared, enriched, folds, config, gate_profile,
                             basket_ids, name="static_basket"):
    """Evaluate a fixed basket of candidates.

    For each fold, ALL basket candidates are evaluated on OOS.  The fold
    is marked PASS if ANY basket member passes gates.

    Mechanics:
    - No selection logic — all basket members always run.
    - If multiple pass, the best PF is reported (but all are recorded).
    - Trade overlap is NOT resolved — this is a coverage experiment,
      not an executable portfolio simulation.

    Anti-leakage: basket composition is fixed before seeing any OOS data.
    """
    basket = [p for p in prepared if p["candidate_id"] in basket_ids]
    if not basket:
        return {"error": "no matching candidates"}

    fold_results = []
    for fi, fold in enumerate(folds):
        member_results = []
        for cand in basket:
            finfo = cand["per_fold"][fi]
            oos = _evaluate_oos(cand["family"], finfo["refitted_params"],
                                enriched, fold, config, gate_profile)
            member_results.append({
                "candidate_id": cand["candidate_id"],
                "family": cand["family"],
                **oos,
            })

        any_pass = any(m["gate_overall"] == "PASS" for m in member_results)
        best_pass = None
        if any_pass:
            passers = [m for m in member_results
                       if m["gate_overall"] == "PASS"]
            best_pass = max(passers, key=lambda m: m.get("pf", 0))

        fold_results.append({
            "fold_id": fold["fold_id"],
            "any_pass": any_pass,
            "members_evaluated": len(member_results),
            "members_passed": sum(1 for m in member_results
                                  if m["gate_overall"] == "PASS"),
            "best_passer": (best_pass["candidate_id"]
                            if best_pass else None),
            "best_pf": best_pass.get("pf") if best_pass else None,
            "member_detail": member_results,
        })

    n_pass = sum(1 for f in fold_results if f["any_pass"])

    return {
        "experiment": name,
        "type": "static_basket",
        "basket": basket_ids,
        "basket_size": len(basket_ids),
        "anti_leakage": "basket fixed before OOS; all members run on every fold",
        "overlap_handling": "none — trades may overlap; this is coverage research, not portfolio sim",
        "folds_any_pass": n_pass,
        "folds_total": len(folds),
        "pass_rate": f"{n_pass}/{len(folds)}",
        "per_fold": fold_results,
    }


# ---------------------------------------------------------------------------
# Experiment B: Train-window selector
# ---------------------------------------------------------------------------

def experiment_train_selector(prepared, enriched, folds, config, gate_profile,
                              selector_fn, name="train_selector"):
    """Select ONE candidate per fold using only train-window signals.

    For each fold, ``selector_fn(fold_signals)`` returns the candidate_id
    to deploy.  ``fold_signals`` is a list of dicts, one per candidate:
        {candidate_id, family, train_reward, train_pf, train_trades,
         recent_vix_20}

    Only the selected candidate is evaluated on OOS.

    Anti-leakage: selector_fn receives only train-period data.
    """
    fold_results = []
    for fi, fold in enumerate(folds):
        # Build signal list for this fold (train-window only)
        signals = []
        for cand in prepared:
            finfo = cand["per_fold"][fi]
            signals.append({
                "candidate_id": cand["candidate_id"],
                "family": cand["family"],
                "train_reward": finfo["train_reward"],
                "train_pf": finfo["train_pf"],
                "train_trades": finfo["train_trades"],
                "recent_vix_20": finfo["recent_vix_20"],
            })

        # Select
        chosen_id = selector_fn(signals)
        chosen = next((p for p in prepared
                       if p["candidate_id"] == chosen_id), None)
        if not chosen:
            fold_results.append({
                "fold_id": fold["fold_id"],
                "chosen": None,
                "status": "no_selection",
                "gate_overall": "FAIL",
            })
            continue

        finfo = chosen["per_fold"][fi]
        oos = _evaluate_oos(chosen["family"], finfo["refitted_params"],
                            enriched, fold, config, gate_profile)

        fold_results.append({
            "fold_id": fold["fold_id"],
            "chosen": chosen_id,
            "chosen_family": chosen["family"],
            "selection_reason": {
                "train_reward": finfo["train_reward"],
                "train_pf": finfo["train_pf"],
                "train_trades": finfo["train_trades"],
            },
            **oos,
        })

    n_pass = sum(1 for f in fold_results
                 if f.get("gate_overall") == "PASS")

    return {
        "experiment": name,
        "type": "train_selector",
        "candidates_eligible": [p["candidate_id"] for p in prepared],
        "anti_leakage": "selector sees only train-window metrics; OOS not available at selection time",
        "selection_method": name,
        "folds_passed": n_pass,
        "folds_total": len(folds),
        "pass_rate": f"{n_pass}/{len(folds)}",
        "per_fold": fold_results,
    }


# ---------------------------------------------------------------------------
# Built-in selector functions
# ---------------------------------------------------------------------------

def select_by_train_reward(signals):
    """Pick the candidate with highest train-window reward."""
    return max(signals, key=lambda s: s["train_reward"])["candidate_id"]


def select_by_train_pf(signals):
    """Pick the candidate with highest train-window profit factor."""
    return max(signals, key=lambda s: s["train_pf"])["candidate_id"]


def select_by_train_trades(signals):
    """Pick the candidate with most train trades (liquidity proxy)."""
    return max(signals, key=lambda s: s["train_trades"])["candidate_id"]


def select_breakout_if_high_vix(signals, vix_threshold=25.0):
    """Pick breakout if recent VIX > threshold, else best ema by reward.

    Rationale: breakout may handle volatile markets better due to
    wider channel entries.
    """
    recent_vix = signals[0]["recent_vix_20"] if signals else 20.0
    if recent_vix > vix_threshold:
        brk = [s for s in signals if s["family"] == "breakout"]
        if brk:
            return max(brk, key=lambda s: s["train_reward"])["candidate_id"]
    ema = [s for s in signals if s["family"] == "ema_crossover"]
    if ema:
        return max(ema, key=lambda s: s["train_reward"])["candidate_id"]
    return max(signals, key=lambda s: s["train_reward"])["candidate_id"]


# ---------------------------------------------------------------------------
# Run all experiments
# ---------------------------------------------------------------------------

def run_all_selector_experiments(candidates, data, folds, config,
                                gate_profile):
    """Run the standard suite of selector experiments.

    Args:
        candidates: list of candidate dicts (candidate_id, logic_family_id,
                    params)
        data: raw bar data
        folds: fold list
        config: pipeline config
        gate_profile: gate threshold dict

    Returns:
        dict with prepared data, experiment results, and coverage summary.
    """
    prepared, enriched = _prepare_candidates(candidates, data, folds, config)

    results = {}

    # --- Individual baselines ---
    for cand in prepared:
        cid = cand["candidate_id"]
        r = experiment_static_basket(
            prepared, enriched, folds, config, gate_profile,
            basket_ids=[cid],
            name=f"individual_{cid}",
        )
        results[f"individual_{cid}"] = r

    # --- Static baskets ---
    all_ids = [p["candidate_id"] for p in prepared]
    ema_ids = [p["candidate_id"] for p in prepared
               if p["family"] == "ema_crossover"]
    brk_ids = [p["candidate_id"] for p in prepared
               if p["family"] == "breakout"]

    # Top-2 ema
    if len(ema_ids) >= 2:
        results["basket_top2_ema"] = experiment_static_basket(
            prepared, enriched, folds, config, gate_profile,
            basket_ids=ema_ids[:2], name="basket_top2_ema")

    # Top-3 ema
    if len(ema_ids) >= 3:
        results["basket_top3_ema"] = experiment_static_basket(
            prepared, enriched, folds, config, gate_profile,
            basket_ids=ema_ids[:3], name="basket_top3_ema")

    # Top ema + top breakout
    if ema_ids and brk_ids:
        results["basket_ema1_brk1"] = experiment_static_basket(
            prepared, enriched, folds, config, gate_profile,
            basket_ids=[ema_ids[0], brk_ids[0]],
            name="basket_ema1_brk1")

    # All candidates
    results["basket_all"] = experiment_static_basket(
        prepared, enriched, folds, config, gate_profile,
        basket_ids=all_ids, name="basket_all")

    # --- Train-window selectors ---
    results["selector_train_reward"] = experiment_train_selector(
        prepared, enriched, folds, config, gate_profile,
        selector_fn=select_by_train_reward,
        name="selector_train_reward")

    results["selector_train_pf"] = experiment_train_selector(
        prepared, enriched, folds, config, gate_profile,
        selector_fn=select_by_train_pf,
        name="selector_train_pf")

    results["selector_train_trades"] = experiment_train_selector(
        prepared, enriched, folds, config, gate_profile,
        selector_fn=select_by_train_trades,
        name="selector_train_trades")

    # --- Regime-conditioned selector ---
    results["selector_vix_family"] = experiment_train_selector(
        prepared, enriched, folds, config, gate_profile,
        selector_fn=lambda s: select_breakout_if_high_vix(s, 25.0),
        name="selector_vix_family")

    return {
        "candidates": [{
            "candidate_id": p["candidate_id"],
            "family": p["family"],
        } for p in prepared],
        "experiments": results,
    }
