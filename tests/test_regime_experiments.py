"""Tests for regime experiment layer."""

import json
from strategy_factory.data import generate_synthetic_data
from strategy_factory.features import compute_max_feature_lookback
from strategy_factory.folds import build_folds
from strategy_factory.config import DEFAULT_CONFIG
from strategy_factory.regime_experiments import (
    run_regime_experiment, build_coverage_matrix,
    REGIME_FILTERS, _apply_trade_filter,
)


TEST_FOLD_SPEC = {
    "mode": "rolling",
    "train_len": 400,
    "test_len": 200,
    "purge_len": 50,
    "retrain_cadence": 200,
    "n_folds": 4,
    "minimum_any_fold_trades": 1,
}


def _setup():
    data = generate_synthetic_data(n_bars=2000)
    max_lb = compute_max_feature_lookback(DEFAULT_CONFIG["features"])
    folds = build_folds(len(data), TEST_FOLD_SPEC, max_lb)
    config = dict(DEFAULT_CONFIG)
    config["minimum_any_fold_trades"] = 1
    config["optimizer_n_trials"] = 5
    return data, folds, config


def test_regime_experiment_returns_all_filters():
    data, folds, config = _setup()
    from strategy_factory.config import GATE_PROFILES
    gate_profile = GATE_PROFILES["research_only"]
    candidate = {
        "candidate_id": "test_ema",
        "logic_family_id": "ema_crossover",
        "params": {"atr_stop_mult": 2.0, "atr_tp_mult": 3.0, "min_atr": 0.5},
    }
    result = run_regime_experiment(candidate, data, folds, config, gate_profile)
    assert "filter_results" in result
    for fname in REGIME_FILTERS:
        assert fname in result["filter_results"], f"missing filter: {fname}"
        fr = result["filter_results"][fname]
        assert "folds_evaluated" in fr
        assert "folds_passed" in fr
        assert "avg_pf" in fr
        assert "coverage_pct" in fr
        assert "per_fold" in fr


def test_baseline_matches_no_filter():
    """Baseline filter should keep all trades."""
    data, folds, config = _setup()
    from strategy_factory.config import GATE_PROFILES
    gate_profile = GATE_PROFILES["research_only"]
    candidate = {
        "candidate_id": "test_brk",
        "logic_family_id": "breakout",
        "params": {"lookback": 20, "atr_stop_mult": 1.5,
                   "atr_tp_mult": 3.0, "min_atr": 0.5},
    }
    result = run_regime_experiment(candidate, data, folds, config, gate_profile)
    bl = result["filter_results"]["baseline"]
    assert bl["coverage_pct"] == 100.0
    assert bl["trades_kept"] == bl["trades_total"]


def test_filter_reduces_trades():
    """Non-baseline filters should keep <= baseline trades."""
    data, folds, config = _setup()
    from strategy_factory.config import GATE_PROFILES
    gate_profile = GATE_PROFILES["research_only"]
    candidate = {
        "candidate_id": "test_ema2",
        "logic_family_id": "ema_crossover",
        "params": {"atr_stop_mult": 2.0, "atr_tp_mult": 3.0, "min_atr": 0.1},
    }
    result = run_regime_experiment(candidate, data, folds, config, gate_profile)
    bl_trades = result["filter_results"]["baseline"]["trades_total"]
    for fname, fr in result["filter_results"].items():
        assert fr["trades_kept"] <= bl_trades, (
            f"{fname} kept more trades than baseline")


def test_apply_trade_filter_skips_high_vix():
    bars = [{"vix": 20.0}, {"vix": 35.0}, {"vix": 15.0}]
    trades = [
        {"entry_bar": 0, "pnl": 10},
        {"entry_bar": 1, "pnl": -5},
        {"entry_bar": 2, "pnl": 3},
    ]
    kept, skipped = _apply_trade_filter(
        trades, bars, lambda b: b.get("vix", 20) > 30)
    assert len(kept) == 2
    assert skipped == 1
    assert kept[0]["pnl"] == 10
    assert kept[1]["pnl"] == 3


def test_coverage_matrix():
    """Coverage matrix correctly computes union."""
    experiments = [
        {"candidate_id": "a", "family": "ema",
         "filter_results": {"baseline": {
             "per_fold": [
                 {"gate_overall": "PASS"}, {"gate_overall": "FAIL"},
                 {"gate_overall": "FAIL"}, {"gate_overall": "PASS"},
             ]}}},
        {"candidate_id": "b", "family": "ema",
         "filter_results": {"baseline": {
             "per_fold": [
                 {"gate_overall": "FAIL"}, {"gate_overall": "PASS"},
                 {"gate_overall": "FAIL"}, {"gate_overall": "FAIL"},
             ]}}},
    ]
    cm = build_coverage_matrix(experiments, "baseline")
    assert cm["fold_union"] == [1, 1, 0, 1]
    assert cm["union_count"] == 3
    assert cm["total_folds"] == 4
    assert cm["matrix"][0]["fold_passes"] == [1, 0, 0, 1]
    assert cm["matrix"][1]["fold_passes"] == [0, 1, 0, 0]


def test_deterministic_experiment():
    """Same candidate twice produces identical results."""
    data, folds, config = _setup()
    from strategy_factory.config import GATE_PROFILES
    gate_profile = GATE_PROFILES["research_only"]
    candidate = {
        "candidate_id": "det_test",
        "logic_family_id": "breakout",
        "params": {"lookback": 20, "atr_stop_mult": 1.5,
                   "atr_tp_mult": 3.0, "min_atr": 0.5},
    }
    r1 = run_regime_experiment(candidate, data, folds, config, gate_profile)
    r2 = run_regime_experiment(candidate, data, folds, config, gate_profile)
    for fname in REGIME_FILTERS:
        assert (r1["filter_results"][fname]["avg_pf"]
                == r2["filter_results"][fname]["avg_pf"])
