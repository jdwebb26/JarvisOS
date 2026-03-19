from .sim import run_candidate_simulation
from .gates import evaluate_all_folds
from .scoring import compute_score


def lambda_sweep(candidate, data, folds, config, lambdas=None):
    """Grid search over reward_lambda values.

    For each lambda, re-runs simulation (sim uses reward_lambda in its proxy)
    and scores the result. Returns the best lambda and all trial results.

    Args:
        candidate: candidate dict
        data: OHLCV rows
        folds: walk-forward folds
        config: pipeline config
        lambdas: list of reward_lambda values to try (default: 0.01..0.20)

    Returns:
        dict with best_lambda, best_score, trials list
    """
    if lambdas is None:
        lambdas = [round(0.01 + i * 0.02, 2) for i in range(10)]  # 0.01, 0.03, ..., 0.19

    trials = []
    best_score = -1.0
    best_lambda = config.get("reward_lambda", 0.05)

    for lam in lambdas:
        trial_config = dict(config)
        trial_config["reward_lambda"] = lam

        result = run_candidate_simulation(candidate, data, folds, trial_config)
        if result["status"] != "PASS" or not result["fold_results"]:
            trials.append({
                "reward_lambda": lam,
                "status": result["status"],
                "score": 0.0,
            })
            continue

        gate_result = evaluate_all_folds(
            result["fold_results"], config.get("timeframe_bucket", "5_60m_intraday")
        )
        score_result = compute_score(result["fold_results"], trial_config)
        score = score_result.get("score", 0.0)

        trials.append({
            "reward_lambda": lam,
            "status": result["status"],
            "gate_overall": gate_result["aggregate"]["overall"],
            "score": round(score, 6),
            "avg_pf": score_result.get("averages", {}).get("avg_pf", 0.0),
        })

        if score > best_score:
            best_score = score
            best_lambda = lam

    return {
        "status": "COMPLETE",
        "best_lambda": best_lambda,
        "best_score": round(best_score, 6),
        "trials": trials,
    }
