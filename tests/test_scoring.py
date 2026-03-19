from strategy_factory.scoring import compute_score
from strategy_factory.config import DEFAULT_CONFIG


def test_score_no_folds():
    result = compute_score([], DEFAULT_CONFIG)
    assert result["status"] == "NO_FOLDS"
    assert result["score"] == 0.0


def test_score_basic():
    fold_results = [
        {
            "fold_id": 0, "profit_factor": 2.0, "sharpe": 1.5,
            "sortino": 3.0, "max_drawdown_proxy": 50.0,
            "win_rate": 0.6, "expectancy": 0.5,
        },
    ]
    result = compute_score(fold_results, DEFAULT_CONFIG)
    assert result["status"] == "SCORED"
    assert result["score"] > 0
    assert result["components"]["profit_factor"] > 0
    assert result["components"]["sharpe"] > 0


def test_score_with_robustness_bonus():
    fold_results = [
        {
            "fold_id": 0, "profit_factor": 2.0, "sharpe": 1.0,
            "sortino": 2.0, "max_drawdown_proxy": 100.0,
        },
    ]
    without = compute_score(fold_results, DEFAULT_CONFIG)
    with_pert = compute_score(fold_results, DEFAULT_CONFIG, perturbation_report={"robust": True})
    assert with_pert["score"] > without["score"]


def test_score_with_stress_bonus():
    fold_results = [
        {
            "fold_id": 0, "profit_factor": 2.0, "sharpe": 1.0,
            "sortino": 2.0, "max_drawdown_proxy": 100.0,
        },
    ]
    without = compute_score(fold_results, DEFAULT_CONFIG)
    with_stress = compute_score(fold_results, DEFAULT_CONFIG, stress_report={"overall": "PASS"})
    assert with_stress["score"] > without["score"]
