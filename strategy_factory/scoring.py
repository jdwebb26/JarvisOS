import math


def compute_score(fold_results, config, perturbation_report=None, stress_report=None):
    """Multi-objective scoring for a candidate across all folds.

    Components (weighted):
        - profit_factor_score: normalized PF (capped at 3.0 → 1.0)
        - sharpe_score: normalized Sharpe (capped at 3.0 → 1.0)
        - sortino_score: normalized Sortino (capped at 5.0 → 1.0)
        - drawdown_score: inverse of max_dd (lower is better)
        - consistency_score: 1 - CV of per-fold PFs (less variance is better)
        - robustness_bonus: bonus if perturbation test passed
        - stress_bonus: bonus if stress test passed

    Returns:
        dict with component scores and final weighted score.
    """
    if not fold_results:
        return {"status": "NO_FOLDS", "score": 0.0}

    n = len(fold_results)
    score_lambda = config.get("score_lambda", 0.30)

    # Extract per-fold metrics
    pfs = [fr.get("profit_factor", 0.0) for fr in fold_results]
    sharpes = [fr.get("sharpe", 0.0) for fr in fold_results]
    sortinos = [fr.get("sortino", 0.0) for fr in fold_results]
    dds = [fr.get("max_drawdown_proxy", 0.0) for fr in fold_results]

    avg_pf = sum(pfs) / n
    avg_sharpe = sum(sharpes) / n
    avg_sortino = sum(sortinos) / n
    max_dd = max(dds)

    # Normalize to [0, 1] with caps
    pf_score = min(1.0, max(0.0, avg_pf / 3.0))
    sharpe_score = min(1.0, max(0.0, avg_sharpe / 3.0))
    sortino_score = min(1.0, max(0.0, avg_sortino / 5.0))
    dd_score = max(0.0, 1.0 - (max_dd / 1000.0))

    # Consistency: 1 - coefficient of variation of PF across folds
    pf_mean = avg_pf
    if n > 1 and pf_mean > 0:
        pf_std = math.sqrt(sum((v - pf_mean) ** 2 for v in pfs) / (n - 1))
        cv = pf_std / pf_mean
        consistency_score = max(0.0, 1.0 - cv)
    else:
        consistency_score = 0.5

    # Robustness bonus
    robustness_bonus = 0.0
    if perturbation_report and perturbation_report.get("robust"):
        robustness_bonus = 0.1

    # Stress bonus
    stress_bonus = 0.0
    if stress_report and stress_report.get("overall") == "PASS":
        stress_bonus = 0.1

    # Weighted combination
    weights = {
        "profit_factor": 0.30,
        "sharpe": 0.15,
        "sortino": 0.15,
        "drawdown": 0.15,
        "consistency": 0.25,
    }

    raw_score = (
        weights["profit_factor"] * pf_score
        + weights["sharpe"] * sharpe_score
        + weights["sortino"] * sortino_score
        + weights["drawdown"] * dd_score
        + weights["consistency"] * consistency_score
        + robustness_bonus
        + stress_bonus
    )

    # Scale by score_lambda for final ranking comparability
    final_score = raw_score * (1 + score_lambda)

    return {
        "status": "SCORED",
        "score": round(final_score, 6),
        "raw_score": round(raw_score, 6),
        "components": {
            "profit_factor": round(pf_score, 4),
            "sharpe": round(sharpe_score, 4),
            "sortino": round(sortino_score, 4),
            "drawdown": round(dd_score, 4),
            "consistency": round(consistency_score, 4),
            "robustness_bonus": round(robustness_bonus, 4),
            "stress_bonus": round(stress_bonus, 4),
        },
        "averages": {
            "avg_pf": round(avg_pf, 4),
            "avg_sharpe": round(avg_sharpe, 4),
            "avg_sortino": round(avg_sortino, 4),
            "max_dd": round(max_dd, 4),
        },
        "weights": weights,
        "score_lambda": score_lambda,
    }
