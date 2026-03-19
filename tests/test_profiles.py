"""Tests for metadata-driven fold and gate profile selection.

Verifies that:
- Fold profile is selected by evidence tier, not bar count
- Gate profile is selected by evidence tier
- Daily data cannot accidentally use intraday gate profile
- Intraday metadata gets execution-grade profile
- Profiles are recorded in artifacts
"""

from strategy_factory.config import (
    select_fold_profile,
    select_gate_profile,
    FOLD_PROFILES,
    GATE_PROFILES,
    classify_evidence,
)
from strategy_factory.gates import evaluate_fold_gates, evaluate_all_folds


# ---------------------------------------------------------------------------
# Fold profile selection
# ---------------------------------------------------------------------------

def test_fold_profile_synthetic():
    spec, name = select_fold_profile("research_only")
    assert name == "research_only"
    assert spec["train_len"] == 5000
    assert spec["minimum_any_fold_trades"] == 50


def test_fold_profile_daily_real():
    spec, name = select_fold_profile("research")
    assert name == "research"
    assert spec["train_len"] == 500
    assert spec["test_len"] == 375
    assert spec["minimum_any_fold_trades"] == 1


def test_fold_profile_hourly_real():
    spec, name = select_fold_profile("exploratory")
    assert name == "exploratory"
    assert spec["train_len"] == 800
    assert spec["minimum_any_fold_trades"] == 5


def test_fold_profile_intraday_real():
    spec, name = select_fold_profile("execution_grade")
    assert name == "execution_grade"
    assert spec["train_len"] == 5000
    assert spec["minimum_any_fold_trades"] == 50


def test_fold_profile_unknown_falls_back():
    spec, name = select_fold_profile("unknown_tier")
    assert name == "research_only"


def test_fold_profiles_all_have_required_keys():
    required = {"mode", "train_len", "test_len", "purge_len",
                "retrain_cadence", "n_folds", "minimum_any_fold_trades"}
    for tier_name, profile in FOLD_PROFILES.items():
        missing = required - set(profile.keys())
        assert not missing, f"{tier_name} missing: {missing}"


# ---------------------------------------------------------------------------
# Gate profile selection
# ---------------------------------------------------------------------------

def test_gate_profile_synthetic():
    gp, name = select_gate_profile("research_only")
    assert name == "research_only"
    assert gp["min_trades_per_oos_fold"] == 50
    assert gp["sharpe_floor"] == 0.8


def test_gate_profile_daily_real():
    gp, name = select_gate_profile("research")
    assert name == "research"
    assert gp["min_trades_per_oos_fold"] == 1
    assert gp["sharpe_floor"] == 0.3  # lower than execution
    assert gp["sortino_floor"] == 0.5


def test_gate_profile_hourly_real():
    gp, name = select_gate_profile("exploratory")
    assert name == "exploratory"
    assert gp["min_trades_per_oos_fold"] == 5
    assert gp["sharpe_floor"] == 0.5


def test_gate_profile_intraday():
    gp, name = select_gate_profile("execution_grade")
    assert name == "execution_grade"
    assert gp["min_trades_per_oos_fold"] == 50
    assert gp["sharpe_floor"] == 0.8
    assert gp["sortino_floor"] == 1.5


def test_gate_profile_unknown_falls_back():
    gp, name = select_gate_profile("unknown_tier")
    assert name == "research_only"


def test_gate_profiles_all_have_required_keys():
    required = {"pf_floor", "min_trades_per_oos_fold", "max_drawdown_proxy",
                "sharpe_floor", "sortino_floor"}
    for tier_name, profile in GATE_PROFILES.items():
        missing = required - set(profile.keys())
        assert not missing, f"{tier_name} missing: {missing}"


# ---------------------------------------------------------------------------
# Cross-profile isolation: daily cannot use intraday gates
# ---------------------------------------------------------------------------

def test_daily_data_cannot_use_intraday_gate_profile():
    """classify_evidence for daily gives 'research' tier, which selects
    research gate profile — NOT execution_grade."""
    ev = classify_evidence("real", "daily")
    gp, name = select_gate_profile(ev["evidence_tier"])
    assert name == "research"
    assert gp["min_trades_per_oos_fold"] == 1
    assert gp["sharpe_floor"] < 0.8  # less strict than execution


