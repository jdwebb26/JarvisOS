from strategy_factory.data import generate_synthetic_data
from strategy_factory.features import (
    compute_features, compute_max_feature_lookback, _ema, _atr,
)
from strategy_factory.config import DEFAULT_CONFIG


def test_compute_max_feature_lookback():
    lb = compute_max_feature_lookback(DEFAULT_CONFIG["features"])
    assert lb == 26  # ema_slow lookback


def test_ema_length():
    values = [float(i) for i in range(100)]
    result = _ema(values, 12)
    assert len(result) == 100


def test_atr_length():
    data = generate_synthetic_data(n_bars=100)
    result = _atr(data, 14)
    assert len(result) == 100
    assert all(v >= 0 for v in result)


def test_compute_features_enriches_data():
    data = generate_synthetic_data(n_bars=200)
    enriched = compute_features(data, DEFAULT_CONFIG["features"])
    assert len(enriched) == 200
    for row in enriched:
        assert "ema_fast" in row
        assert "ema_slow" in row
        assert "atr" in row
        assert "vix_regime" in row
        assert row["vix_regime"] in ("low_vol", "mid_vol", "high_vol")


def test_features_do_not_mutate_original():
    data = generate_synthetic_data(n_bars=50)
    original_keys = set(data[0].keys())
    compute_features(data, DEFAULT_CONFIG["features"])
    assert set(data[0].keys()) == original_keys
