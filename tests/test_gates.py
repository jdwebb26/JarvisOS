from strategy_factory.gates import evaluate_fold_gates, evaluate_all_folds, hard_gate_summary


def test_gates_shape():
    out = hard_gate_summary()
    assert "status" in out


def test_evaluate_fold_gates_shape():
    metrics = {
        "trades": 200,
        "max_drawdown_proxy": 500.0,
        "profit_factor": 1.5,
        "sharpe": 1.0,
        "sortino": 2.5,
    }
    out = evaluate_fold_gates(metrics, "5_60m_intraday")
    assert "overall" in out
    assert "min_trades_per_oos_fold" in out
    assert "profit_factor" in out
    assert "sharpe" in out
    assert "sortino" in out


def test_evaluate_fold_gates_pass():
    metrics = {
        "trades": 200,
        "max_drawdown_proxy": 100.0,
        "profit_factor": 2.0,
        "sharpe": 1.5,
        "sortino": 3.0,
    }
    out = evaluate_fold_gates(metrics, "5_60m_intraday")
    assert out["overall"] == "PASS"


def test_evaluate_fold_gates_fail_on_pf():
    metrics = {
        "trades": 200,
        "max_drawdown_proxy": 100.0,
        "profit_factor": 0.8,  # Below 1.3 threshold
        "sharpe": 1.5,
        "sortino": 3.0,
    }
    out = evaluate_fold_gates(metrics, "5_60m_intraday")
    assert out["overall"] == "FAIL"
    assert out["profit_factor"]["pass"] is False


def test_evaluate_all_folds():
    fold_results = [
        {"fold_id": 0, "trades": 200, "max_drawdown_proxy": 50.0,
         "profit_factor": 2.0, "sharpe": 1.5, "sortino": 3.0},
        {"fold_id": 1, "trades": 180, "max_drawdown_proxy": 80.0,
         "profit_factor": 1.5, "sharpe": 1.0, "sortino": 2.5},
    ]
    out = evaluate_all_folds(fold_results, "5_60m_intraday")
    assert "per_fold" in out
    assert "aggregate" in out
    assert len(out["per_fold"]) == 2
    assert out["aggregate"]["folds_evaluated"] == 2
    assert out["aggregate"]["overall"] == "PASS"
    assert out["aggregate"]["avg_profit_factor"] == 1.75


def test_evaluate_all_folds_mixed_pass_fail():
    fold_results = [
        {"fold_id": 0, "trades": 200, "max_drawdown_proxy": 50.0,
         "profit_factor": 2.0, "sharpe": 1.5, "sortino": 3.0},
        {"fold_id": 1, "trades": 10, "max_drawdown_proxy": 80.0,
         "profit_factor": 0.5, "sharpe": -0.5, "sortino": -1.0},
    ]
    out = evaluate_all_folds(fold_results, "5_60m_intraday")
    assert out["aggregate"]["overall"] == "FAIL"
    assert out["aggregate"]["folds_passed"] == 1
    assert out["aggregate"]["folds_failed"] == 1
