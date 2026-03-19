"""Tests for selector / ensemble experiment layer."""

from strategy_factory.data import generate_synthetic_data
from strategy_factory.features import compute_max_feature_lookback
from strategy_factory.folds import build_folds
from strategy_factory.config import DEFAULT_CONFIG, GATE_PROFILES
from strategy_factory.selector_experiments import (
    _prepare_candidates,
    experiment_static_basket,
    experiment_train_selector,
    select_by_train_reward,
    select_by_train_pf,
    select_breakout_if_high_vix,
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
    candidates = [
        {"candidate_id": "ema_a", "logic_family_id": "ema_crossover",
         "params": {"atr_stop_mult": 2.0, "atr_tp_mult": 3.0, "min_atr": 0.5}},
        {"candidate_id": "brk_a", "logic_family_id": "breakout",
         "params": {"lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0,
                    "min_atr": 0.5}},
    ]
    return data, folds, config, gate_profile, candidates


def test_prepare_candidates():
    data, folds, config, _, candidates = _setup()
    prepared, enriched = _prepare_candidates(candidates, data, folds, config)
    assert len(prepared) == 2
    for p in prepared:
        assert len(p["per_fold"]) == len(folds)
        for fi in p["per_fold"]:
            assert "train_reward" in fi
            assert "train_pf" in fi
            assert "train_trades" in fi
            assert "recent_vix_20" in fi
            assert "refitted_params" in fi


def test_prepare_deterministic():
    data, folds, config, _, candidates = _setup()
    p1, _ = _prepare_candidates(candidates, data, folds, config)
    p2, _ = _prepare_candidates(candidates, data, folds, config)
    for a, b in zip(p1, p2):
        for fa, fb in zip(a["per_fold"], b["per_fold"]):
            assert fa["train_reward"] == fb["train_reward"]
            assert fa["refitted_params"] == fb["refitted_params"]


def test_static_basket_returns_structure():
    data, folds, config, gate_profile, candidates = _setup()
    prepared, enriched = _prepare_candidates(candidates, data, folds, config)
    result = experiment_static_basket(
        prepared, enriched, folds, config, gate_profile,
        basket_ids=["ema_a", "brk_a"], name="test_basket")
    assert result["type"] == "static_basket"
    assert result["basket_size"] == 2
    assert "anti_leakage" in result
    assert "overlap_handling" in result
    assert len(result["per_fold"]) == len(folds)
    for f in result["per_fold"]:
        assert "any_pass" in f
        assert "members_evaluated" in f
        assert f["members_evaluated"] == 2


def test_static_basket_individual_baseline():
    """Individual basket of 1 should match single-candidate evaluation."""
    data, folds, config, gate_profile, candidates = _setup()
    prepared, enriched = _prepare_candidates(candidates, data, folds, config)
    r = experiment_static_basket(
        prepared, enriched, folds, config, gate_profile,
        basket_ids=["ema_a"])
    assert r["basket_size"] == 1
    for f in r["per_fold"]:
        assert f["members_evaluated"] == 1


def test_train_selector_no_leakage():
    """Selector function receives train signals only, never OOS results."""
    data, folds, config, gate_profile, candidates = _setup()
    prepared, enriched = _prepare_candidates(candidates, data, folds, config)

    seen_signals = []

    def recording_selector(signals):
        seen_signals.append(signals)
        return signals[0]["candidate_id"]

    result = experiment_train_selector(
        prepared, enriched, folds, config, gate_profile,
        selector_fn=recording_selector, name="test_leakage")

    assert len(seen_signals) == len(folds)
    for fold_signals in seen_signals:
        for s in fold_signals:
            # Selector only sees these train-window fields
            assert "train_reward" in s
            assert "train_pf" in s
            assert "train_trades" in s
            assert "recent_vix_20" in s
            # Must NOT have OOS fields
            assert "pf" not in s
            assert "sharpe" not in s
            assert "sortino" not in s
            assert "gate_overall" not in s


def test_train_selector_returns_structure():
    data, folds, config, gate_profile, candidates = _setup()
    prepared, enriched = _prepare_candidates(candidates, data, folds, config)
    result = experiment_train_selector(
        prepared, enriched, folds, config, gate_profile,
        selector_fn=select_by_train_reward, name="test_sel")
    assert result["type"] == "train_selector"
    assert "anti_leakage" in result
    assert len(result["per_fold"]) == len(folds)
    for f in result["per_fold"]:
        assert "chosen" in f
        assert "selection_reason" in f


def test_vix_family_selector():
    """VIX-conditioned selector picks breakout when VIX is high."""
    signals_high = [
        {"candidate_id": "ema_1", "family": "ema_crossover",
         "train_reward": 100, "train_pf": 2.0, "train_trades": 10,
         "recent_vix_20": 30.0},
        {"candidate_id": "brk_1", "family": "breakout",
         "train_reward": 80, "train_pf": 1.5, "train_trades": 15,
         "recent_vix_20": 30.0},
    ]
    assert select_breakout_if_high_vix(signals_high, 25.0) == "brk_1"

    signals_low = [
        {"candidate_id": "ema_1", "family": "ema_crossover",
         "train_reward": 100, "train_pf": 2.0, "train_trades": 10,
         "recent_vix_20": 18.0},
        {"candidate_id": "brk_1", "family": "breakout",
         "train_reward": 80, "train_pf": 1.5, "train_trades": 15,
         "recent_vix_20": 18.0},
    ]
    assert select_breakout_if_high_vix(signals_low, 25.0) == "ema_1"