def test_intraday_data_gets_execution_gate_profile():
    ev = classify_evidence("real", "1min_bar")
    gp, name = select_gate_profile(ev["evidence_tier"])
    assert name == "execution_grade"
    assert gp["min_trades_per_oos_fold"] == 50
    assert gp["sharpe_floor"] == 0.8


def test_synthetic_data_gets_research_only_gate_profile():
    ev = classify_evidence("synthetic", "synthetic")
    gp, name = select_gate_profile(ev["evidence_tier"])
    assert name == "research_only"


# ---------------------------------------------------------------------------
# Gate evaluation with profile override
# ---------------------------------------------------------------------------

def test_evaluate_fold_gates_with_research_profile():
    """Research gate profile: sharpe 0.3, sortino 0.5, min_trades 1."""
    gp, _ = select_gate_profile("research")
    metrics = {
        "fold_id": 0, "trades": 3, "profit_factor": 2.0,
        "sharpe": 0.4, "sortino": 0.6, "max_drawdown_proxy": 100.0,
    }
    result = evaluate_fold_gates(metrics, "multi_hour_overnight",
                                 gate_profile=gp)
    # Should pass: sharpe 0.4 >= 0.3, sortino 0.6 >= 0.5, trades 3 >= 1
    assert result["overall"] == "PASS"
    assert result["sharpe"]["threshold"] == 0.3
    assert result["sortino"]["threshold"] == 0.5
    assert result["min_trades_per_oos_fold"]["threshold"] == 1


def test_evaluate_fold_gates_with_execution_profile():
    """Same metrics should FAIL under execution-grade gates."""
    gp, _ = select_gate_profile("execution_grade")
    metrics = {
        "fold_id": 0, "trades": 3, "profit_factor": 2.0,
        "sharpe": 0.4, "sortino": 0.6, "max_drawdown_proxy": 100.0,
    }
    result = evaluate_fold_gates(metrics, "multi_hour_overnight",
                                 gate_profile=gp)
    # Should fail: trades 3 < 50, sharpe 0.4 < 0.8
    assert result["overall"] == "FAIL"
    assert result["min_trades_per_oos_fold"]["pass"] is False
    assert result["sharpe"]["pass"] is False


def test_evaluate_fold_gates_without_profile_uses_timeframe():
    """When no gate_profile provided, falls back to TIMEFRAME_GATES."""
    metrics = {
        "fold_id": 0, "trades": 200, "profit_factor": 2.0,
        "sharpe": 1.5, "sortino": 3.0, "max_drawdown_proxy": 50.0,
    }
    result = evaluate_fold_gates(metrics, "5_60m_intraday",
                                 gate_profile=None)
    assert result["overall"] == "PASS"
    # Threshold should come from TIMEFRAME_GATES["5_60m_intraday"]
    assert result["min_trades_per_oos_fold"]["threshold"] == 150


# ---------------------------------------------------------------------------
# End-to-end: evidence tier → fold profile + gate profile
# ---------------------------------------------------------------------------

def test_full_profile_chain_daily():
    """Daily real data: research evidence → research fold + research gates."""
    ev = classify_evidence("real", "daily")
    fp, fp_name = select_fold_profile(ev["evidence_tier"])
    gp, gp_name = select_gate_profile(ev["evidence_tier"])

    assert fp_name == "research"
    assert gp_name == "research"
    assert fp["train_len"] == 500
    assert gp["sharpe_floor"] == 0.3
    assert ev["promotion_eligible"] is False


def test_full_profile_chain_intraday():
    """Intraday real data: execution_grade evidence → execution fold + gates."""
    ev = classify_evidence("real", "1m")
    fp, fp_name = select_fold_profile(ev["evidence_tier"])
    gp, gp_name = select_gate_profile(ev["evidence_tier"])

    assert fp_name == "execution_grade"
    assert gp_name == "execution_grade"
    assert fp["train_len"] == 5000
    assert gp["sharpe_floor"] == 0.8
    assert ev["promotion_eligible"] is True
