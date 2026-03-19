from strategy_factory.stress import stress_check
from strategy_factory.data import generate_synthetic_data
from strategy_factory.features import compute_max_feature_lookback
from strategy_factory.folds import build_folds
from strategy_factory.sim import run_candidate_simulation
from strategy_factory.config import DEFAULT_CONFIG


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
TEST_CONFIG["minimum_any_fold_trades"] = 1


def test_stress_check_runs():
    data = generate_synthetic_data(n_bars=2000)
    max_lb = compute_max_feature_lookback(TEST_CONFIG["features"])
    folds = build_folds(len(data), TEST_FOLD_SPEC, max_lb)
    candidate = {
        "candidate_id": "stress_test",
        "logic_family_id": "breakout",
        "params": {"lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0, "min_atr": 0.5},
        "param_types": {"lookback": "int", "atr_stop_mult": "float",
                        "atr_tp_mult": "float", "min_atr": "float"},
    }
    report = stress_check(candidate, data, folds, TEST_CONFIG, sim_fn=run_candidate_simulation)
    assert report["status"] in ("COMPLETE", "SKIP")
    if report["status"] == "COMPLETE":
        assert report["overall"] in ("PASS", "FAIL")
        assert "regimes" in report
        assert "low_vol" in report["regimes"]
        assert "mid_vol" in report["regimes"]
        assert "high_vol" in report["regimes"]


def test_stress_check_has_regime_pf():
    data = generate_synthetic_data(n_bars=2000)
    max_lb = compute_max_feature_lookback(TEST_CONFIG["features"])
    folds = build_folds(len(data), TEST_FOLD_SPEC, max_lb)
    candidate = {
        "candidate_id": "stress_pf",
        "logic_family_id": "breakout",
        "params": {"lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0, "min_atr": 0.5},
        "param_types": {"lookback": "int", "atr_stop_mult": "float",
                        "atr_tp_mult": "float", "min_atr": "float"},
    }
    report = stress_check(candidate, data, folds, TEST_CONFIG, sim_fn=run_candidate_simulation)
    if report["status"] == "COMPLETE":
        for regime_name, info in report["regimes"].items():
            assert "trades" in info
            assert "gate_pass" in info
            if info["trades"] > 0:
                assert "profit_factor" in info
