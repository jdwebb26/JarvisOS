"""Tests for evidence classification and promotion eligibility.

These are the hard rules that prevent daily-data or synthetic-data
candidates from being confused with intraday execution-grade evidence.
"""

from strategy_factory.config import classify_evidence, EVIDENCE_TIERS


# ---------------------------------------------------------------------------
# classify_evidence tests
# ---------------------------------------------------------------------------

def test_synthetic_is_research_only():
    ev = classify_evidence("synthetic", "synthetic")
    assert ev["evidence_tier"] == "research_only"
    assert ev["promotion_eligible"] is False
    assert ev["max_stage"] == "CANDIDATE"
    assert ev["source_class"] == "synthetic"


def test_daily_real_is_research():
    ev = classify_evidence("real", "daily")
    assert ev["evidence_tier"] == "research"
    assert ev["promotion_eligible"] is False
    assert ev["max_stage"] == "CANDIDATE"
    assert ev["source_class"] == "market_data"


def test_daily_variants():
    """All daily-like granularities should classify as daily_real."""
    for gran in ("daily", "1d", "day"):
        ev = classify_evidence("real", gran)
        assert ev["evidence_tier"] == "research", f"Failed for {gran}"
        assert ev["promotion_eligible"] is False


def test_hourly_real_is_exploratory():
    ev = classify_evidence("real", "1h")
    assert ev["evidence_tier"] == "exploratory"
    assert ev["promotion_eligible"] is False
    assert ev["max_stage"] == "CANDIDATE"


def test_hourly_variants():
    for gran in ("1h", "hourly", "60m", "60min"):
        ev = classify_evidence("real", gran)
        assert ev["evidence_tier"] == "exploratory", f"Failed for {gran}"


def test_intraday_real_is_execution_grade():
    ev = classify_evidence("real", "1min_bar")
    assert ev["evidence_tier"] == "execution_grade"
    assert ev["promotion_eligible"] is True
    assert ev["max_stage"] == "BACKTESTED"
    assert ev["source_class"] == "market_data"


def test_intraday_variants():
    """All intraday granularities should be execution-grade."""
    for gran in ("1m", "1min", "1min_bar", "5m", "5min", "3m", "3min"):
        ev = classify_evidence("real", gran)
        assert ev["evidence_tier"] == "execution_grade", f"Failed for {gran}"
        assert ev["promotion_eligible"] is True


def test_unknown_granularity_is_conservative():
    """Unknown granularity with real data should be treated as daily (conservative)."""
    ev = classify_evidence("real", "weird_unknown_thing")
    assert ev["evidence_tier"] == "research"
    assert ev["promotion_eligible"] is False


# ---------------------------------------------------------------------------
# Promotion eligibility hard rules
# ---------------------------------------------------------------------------

def test_only_intraday_can_reach_backtested():
    """Only execution_grade evidence can have max_stage == BACKTESTED."""
    for tier_name, tier in EVIDENCE_TIERS.items():
        if tier_name == "intraday_real":
            assert tier["max_stage"] == "BACKTESTED"
            assert tier["promotion_eligible"] is True
        else:
            assert tier["max_stage"] == "CANDIDATE", f"{tier_name} should cap at CANDIDATE"
            assert tier["promotion_eligible"] is False, f"{tier_name} should not be promotion eligible"


def test_evidence_tier_hierarchy():
    """Verify the evidence tier ordering makes sense."""
    tiers = list(EVIDENCE_TIERS.keys())
    assert "synthetic" in tiers
    assert "daily_real" in tiers
    assert "hourly_real" in tiers
    assert "intraday_real" in tiers


# ---------------------------------------------------------------------------
# Stage capping integration tests
# ---------------------------------------------------------------------------

def test_stage_capped_by_evidence_daily():
    """Even if all gates pass, daily data cannot produce BACKTESTED stage."""
    ev = classify_evidence("real", "daily")
    max_stage = ev["max_stage"]

    # Simulate the stage logic from cli.py
    gate_pass = True
    robust = True
    stress_pass = True
    sim_pass = True

    if sim_pass and gate_pass and robust and stress_pass:
        stage = "BACKTESTED" if max_stage == "BACKTESTED" else "CANDIDATE"
    elif sim_pass:
        stage = "CANDIDATE"
    else:
        stage = "REJECTED"

    assert stage == "CANDIDATE"  # capped, not BACKTESTED


