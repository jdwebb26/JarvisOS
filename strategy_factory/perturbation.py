import random
import math


def jitter_params(params, param_types, pct=0.10, rng=None):
    """Jitter numeric parameters by ±pct (default ±10%).

    param_types: dict mapping param name to type hint.
        "float" params get continuous jitter.
        "int" params get rounded jitter.
        Other types are passed through unchanged.
    """
    if rng is None:
        rng = random.Random()
    out = {}
    for k, v in params.items():
        ptype = param_types.get(k, "float")
        if ptype in ("float", "int") and isinstance(v, (int, float)):
            lo = v * (1 - pct)
            hi = v * (1 + pct)
            jittered = rng.uniform(lo, hi)
            if ptype == "int":
                jittered = int(round(jittered))
            out[k] = jittered
        else:
            out[k] = v
    return out


def run_perturbation_test(candidate, data, folds, config, sim_fn,
                          n_trials=5, jitter_pct=0.10, seed=None):
    """Run perturbation robustness test.

    Jitters candidate params n_trials times and re-simulates.
    Returns a report with baseline vs perturbed PF and degradation stats.

    Args:
        candidate: dict with candidate_id, logic_family_id, params, param_types
        data: OHLCV rows
        folds: walk-forward folds
        config: pipeline config
        sim_fn: simulation function (run_candidate_simulation)
        n_trials: number of perturbed runs
        jitter_pct: jitter magnitude (0.10 = ±10%)
        seed: random seed for reproducibility

    Returns:
        dict with baseline_pf, perturbed_pfs, mean_perturbed_pf,
        pf_degradation_pct, robust (bool), details
    """
    rng = random.Random(seed)

    # Baseline run
    baseline_result = sim_fn(candidate, data, folds, config)
    if baseline_result["status"] != "PASS" or not baseline_result["fold_results"]:
        return {
            "status": "SKIP",
            "reason": f"Baseline {baseline_result['status']}: {baseline_result.get('reject_reason')}",
            "baseline_pf": None,
            "perturbed_pfs": [],
            "robust": False,
        }

    baseline_pfs = [fr["profit_factor"] for fr in baseline_result["fold_results"]]
    baseline_avg_pf = sum(baseline_pfs) / len(baseline_pfs)

    params = candidate.get("params", {})
    param_types = candidate.get("param_types", {})

    perturbed_results = []
    for trial_idx in range(n_trials):
        jittered = jitter_params(params, param_types, pct=jitter_pct, rng=rng)
        perturbed_candidate = dict(candidate)
        perturbed_candidate["params"] = jittered
        result = sim_fn(perturbed_candidate, data, folds, config)

        if result["status"] == "PASS" and result["fold_results"]:
            pfs = [fr["profit_factor"] for fr in result["fold_results"]]
            avg_pf = sum(pfs) / len(pfs)
        else:
            avg_pf = 0.0

        perturbed_results.append({
            "trial": trial_idx,
            "jittered_params": jittered,
            "status": result["status"],
            "avg_pf": round(avg_pf, 4),
        })

    perturbed_pfs = [pr["avg_pf"] for pr in perturbed_results]
    mean_perturbed_pf = sum(perturbed_pfs) / len(perturbed_pfs) if perturbed_pfs else 0.0

    if baseline_avg_pf > 0:
        degradation_pct = (baseline_avg_pf - mean_perturbed_pf) / baseline_avg_pf
    else:
        degradation_pct = 1.0

    # Robust if mean perturbed PF doesn't degrade more than 20%
    robust = degradation_pct < 0.20

    return {
        "status": "COMPLETE",
        "baseline_avg_pf": round(baseline_avg_pf, 4),
        "perturbed_pfs": [round(p, 4) for p in perturbed_pfs],
        "mean_perturbed_pf": round(mean_perturbed_pf, 4),
        "pf_degradation_pct": round(degradation_pct, 4),
        "robust": robust,
        "n_trials": n_trials,
        "jitter_pct": jitter_pct,
        "details": perturbed_results,
    }
