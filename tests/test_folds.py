from strategy_factory.features import compute_max_feature_lookback
from strategy_factory.folds import build_folds, validate_purge_gap


def test_build_folds_contains_purge_window():
    max_lb = compute_max_feature_lookback({
        "ema_fast": {"lookback": 12},
        "ema_slow": {"lookback": 26},
    })
    folds = build_folds(
        4000,
        {
            "mode": "rolling",
            "train_len": 1000,
            "test_len": 200,
            "purge_len": 50,
            "retrain_cadence": 200,
            "n_folds": 4,
        },
        max_lb,
    )
    assert len(folds) > 0
    assert folds[0]["purge_len"] >= max_lb
    assert folds[0]["purge_end"] - folds[0]["purge_start"] == folds[0]["purge_len"]


def test_validate_purge_gap_raises():
    raised = False
    try:
        validate_purge_gap(10, 50, sentinel_mode=False)
    except ValueError:
        raised = True
    assert raised is True
