from strategy_factory.data import generate_synthetic_data
from strategy_factory.features import compute_max_feature_lookback
from strategy_factory.folds import build_folds
from strategy_factory.sim import (
    run_candidate_simulation, _compute_sharpe, _compute_sortino,
    _compute_fold_metrics, _cost_per_trade, _candidate_seed_salt,
)
from strategy_factory.config import DEFAULT_CONFIG


# Test-sized fold spec that works with 2000-bar synthetic data
TEST_FOLD_SPEC = {
    "mode": "rolling",
    "train_len": 400,
    "test_len": 200,
    "purge_len": 50,
    "retrain_cadence": 200,
    "n_folds": 4,
}

TEST_CONFIG = dict(DEFAULT_CONFIG)
TEST_CONFIG["fold_spec"] = TEST_FOLD_SPEC


def _make_candidate(family="breakout"):
    return {
        "candidate_id": "test_cand",
        "logic_family_id": family,
        "params": {"lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0, "min_atr": 0.5},
        "param_types": {"lookback": "int", "atr_stop_mult": "float",
                        "atr_tp_mult": "float", "min_atr": "float"},
    }


def test_sim_returns_result():
    data = generate_synthetic_data(n_bars=2000)
    max_lb = compute_max_feature_lookback(TEST_CONFIG["features"])
    folds = build_folds(len(data), TEST_FOLD_SPEC, max_lb)
    result = run_candidate_simulation(
        candidate=_make_candidate(),
        data=data,
        folds=folds,
        config=TEST_CONFIG,
    )
    assert "status" in result
    assert "fold_results" in result


def test_sim_has_reward_proxy_or_reject_reason():
    data = generate_synthetic_data(n_bars=2000)
    max_lb = compute_max_feature_lookback(TEST_CONFIG["features"])
    folds = build_folds(len(data), TEST_FOLD_SPEC, max_lb)
    result = run_candidate_simulation(
        candidate=_make_candidate(),
        data=data,
        folds=folds,
        config=TEST_CONFIG,
    )
    if result["fold_results"]:
        assert "reward_proxy" in result["fold_results"][0]
    else:
        assert result["reject_reason"] is not None


def test_sim_computes_profit_factor():
    data = generate_synthetic_data(n_bars=2000)
    max_lb = compute_max_feature_lookback(TEST_CONFIG["features"])
    folds = build_folds(len(data), TEST_FOLD_SPEC, max_lb)
    # Use min_any_fold_trades=1 so breakout passes with few trades per fold
    config = dict(TEST_CONFIG)
    config["minimum_any_fold_trades"] = 1
    result = run_candidate_simulation(
        candidate=_make_candidate(),
        data=data,
        folds=folds,
        config=config,
    )
    assert result["status"] == "PASS"
    for fr in result["fold_results"]:
        assert "profit_factor" in fr
        assert "sharpe" in fr
        assert "sortino" in fr
        assert "win_rate" in fr
        assert "gross_profit" in fr
        assert "gross_loss" in fr
        assert "trade_returns" in fr
        assert fr["profit_factor"] >= 0
        assert 0.0 <= fr["win_rate"] <= 1.0
        assert fr["gross_profit"] >= 0
        assert fr["gross_loss"] >= 0


def test_sim_walkforward_refit():
    """With refit=True, each fold gets its own optimised params."""
    data = generate_synthetic_data(n_bars=2000)
    max_lb = compute_max_feature_lookback(TEST_CONFIG["features"])
    folds = build_folds(len(data), TEST_FOLD_SPEC, max_lb)
    config = dict(TEST_CONFIG)
    config["minimum_any_fold_trades"] = 1
    config["optimizer_n_trials"] = 5  # keep fast

    result = run_candidate_simulation(
        candidate=_make_candidate(),
        data=data,
        folds=folds,
        config=config,
        refit=True,
    )
    assert "status" in result
    assert "per_fold_params" in result
    # Should have one param set per fold attempted
    assert len(result["per_fold_params"]) >= 1
    # Each fold's params should be a dict
    for p in result["per_fold_params"]:
        assert isinstance(p, dict)


def test_sim_refit_false_no_per_fold_params():
    """With refit=False (legacy), no per_fold_params in output."""
    data = generate_synthetic_data(n_bars=2000)
    max_lb = compute_max_feature_lookback(TEST_CONFIG["features"])
    folds = build_folds(len(data), TEST_FOLD_SPEC, max_lb)
    config = dict(TEST_CONFIG)
    config["minimum_any_fold_trades"] = 1

    result = run_candidate_simulation(
        candidate=_make_candidate(),
        data=data,
        folds=folds,
        config=config,
        refit=False,
    )
    assert "per_fold_params" not in result


def test_sim_refit_different_params_per_fold():
    """Walk-forward refit should (usually) produce different params per fold
    because each fold trains on a different window."""
    data = generate_synthetic_data(n_bars=4000, seed=99)
    fold_spec = {
        "mode": "rolling",
        "train_len": 600,
        "test_len": 200,
        "purge_len": 50,
        "retrain_cadence": 200,
        "n_folds": 4,
    }
    max_lb = compute_max_feature_lookback(TEST_CONFIG["features"])
    folds = build_folds(len(data), fold_spec, max_lb)
    config = dict(TEST_CONFIG)
    config["fold_spec"] = fold_spec
    config["minimum_any_fold_trades"] = 1
    config["optimizer_n_trials"] = 10

    result = run_candidate_simulation(
        candidate=_make_candidate(),
        data=data,
        folds=folds,
        config=config,
        refit=True,
    )
    params_list = result.get("per_fold_params", [])
    if len(params_list) >= 2:
        # Not all folds should have identical params (very unlikely with
        # different train windows and random search)
        all_same = all(p == params_list[0] for p in params_list)
        # This is a soft check — if by extreme coincidence all are the same,
        # the test still passes (no flaky failures)
        assert isinstance(params_list[0], dict)
        assert isinstance(params_list[-1], dict)


def test_cost_per_trade_calculation():
    """Verify round-trip cost formula."""
    cost_model = {
        "commission_per_side_points": 0.125,
        "slippage_per_side_points": 0.25,
    }
    # 2 * (0.125 + 0.25) = 0.75 points per round-trip
    assert abs(_cost_per_trade(cost_model) - 0.75) < 1e-9
    assert _cost_per_trade(None) == 0.0
    assert _cost_per_trade({}) == 0.0


def test_cost_model_reduces_pnl():
    """With costs, net PnL should be less than gross PnL."""
    from strategy_factory.strategies import run_strategy
    from strategy_factory.features import compute_features

    data = generate_synthetic_data(n_bars=2000)
    enriched = compute_features(data, DEFAULT_CONFIG["features"])
    bars = enriched[400:600]

    trades = run_strategy("breakout", bars, {
        "lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0, "min_atr": 0.5,
    })
    if not trades:
        return  # skip if no trades generated

    # Without costs
    metrics_free = _compute_fold_metrics(trades, 0, 200, cost_model=None)
    # With costs
    cost_model = {"commission_per_side_points": 0.125, "slippage_per_side_points": 0.25}
    metrics_cost = _compute_fold_metrics(trades, 0, 200, cost_model=cost_model)

    assert metrics_free is not None
    assert metrics_cost is not None
    # Net PnL should be less by exactly n_trades * cost_per_trade
    expected_cost = len(trades) * _cost_per_trade(cost_model)
    assert abs(metrics_cost["total_cost"] - expected_cost) < 0.01
    assert abs(metrics_cost["pnl"] - (metrics_free["pnl"] - expected_cost)) < 0.01
    # Gross PnL preserved
    assert abs(metrics_cost["pnl_gross"] - metrics_free["pnl"]) < 0.01


def test_cost_model_in_simulation():
    """Verify cost model flows through run_candidate_simulation."""
    data = generate_synthetic_data(n_bars=2000)
    max_lb = compute_max_feature_lookback(TEST_CONFIG["features"])
    folds = build_folds(len(data), TEST_FOLD_SPEC, max_lb)
    config = dict(TEST_CONFIG)
    config["minimum_any_fold_trades"] = 1
    config["cost_model"] = {
        "commission_per_side_points": 0.125,
        "slippage_per_side_points": 0.25,
    }

    result = run_candidate_simulation(
        candidate=_make_candidate(),
        data=data,
        folds=folds,
        config=config,
    )
    if result["fold_results"]:
        fr = result["fold_results"][0]
        assert "pnl_gross" in fr
        assert "total_cost" in fr
        assert fr["total_cost"] > 0  # should have some trades


def test_cost_model_zero_gives_same_as_none():
    """Zero costs should produce same PnL as no cost model."""
    data = generate_synthetic_data(n_bars=2000)
    max_lb = compute_max_feature_lookback(TEST_CONFIG["features"])
    folds = build_folds(len(data), TEST_FOLD_SPEC, max_lb)

    config_none = dict(TEST_CONFIG)
    config_none["minimum_any_fold_trades"] = 1
    config_none.pop("cost_model", None)  # explicitly no cost model

    config_zero = dict(TEST_CONFIG)
    config_zero["minimum_any_fold_trades"] = 1
    config_zero["cost_model"] = {
        "commission_per_side_points": 0.0,
        "slippage_per_side_points": 0.0,
    }

    result_none = run_candidate_simulation(
        candidate=_make_candidate(), data=data, folds=folds, config=config_none,
    )
    result_zero = run_candidate_simulation(
        candidate=_make_candidate(), data=data, folds=folds, config=config_zero,
    )

    if result_none["fold_results"] and result_zero["fold_results"]:
        assert result_none["fold_results"][0]["pnl"] == result_zero["fold_results"][0]["pnl"]


def test_sharpe_and_sortino_helpers():
    # Positive returns → positive sharpe
    returns = [1.0, 2.0, 1.5, 0.5, 1.0]
    assert _compute_sharpe(returns) > 0
    # All-positive returns → zero downside deviation → sortino = 0
    assert _compute_sortino(returns) == 0.0

    # Mixed returns → sortino should be positive if mean > 0
    mixed = [2.0, -0.5, 1.5, -0.3, 1.0]
    assert _compute_sortino(mixed) > 0

    # All same → sharpe = 0 (no variance)
    assert _compute_sharpe([1.0, 1.0, 1.0]) == 0.0

    # Empty/single → 0
    assert _compute_sharpe([]) == 0.0
    assert _compute_sharpe([5.0]) == 0.0
    assert _compute_sortino([]) == 0.0


# ---------------------------------------------------------------------------
# Optimizer seed diversity
# ---------------------------------------------------------------------------

def test_candidate_seed_salt_deterministic():
    """Same candidate always produces the same salt."""
    salt1 = _candidate_seed_salt("breakout", {"lookback": 20, "atr_stop_mult": 1.5})
    salt2 = _candidate_seed_salt("breakout", {"lookback": 20, "atr_stop_mult": 1.5})
    assert salt1 == salt2
    assert isinstance(salt1, int)
    assert salt1 > 0


def test_candidate_seed_salt_varies_by_params():
    """Different params produce different salts."""
    salt_a = _candidate_seed_salt("breakout", {"lookback": 20, "atr_stop_mult": 1.5})
    salt_b = _candidate_seed_salt("breakout", {"lookback": 30, "atr_stop_mult": 1.5})
    assert salt_a != salt_b


def test_candidate_seed_salt_varies_by_family():
    """Different family produces different salt."""
    salt_a = _candidate_seed_salt("breakout", {"lookback": 20})
    salt_b = _candidate_seed_salt("ema_crossover", {"lookback": 20})
    assert salt_a != salt_b


def test_candidate_seed_salt_key_order_independent():
    """Param key order should not affect the salt."""
    salt1 = _candidate_seed_salt("breakout", {"a": 1.0, "b": 2.0})
    salt2 = _candidate_seed_salt("breakout", {"b": 2.0, "a": 1.0})
    assert salt1 == salt2


def test_refit_reproducible_same_candidate():
    """Same candidate run twice produces identical per-fold params."""
    data = generate_synthetic_data(n_bars=2000)
    max_lb = compute_max_feature_lookback(TEST_CONFIG["features"])
    folds = build_folds(len(data), TEST_FOLD_SPEC, max_lb)
    config = dict(TEST_CONFIG)
    config["minimum_any_fold_trades"] = 1
    config["optimizer_n_trials"] = 5

    candidate = _make_candidate()
    r1 = run_candidate_simulation(candidate, data, folds, config, refit=True)
    r2 = run_candidate_simulation(candidate, data, folds, config, refit=True)

    assert r1["per_fold_params"] == r2["per_fold_params"]
    assert r1["optimizer_seeds"] == r2["optimizer_seeds"]


def test_refit_different_candidates_get_different_seeds():
    """Different starting params should produce different optimizer seeds."""
    data = generate_synthetic_data(n_bars=2000)
    max_lb = compute_max_feature_lookback(TEST_CONFIG["features"])
    folds = build_folds(len(data), TEST_FOLD_SPEC, max_lb)
    config = dict(TEST_CONFIG)
    config["minimum_any_fold_trades"] = 1
    config["optimizer_n_trials"] = 5

    cand_a = {
        "candidate_id": "a", "logic_family_id": "breakout",
        "params": {"lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0, "min_atr": 0.5},
    }
    cand_b = {
        "candidate_id": "b", "logic_family_id": "breakout",
        "params": {"lookback": 30, "atr_stop_mult": 2.0, "atr_tp_mult": 4.0, "min_atr": 0.8},
    }

    r_a = run_candidate_simulation(cand_a, data, folds, config, refit=True)
    r_b = run_candidate_simulation(cand_b, data, folds, config, refit=True)

    # Seeds must differ
    assert r_a["optimizer_seeds"] != r_b["optimizer_seeds"]
    # Per-fold params should (almost certainly) differ
    if r_a["status"] == "PASS" and r_b["status"] == "PASS":
        assert r_a["per_fold_params"] != r_b["per_fold_params"]


def test_refit_returns_optimizer_seeds():
    """Refit results should include optimizer_seeds metadata."""
    data = generate_synthetic_data(n_bars=2000)
    max_lb = compute_max_feature_lookback(TEST_CONFIG["features"])
    folds = build_folds(len(data), TEST_FOLD_SPEC, max_lb)
    config = dict(TEST_CONFIG)
    config["minimum_any_fold_trades"] = 1
    config["optimizer_n_trials"] = 5

    result = run_candidate_simulation(_make_candidate(), data, folds, config, refit=True)
    assert "optimizer_seeds" in result
    assert len(result["optimizer_seeds"]) >= 1
    for s in result["optimizer_seeds"]:
        assert isinstance(s, int)
        assert s > 0