def test_stage_capped_by_evidence_synthetic():
    """Synthetic data can never produce BACKTESTED."""
    ev = classify_evidence("synthetic", "synthetic")
    max_stage = ev["max_stage"]

    gate_pass = True
    robust = True
    stress_pass = True
    sim_pass = True

    if sim_pass and gate_pass and robust and stress_pass:
        stage = "BACKTESTED" if max_stage == "BACKTESTED" else "CANDIDATE"
    elif sim_pass:
        stage = "CANDIDATE"
    else:
        stage = "REJECTED"

    assert stage == "CANDIDATE"


def test_stage_not_capped_for_intraday():
    """Intraday real data CAN produce BACKTESTED if all gates pass."""
    ev = classify_evidence("real", "1min_bar")
    max_stage = ev["max_stage"]

    gate_pass = True
    robust = True
    stress_pass = True
    sim_pass = True

    if sim_pass and gate_pass and robust and stress_pass:
        stage = "BACKTESTED" if max_stage == "BACKTESTED" else "CANDIDATE"
    elif sim_pass:
        stage = "CANDIDATE"
    else:
        stage = "REJECTED"

    assert stage == "BACKTESTED"


def test_rejected_regardless_of_evidence():
    """If sim fails, stage is always REJECTED regardless of evidence tier."""
    for gran in ("synthetic", "daily", "1h", "1min_bar"):
        source = "synthetic" if gran == "synthetic" else "real"
        ev = classify_evidence(source, gran)
        max_stage = ev["max_stage"]

        sim_pass = False
        gate_pass = True
        robust = True
        stress_pass = True

        if sim_pass and gate_pass and robust and stress_pass:
            stage = "BACKTESTED" if max_stage == "BACKTESTED" else "CANDIDATE"
        elif sim_pass:
            stage = "CANDIDATE"
        else:
            stage = "REJECTED"

        assert stage == "REJECTED"


# ---------------------------------------------------------------------------
# Registry entry evidence field tests
# ---------------------------------------------------------------------------

def test_registry_entry_includes_evidence(tmp_path):
    """Registry entries should include evidence classification."""
    import strategy_factory.artifacts as art_mod
    import json

    orig = art_mod.STRATEGIES_REGISTRY
    reg_path = tmp_path / "STRATEGIES.jsonl"
    art_mod.STRATEGIES_REGISTRY = reg_path

    try:
        evidence = {
            "data_source": "real",
            "data_granularity": "daily",
            "source_class": "market_data",
            "evidence_tier": "research",
            "promotion_eligible": False,
            "max_stage": "CANDIDATE",
            "fold_profile_used": "research",
            "gate_profile_used": "research",
        }

        entry = art_mod.append_to_strategy_registry(
            candidate_id="test_ev_001",
            logic_family_id="breakout",
            params={"lookback": 20},
            stage="CANDIDATE",
            score=0.7,
            gate_overall="FAIL",
            artifact_dir=tmp_path,
            data_source="real",
            fold_count=8,
            evidence=evidence,
        )

        assert "evidence" in entry
        assert entry["evidence"]["evidence_tier"] == "research"
        assert entry["evidence"]["promotion_eligible"] is False

        # Verify file contents
        parsed = json.loads(reg_path.read_text().strip())
        assert parsed["evidence"]["evidence_tier"] == "research"
        assert parsed["stage"] == "CANDIDATE"
    finally:
        art_mod.STRATEGIES_REGISTRY = orig


def test_provenance_linkage_includes_evidence(tmp_path):
    """Provenance linkage should include evidence classification."""
    from strategy_factory.artifacts import write_provenance_linkage
    import json

    evidence = {
        "data_source": "real",
        "data_granularity": "daily",
        "evidence_tier": "research",
        "promotion_eligible": False,
    }

    payload = write_provenance_linkage(
        tmp_path,
        candidate_id="test_prov_001",
        status="PASS",
        gate_overall="FAIL",
        fold_count=8,
        evidence=evidence,
    )

    assert "evidence" in payload
    assert payload["evidence"]["evidence_tier"] == "research"

    # Verify file
    linkage = json.loads((tmp_path / "provenance_linkage.json").read_text())
    assert linkage["evidence"]["promotion_eligible"] is False
