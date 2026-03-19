from strategy_factory.diversity import compute_fingerprint


def test_fingerprint_empty():
    fp = compute_fingerprint([])
    assert len(fp) == 34
    assert all(v == 0.0 for v in fp)


def test_fingerprint_shape():
    fold_results = [
        {
            "fold_id": 0, "profit_factor": 1.5, "sharpe": 0.8,
            "sortino": 1.2, "win_rate": 0.55, "expectancy": 0.3,
            "max_drawdown_proxy": 50.0, "trades": 150,
            "avg_winner": 2.0, "avg_loser": 1.5,
            "gross_profit": 100.0, "gross_loss": 66.7, "pnl": 33.3,
        },
        {
            "fold_id": 1, "profit_factor": 1.3, "sharpe": 0.6,
            "sortino": 0.9, "win_rate": 0.52, "expectancy": 0.2,
            "max_drawdown_proxy": 80.0, "trades": 130,
            "avg_winner": 1.8, "avg_loser": 1.6,
            "gross_profit": 90.0, "gross_loss": 70.0, "pnl": 20.0,
        },
    ]
    fp = compute_fingerprint(fold_results)
    assert len(fp) == 34
    # PF mean should be around 1.4
    assert 1.3 < fp[0] < 1.5
    # All values should be finite
    assert all(isinstance(v, float) for v in fp)


def test_fingerprint_single_fold():
    fold_results = [
        {
            "fold_id": 0, "profit_factor": 2.0, "sharpe": 1.0,
            "sortino": 1.5, "win_rate": 0.6, "expectancy": 0.5,
            "max_drawdown_proxy": 30.0, "trades": 200,
            "avg_winner": 3.0, "avg_loser": 2.0,
            "gross_profit": 120.0, "gross_loss": 60.0, "pnl": 60.0,
        },
    ]
    fp = compute_fingerprint(fold_results)
    assert len(fp) == 34
    # With single fold, std should be 0
    assert fp[1] == 0.0  # PF std
