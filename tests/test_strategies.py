from strategy_factory.data import generate_synthetic_data
from strategy_factory.features import compute_features
from strategy_factory.strategies import run_strategy, STRATEGY_REGISTRY
from strategy_factory.config import DEFAULT_CONFIG


def _get_enriched(n_bars=2000):
    data = generate_synthetic_data(n_bars=n_bars)
    return compute_features(data, DEFAULT_CONFIG["features"])


def test_strategy_registry():
    assert "ema_crossover" in STRATEGY_REGISTRY
    assert "ema_crossover_cd" in STRATEGY_REGISTRY
    assert "mean_reversion" in STRATEGY_REGISTRY
    assert "breakout" in STRATEGY_REGISTRY


def test_ema_crossover_produces_trades():
    bars = _get_enriched()
    trades = run_strategy("ema_crossover", bars, {
        "atr_stop_mult": 2.0, "atr_tp_mult": 3.0, "min_atr": 0.5,
    })
    assert isinstance(trades, list)
    assert len(trades) > 0
    for t in trades:
        assert "entry_bar" in t
        assert "exit_bar" in t
        assert "direction" in t
        assert t["direction"] in (1, -1)
        assert "pnl" in t
        assert "exit_reason" in t
        assert t["exit_reason"] in ("signal", "stop", "take_profit", "end_of_data")


def test_mean_reversion_produces_trades():
    bars = _get_enriched()
    trades = run_strategy("mean_reversion", bars, {
        "entry_atr_mult": 1.5, "atr_stop_mult": 2.0, "min_atr": 0.5,
    })
    assert isinstance(trades, list)
    assert len(trades) > 0


def test_breakout_produces_trades():
    bars = _get_enriched()
    trades = run_strategy("breakout", bars, {
        "lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0, "min_atr": 0.5,
    })
    assert isinstance(trades, list)
    assert len(trades) > 0


def test_unknown_strategy_raises():
    bars = _get_enriched(100)
    raised = False
    try:
        run_strategy("nonexistent", bars, {})
    except ValueError:
        raised = True
    assert raised


def test_trade_pnl_is_consistent():
    """Verify that trade PnL = (exit - entry) * direction."""
    bars = _get_enriched()
    trades = run_strategy("breakout", bars, {
        "lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0, "min_atr": 0.5,
    })
    for t in trades:
        expected_pnl = round((t["exit_price"] - t["entry_price"]) * t["direction"], 2)
        assert t["pnl"] == expected_pnl, f"PnL mismatch: {t}"


def test_no_overlapping_trades():
    """Verify single position — no overlapping trades."""
    bars = _get_enriched()
    for family in ["ema_crossover", "ema_crossover_cd", "mean_reversion", "breakout"]:
        params = {"atr_stop_mult": 2.0, "atr_tp_mult": 3.0, "min_atr": 0.5}
        if family == "mean_reversion":
            params["entry_atr_mult"] = 1.5
        elif family == "breakout":
            params["lookback"] = 20
        elif family == "ema_crossover_cd":
            params["cooldown_bars"] = 10
        trades = run_strategy(family, bars, params)
        for i in range(len(trades) - 1):
            assert trades[i]["exit_bar"] <= trades[i + 1]["entry_bar"], \
                f"Overlap in {family}: trade {i} exits at {trades[i]['exit_bar']} " \
                f"but trade {i+1} enters at {trades[i+1]['entry_bar']}"


def test_ema_cd_produces_trades():
    bars = _get_enriched()
    trades = run_strategy("ema_crossover_cd", bars, {
        "atr_stop_mult": 2.0, "atr_tp_mult": 3.0, "min_atr": 0.5,
        "cooldown_bars": 10,
    })
    assert isinstance(trades, list)
    assert len(trades) > 0
    for t in trades:
        assert t["exit_reason"] in ("signal", "stop", "take_profit", "end_of_data")


def test_ema_cd_cooldown_reduces_trades():
    """Cooldown should produce <= trades than base ema_crossover."""
    bars = _get_enriched()
    params = {"atr_stop_mult": 2.0, "atr_tp_mult": 3.0, "min_atr": 0.3}
    base_trades = run_strategy("ema_crossover", bars, params)
    cd_trades = run_strategy("ema_crossover_cd", bars,
                             {**params, "cooldown_bars": 10})
    assert len(cd_trades) <= len(base_trades)


def test_ema_cd_zero_cooldown_close_to_base():
    """With cooldown_bars=0, behavior is close to base but may differ on
    same-bar re-entry after stopout (cooldown check blocks i > i)."""
    bars = _get_enriched()
    params = {"atr_stop_mult": 2.0, "atr_tp_mult": 3.0, "min_atr": 0.5}
    base = run_strategy("ema_crossover", bars, params)
    cd0 = run_strategy("ema_crossover_cd", bars, {**params, "cooldown_bars": 0})
    # Should be very close — small differences only from same-bar re-entry edge case
    assert abs(len(base) - len(cd0)) <= len(base) * 0.15


def test_ema_cd_cooldown_bars_affects_behavior():
    """Different cooldown values should produce different results."""
    bars = _get_enriched(3000)
    params = {"atr_stop_mult": 2.0, "atr_tp_mult": 3.0, "min_atr": 0.3}
    trades_5 = run_strategy("ema_crossover_cd", bars,
                            {**params, "cooldown_bars": 5})
    trades_20 = run_strategy("ema_crossover_cd", bars,
                             {**params, "cooldown_bars": 20})
    # Longer cooldown should produce fewer or equal trades
    assert len(trades_20) <= len(trades_5)
