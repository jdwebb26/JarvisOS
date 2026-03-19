"""Generate candidate strategy configurations from param ranges.

Each strategy family defines its param space. Candidates are generated
via random sampling within those ranges.
"""
import random
import uuid


# Param space definitions per strategy family.
# Each param: (min, max, type, default)
PARAM_SPACES = {
    "ema_crossover": {
        "atr_stop_mult": (1.0, 4.0, "float", 2.0),
        "atr_tp_mult":   (1.5, 6.0, "float", 3.0),
        "min_atr":       (0.1, 2.0, "float", 0.5),
    },
    "ema_crossover_cd": {
        "atr_stop_mult": (1.0, 4.0, "float", 2.0),
        "atr_tp_mult":   (1.5, 6.0, "float", 3.0),
        "min_atr":       (0.1, 2.0, "float", 0.5),
        "cooldown_bars": (5, 25, "int", 10),
    },
    "mean_reversion": {
        "entry_atr_mult": (0.8, 3.0, "float", 1.5),
        "atr_stop_mult":  (1.0, 4.0, "float", 2.0),
        "min_atr":        (0.1, 2.0, "float", 0.5),
    },
    "breakout": {
        "lookback":      (10, 50, "int", 20),
        "atr_stop_mult": (1.0, 3.0, "float", 1.5),
        "atr_tp_mult":   (2.0, 6.0, "float", 3.0),
        "min_atr":       (0.1, 2.0, "float", 0.5),
    },
}

# Map strategy families to their natural timeframe bucket for gate evaluation
FAMILY_TIMEFRAME = {
    "ema_crossover": "multi_hour_overnight",
    "ema_crossover_cd": "multi_hour_overnight",
    "mean_reversion": "5_60m_intraday",
    "breakout": "multi_hour_overnight",
}


def generate_candidates(families=None, n_per_family=5, seed=None):
    """Generate candidate dicts by random sampling from param spaces.

    Args:
        families: list of family names (default: all registered families)
        n_per_family: number of candidates per family
        seed: random seed for reproducibility

    Returns:
        list of candidate dicts, each with:
            candidate_id, logic_family_id, params, param_types
    """
    if families is None:
        families = list(PARAM_SPACES.keys())

    rng = random.Random(seed)
    candidates = []

    for family in families:
        space = PARAM_SPACES.get(family)
        if space is None:
            raise ValueError(f"No param space for family: {family}")

        param_types = {k: v[2] for k, v in space.items()}

        for i in range(n_per_family):
            params = {}
            for pname, (lo, hi, ptype, default) in space.items():
                val = rng.uniform(lo, hi)
                if ptype == "int":
                    val = int(round(val))
                else:
                    val = round(val, 4)
                params[pname] = val

            cid = f"{family}_{uuid.uuid4().hex[:8]}"
            candidates.append({
                "candidate_id": cid,
                "logic_family_id": family,
                "params": params,
                "param_types": param_types,
            })

    return candidates


def generate_default_candidate(family):
    """Generate a single candidate with default params for a family."""
    space = PARAM_SPACES.get(family)
    if space is None:
        raise ValueError(f"No param space for family: {family}")
    params = {k: v[3] for k, v in space.items()}
    param_types = {k: v[2] for k, v in space.items()}
    return {
        "candidate_id": f"{family}_default",
        "logic_family_id": family,
        "params": params,
        "param_types": param_types,
    }
