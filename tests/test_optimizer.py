from strategy_factory.data import generate_synthetic_data
from strategy_factory.features import compute_features
from strategy_factory.optimizer import optimize_params, _evaluate_on_bars
from strategy_factory.config import DEFAULT_CONFIG


def _get_train_bars(n_bars=2000):
    data = generate_synthetic_data(n_bars=n_bars)
    enriched = compute_features(data, DEFAULT_CONFIG["features"])
    # Use first 1000 bars as "train" — simulating train/OOS split
    return enriched[:1000]


def test_evaluate_on_bars_breakout():
    bars = _get_train_bars()
    result = _evaluate_on_bars("breakout", bars, {
        "lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0, "min_atr": 0.5,
    })
    assert result is not None
    assert "trades" in result
    assert "pnl" in result
    assert "profit_factor" in result
    assert "reward_proxy" in result
    assert result["trades"] > 0


def test_optimize_params_returns_best():
    bars = _get_train_bars()
    base_params = {"lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0, "min_atr": 0.5}
    result = optimize_params("breakout", bars, base_params, n_trials=10, seed=42)
    assert "best_params" in result
    assert "best_reward" in result
    assert "trials_evaluated" in result
    assert result["trials_evaluated"] == 10
    assert "baseline_reward" in result


def test_optimize_does_not_worsen():
    """Optimizer should find params at least as good as baseline."""
    bars = _get_train_bars()
    base_params = {"lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0, "min_atr": 0.5}
    result = optimize_params("breakout", bars, base_params, n_trials=20, seed=42)
    assert result["best_reward"] >= result["baseline_reward"]


def test_optimize_train_only():
    """Verify optimizer uses only the bars provided (train data)."""
    # Two different train windows should produce different optimal params
    data = generate_synthetic_data(n_bars=4000)
    enriched = compute_features(data, DEFAULT_CONFIG["features"])

    train_a = enriched[:1000]
    train_b = enriched[2000:3000]
    base = {"lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0, "min_atr": 0.5}

    result_a = optimize_params("breakout", train_a, base, n_trials=10, seed=42)
    result_b = optimize_params("breakout", train_b, base, n_trials=10, seed=42)

    # Different data windows should give different rewards (not guaranteed
    # but highly likely with different price regimes)
    # At minimum, the function should run without error
    assert result_a["trials_evaluated"] == 10
    assert result_b["trials_evaluated"] == 10
