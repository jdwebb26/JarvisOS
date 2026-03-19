"""Tests for strategy mutation experiment layer."""

from strategy_factory.data import generate_synthetic_data
from strategy_factory.features import compute_max_feature_lookback, compute_features
from strategy_factory.folds import build_folds
from strategy_factory.config import DEFAULT_CONFIG, GATE_PROFILES
from strategy_factory.mutation_experiments import (
    run_mutation_experiment, MUTATIONS,
    _ema_with_trend_filter, _ema_with_cooldown,
    _ema_with_max_holding, _breakout_with_trend_alignment,
    _base_ema_crossover, _base_breakout,
)


TEST_FOLD_SPEC = {
    "mode": "rolling", "train_len": 400, "test_len": 200,
    "purge_len": 50, "retrain_cadence": 200, "n_folds": 4,
    "minimum_any_fold_trades": 1,
}


def _setup():
    data = generate_synthetic_data(n_bars=2000)
    max_lb = compute_max_feature_lookback(DEFAULT_CONFIG["features"])
    folds = build_folds(len(data), TEST_FOLD_SPEC, max_lb)
    config = dict(DEFAULT_CONFIG)
    config["minimum_any_fold_trades"] = 1
    config["optimizer_n_trials"] = 3
    gate_profile = GATE_PROFILES["research_only"]
    return data, folds, config, gate_profile


def _enriched_bars(n=500):
    data = generate_synthetic_data(n_bars=n)
    return compute_features(data, DEFAULT_CONFIG["features"])


def test_mutation_experiment_returns_all_relevant():
    data, folds, config, gp = _setup()
    cand = {"candidate_id": "t_ema", "logic_family_id": "ema_crossover",
            "params": {"atr_stop_mult": 2.0, "atr_tp_mult": 3.0,
                       "min_atr": 0.5}}
    result = run_mutation_experiment(cand, data, folds, config, gp)
    assert "mutation_results" in result
    # Should have all ema mutations (baseline + variants)
    ema_mutations = {k for k, v in MUTATIONS.items()
                     if v["family"] == "ema_crossover"}
    for m in ema_mutations:
        assert m in result["mutation_results"], f"missing mutation: {m}"


def test_mutation_experiment_breakout():
    data, folds, config, gp = _setup()
    cand = {"candidate_id": "t_brk", "logic_family_id": "breakout",
            "params": {"lookback": 20, "atr_stop_mult": 1.5,
                       "atr_tp_mult": 3.0, "min_atr": 0.5}}
    result = run_mutation_experiment(cand, data, folds, config, gp)
    brk_mutations = {k for k, v in MUTATIONS.items()
                     if v["family"] == "breakout"}
    for m in brk_mutations:
        assert m in result["mutation_results"]


def test_mutation_result_schema():
    data, folds, config, gp = _setup()
    cand = {"candidate_id": "t_ema", "logic_family_id": "ema_crossover",
            "params": {"atr_stop_mult": 2.0, "atr_tp_mult": 3.0,
                       "min_atr": 0.5}}
    result = run_mutation_experiment(cand, data, folds, config, gp)
    for mname, mr in result["mutation_results"].items():
        assert "description" in mr
        assert "folds_passed" in mr
        assert "pass_rate" in mr
        assert "avg_pf" in mr
        assert "per_fold" in mr
        assert len(mr["per_fold"]) == len(folds)
        for f in mr["per_fold"]:
            assert "fold_id" in f
            assert "trades" in f
            assert "gate_overall" in f


def test_mutation_deterministic():
    data, folds, config, gp = _setup()
    cand = {"candidate_id": "det", "logic_family_id": "ema_crossover",
            "params": {"atr_stop_mult": 2.0, "atr_tp_mult": 3.0,
                       "min_atr": 0.5}}
    r1 = run_mutation_experiment(cand, data, folds, config, gp)
    r2 = run_mutation_experiment(cand, data, folds, config, gp)
    for mname in r1["mutation_results"]:
        assert (r1["mutation_results"][mname]["avg_pf"]
                == r2["mutation_results"][mname]["avg_pf"])


def test_baseline_matches_base_strategy():
    """Baseline mutation should produce same trades as registered strategy."""
    bars = _enriched_bars()
    params = {"atr_stop_mult": 2.0, "atr_tp_mult": 3.0, "min_atr": 0.5}
    base = _base_ema_crossover(bars, params)
    # Baseline mutation IS the registered strategy
    from strategy_factory.strategies import run_strategy
    direct = run_strategy("ema_crossover", bars, params)
    assert len(base) == len(direct)
    for a, b in zip(base, direct):
        assert a["pnl"] == b["pnl"]


def test_trend_filter_reduces_or_equals_trades():
    """Trend filter should produce <= trades than baseline."""
    bars = _enriched_bars(1000)
    params = {"atr_stop_mult": 2.0, "atr_tp_mult": 3.0, "min_atr": 0.3,
              "trend_lookback": 5}
    base = _base_ema_crossover(bars, params)
    filtered = _ema_with_trend_filter(bars, params)
    assert len(filtered) <= len(base)


def test_cooldown_reduces_or_equals_trades():
    bars = _enriched_bars(1000)
    params = {"atr_stop_mult": 2.0, "atr_tp_mult": 3.0, "min_atr": 0.3,
              "cooldown_bars": 10}
    base = _base_ema_crossover(bars, params)
    cd = _ema_with_cooldown(bars, params)
    assert len(cd) <= len(base)


def test_max_holding_produces_trades():
    bars = _enriched_bars(1000)
    params = {"atr_stop_mult": 2.0, "atr_tp_mult": 3.0, "min_atr": 0.3,
              "max_hold_bars": 15}
    trades = _ema_with_max_holding(bars, params)
    # Should produce at least as many trades as baseline (time exit adds exits)
    base = _base_ema_crossover(bars, params)
    assert len(trades) >= len(base)


def test_breakout_trend_aligned_reduces_or_equals():
    bars = _enriched_bars(1000)
    params = {"lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0,
              "min_atr": 0.3, "trend_lookback": 5}
    base = _base_breakout(bars, params)
    aligned = _breakout_with_trend_alignment(bars, params)
    assert len(aligned) <= len(base)
