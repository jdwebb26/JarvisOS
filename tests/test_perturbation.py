from strategy_factory.perturbation import jitter_params, run_perturbation_test
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


def test_jitter_params_changes_values():
    params = {"a": 10.0, "b": 5.0}
    types = {"a": "float", "b": "float"}
    import random
    rng = random.Random(99)
    jittered = jitter_params(params, types, pct=0.10, rng=rng)
    # At least one value should differ (statistically near-certain)
    assert jittered["a"] != params["a"] or jittered["b"] != params["b"]
    # Values should be within ±10%
    assert 9.0 <= jittered["a"] <= 11.0
    assert 4.5 <= jittered["b"] <= 5.5


def test_jitter_params_int_rounding():
    params = {"n": 100}
    types = {"n": "int"}
    import random
    rng = random.Random(42)
    jittered = jitter_params(params, types, pct=0.10, rng=rng)
    assert isinstance(jittered["n"], int)
    assert 90 <= jittered["n"] <= 110


def test_jitter_params_passthrough_unknown_types():
    params = {"x": 5.0, "name": "strategy_a"}
    types = {"x": "float", "name": "str"}
    import random
    rng = random.Random(1)
    jittered = jitter_params(params, types, pct=0.10, rng=rng)
    assert jittered["name"] == "strategy_a"


def test_perturbation_test_runs():
    data = generate_synthetic_data(n_bars=2000)
    max_lb = compute_max_feature_lookback(TEST_CONFIG["features"])
    folds = build_folds(len(data), TEST_FOLD_SPEC, max_lb)
    candidate = {
        "candidate_id": "perturb_test",
        "logic_family_id": "breakout",
        "params": {"lookback": 20, "atr_stop_mult": 1.5, "atr_tp_mult": 3.0, "min_atr": 0.5},
        "param_types": {"lookback": "int", "atr_stop_mult": "float",
                        "atr_tp_mult": "float", "min_atr": "float"},
    }
    report = run_perturbation_test(
        candidate, data, folds, TEST_CONFIG,
        sim_fn=run_candidate_simulation,
        n_trials=3, seed=42,
    )
    assert report["status"] in ("COMPLETE", "SKIP")
    if report["status"] == "COMPLETE":
        assert "baseline_avg_pf" in report
        assert len(report["perturbed_pfs"]) == 3
        assert "robust" in report
