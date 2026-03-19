from strategy_factory.candidate_gen import (
    generate_candidates, generate_default_candidate, PARAM_SPACES, FAMILY_TIMEFRAME,
)


def test_generate_candidates_shape():
    candidates = generate_candidates(families=["breakout"], n_per_family=3, seed=42)
    assert len(candidates) == 3
    for c in candidates:
        assert "candidate_id" in c
        assert "logic_family_id" in c
        assert c["logic_family_id"] == "breakout"
        assert "params" in c
        assert "param_types" in c


def test_generate_candidates_all_families():
    candidates = generate_candidates(n_per_family=2, seed=42)
    families = {c["logic_family_id"] for c in candidates}
    assert "ema_crossover" in families
    assert "ema_crossover_cd" in families
    assert "mean_reversion" in families
    assert "breakout" in families
    assert len(candidates) == 2 * len(PARAM_SPACES)


def test_generate_candidates_unique_ids():
    candidates = generate_candidates(n_per_family=5, seed=42)
    ids = [c["candidate_id"] for c in candidates]
    assert len(ids) == len(set(ids))


def test_generate_candidates_params_in_range():
    candidates = generate_candidates(families=["breakout"], n_per_family=10, seed=42)
    space = PARAM_SPACES["breakout"]
    for c in candidates:
        for pname, (lo, hi, ptype, _) in space.items():
            val = c["params"][pname]
            assert lo <= val <= hi, f"{pname}={val} not in [{lo}, {hi}]"
            if ptype == "int":
                assert isinstance(val, int)


def test_generate_default_candidate():
    c = generate_default_candidate("breakout")
    assert c["logic_family_id"] == "breakout"
    assert c["candidate_id"] == "breakout_default"
    space = PARAM_SPACES["breakout"]
    for pname, (_, _, _, default) in space.items():
        assert c["params"][pname] == default


def test_family_timeframe_mapping():
    for family in PARAM_SPACES:
        assert family in FAMILY_TIMEFRAME, f"Missing timeframe mapping for {family}"


def test_ema_cd_param_space():
    assert "ema_crossover_cd" in PARAM_SPACES
    space = PARAM_SPACES["ema_crossover_cd"]
    assert "cooldown_bars" in space
    lo, hi, ptype, default = space["cooldown_bars"]
    assert ptype == "int"
    assert default == 10
    assert lo < hi


def test_ema_cd_default_candidate():
    c = generate_default_candidate("ema_crossover_cd")
    assert c["logic_family_id"] == "ema_crossover_cd"
    assert c["params"]["cooldown_bars"] == 10
    assert c["params"]["atr_stop_mult"] == 2.0


def test_ema_cd_candidate_generation():
    candidates = generate_candidates(families=["ema_crossover_cd"],
                                     n_per_family=5, seed=42)
    assert len(candidates) == 5
    for c in candidates:
        assert c["logic_family_id"] == "ema_crossover_cd"
        assert "cooldown_bars" in c["params"]
        assert isinstance(c["params"]["cooldown_bars"], int)
        space = PARAM_SPACES["ema_crossover_cd"]
        lo, hi, _, _ = space["cooldown_bars"]
        assert lo <= c["params"]["cooldown_bars"] <= hi
