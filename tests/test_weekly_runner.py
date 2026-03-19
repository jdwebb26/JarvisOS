"""Tests for weekly runner and forward_validation schema."""

import json
from pathlib import Path

import strategy_factory.artifacts as art_mod
from strategy_factory.analysis import compute_candidate_signature
from strategy_factory.weekly_runner import (
    _build_forward_validation,
    _build_weekly_report,
    _history_snapshot,
)


def _write_history(tmp_path, records):
    """Write test records to a temp CANDIDATE_HISTORY.jsonl."""
    hist_path = tmp_path / "CANDIDATE_HISTORY.jsonl"
    with open(hist_path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return hist_path


# ---------------------------------------------------------------------------
# Forward validation schema
# ---------------------------------------------------------------------------

def test_forward_validation_schema():
    """forward_validation.json must answer all required questions."""
    fv = _build_forward_validation(
        cycle_id="test_cycle",
        run_ids=set(),
        art_dir=None,
        n_candidates=10,
    )
    assert fv["cycle_id"] == "test_cycle"
    assert "generated_at" in fv
    assert "run_ids" in fv
    assert "families_run" in fv
    assert "questions" in fv
    assert "shortlist_snapshot" in fv

    q = fv["questions"]
    required_questions = [
        "cd_vs_baseline",
        "cooldown_regime_present",
        "breakout_coverage",
        "hourly_status",
        "priority_family",
        "monitor_family",
        "new_shortlist_entries",
        "new_entry_signatures",
        "degraded_prior_ideas",
    ]
    for rq in required_questions:
        assert rq in q, f"missing question: {rq}"

    fr = fv["families_run"]
    required_families = [
        "ema_crossover_daily",
        "ema_crossover_cd_daily",
        "breakout_daily",
        "hourly_all",
    ]
    for rf in required_families:
        assert rf in fr, f"missing family: {rf}"


def test_forward_validation_deterministic():
    fv1 = _build_forward_validation("det", set(), None, 10)
    fv2 = _build_forward_validation("det", set(), None, 10)
    assert fv1["questions"] == fv2["questions"]
    assert fv1["shortlist_snapshot"] == fv2["shortlist_snapshot"]


def test_forward_validation_with_fake_run_ids():
    """With fake run_ids that don't match history, should handle gracefully."""
    fv = _build_forward_validation(
        cycle_id="fake_test",
        run_ids={"run_nonexistent_abc"},
        art_dir=None,
        n_candidates=5,
    )
    assert fv["questions"]["cd_vs_baseline"] == "insufficient_data"
    assert fv["questions"]["hourly_status"] == "no_data"
    assert fv["questions"]["degraded_prior_ideas"] == []


def test_forward_validation_shortlist_snapshot():
    fv = _build_forward_validation("snap_test", set(), None, 10)
    snap = fv["shortlist_snapshot"]
    assert "total_ideas" in snap
    assert "top_5" in snap
    assert isinstance(snap["top_5"], list)
    for idea in snap["top_5"]:
        assert "signature" in idea
        assert "family" in idea
        assert "appearances" in idea
        assert "best_score" in idea
        assert "classification" in idea


# ---------------------------------------------------------------------------
# Forward validation with mock history
# ---------------------------------------------------------------------------

def _make_record(run_id, dataset_id, family, status, score, params=None):
    """Create a minimal candidate history record."""
    params = params or {"atr_stop_mult": 2.0}
    return {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "candidate_id": f"c_{run_id}_{family}",
        "candidate_signature": compute_candidate_signature(family, params),
        "family": family,
        "params": params,
        "status": status,
        "reject_reason": "NO_TRADES" if status != "PASS" else None,
        "stage": "CANDIDATE" if status == "PASS" else "REJECTED",
        "stage_reason": "evidence_tier_cap:research" if status == "PASS" else "gate_fail",
        "score": score,
        "gate_overall": "PASS" if status == "PASS" else "FAIL",
        "evidence_tier": "research",
        "evidence": {
            "evidence_tier": "research",
            "data_granularity": "daily",
            "promotion_eligible": False,
        },
    }


def test_forward_validation_cd_outperforms(tmp_path):
    """CD outperforms baseline when cd top_score > ema top_score."""
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.5),
        _make_record("run_a", "NQ_daily", "ema_crossover_cd", "PASS", 0.7),
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
    try:
        fv = _build_forward_validation("test", {"run_a"}, None, 5)
        assert fv["questions"]["cd_vs_baseline"] == "cd_higher_top_score"
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_forward_validation_baseline_higher(tmp_path):
    """Baseline wins when ema top and median > cd."""
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.8),
        _make_record("run_a", "NQ_daily", "ema_crossover_cd", "PASS", 0.4),
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
    try:
        fv = _build_forward_validation("test", {"run_a"}, None, 5)
        assert fv["questions"]["cd_vs_baseline"] == "baseline_higher"
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_forward_validation_breakout_survivors(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        _make_record("run_a", "NQ_daily", "breakout", "PASS", 0.6,
                      {"lookback": 20, "atr_stop_mult": 1.5}),
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
    try:
        fv = _build_forward_validation("test", {"run_a"}, None, 5)
        assert fv["questions"]["breakout_coverage"] == "breakout_has_survivors"
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_forward_validation_breakout_all_fail(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        _make_record("run_a", "NQ_daily", "breakout", "REJECT", 0.0),
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
    try:
        fv = _build_forward_validation("test", {"run_a"}, None, 5)
        assert fv["questions"]["breakout_coverage"] == "breakout_all_fail"
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_forward_validation_hourly_signal(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        _make_record("run_a", "NQ_hourly", "ema_crossover", "PASS", 0.65),
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
    try:
        fv = _build_forward_validation("test", {"run_a"}, None, 5)
        assert fv["questions"]["hourly_status"] == "showing_signal"
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_forward_validation_hourly_shallow(tmp_path):
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        _make_record("run_a", "NQ_hourly", "ema_crossover", "PASS", 0.3),
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
    try:
        fv = _build_forward_validation("test", {"run_a"}, None, 5)
        assert fv["questions"]["hourly_status"] == "still_shallow"
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_forward_validation_degraded_idea(tmp_path):
    """Detect degradation when this cycle's score < 85% of historical avg."""
    orig = art_mod.CANDIDATE_HISTORY
    params = {"atr_stop_mult": 2.5}
    sig = compute_candidate_signature("ema_crossover", params)
    records = [
        # Historical: appeared in run_old with score 0.80
        _make_record("run_old", "NQ_daily", "ema_crossover", "PASS", 0.80, params),
        # This cycle: same sig but score dropped to 0.50
        _make_record("run_new", "NQ_daily", "ema_crossover", "PASS", 0.50, params),
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
    try:
        fv = _build_forward_validation("test", {"run_new"}, None, 5)
        degraded = fv["questions"]["degraded_prior_ideas"]
        assert len(degraded) == 1
        assert degraded[0]["signature"] == sig
        assert degraded[0]["this_cycle_score"] == 0.50
        assert degraded[0]["drop_pct"] > 0
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_forward_validation_no_degradation(tmp_path):
    """No degradation when score stays stable."""
    orig = art_mod.CANDIDATE_HISTORY
    params = {"atr_stop_mult": 2.5}
    records = [
        _make_record("run_old", "NQ_daily", "ema_crossover", "PASS", 0.70, params),
        _make_record("run_new", "NQ_daily", "ema_crossover", "PASS", 0.68, params),
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
    try:
        fv = _build_forward_validation("test", {"run_new"}, None, 5)
        assert fv["questions"]["degraded_prior_ideas"] == []
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_forward_validation_new_shortlist_entry(tmp_path):
    """Detect new entries that first appeared this cycle."""
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        _make_record("run_a", "NQ_daily", "breakout", "PASS", 0.6,
                      {"lookback": 30, "atr_stop_mult": 1.5}),
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
    try:
        fv = _build_forward_validation("test", {"run_a"}, None, 5)
        assert fv["questions"]["new_shortlist_entries"] >= 1
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_forward_validation_family_summary_rejection_reasons(tmp_path):
    """Family summaries include rejection reasons."""
    orig = art_mod.CANDIDATE_HISTORY
    records = [
        _make_record("run_a", "NQ_daily", "ema_crossover", "REJECT", 0.0),
        _make_record("run_a", "NQ_daily", "ema_crossover", "REJECT", 0.0),
        _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.5),
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
    try:
        fv = _build_forward_validation("test", {"run_a"}, None, 5)
        ema = fv["families_run"]["ema_crossover_daily"]
        assert ema["evaluated"] == 3
        assert ema["passed"] == 1
        assert ema["rejected"] == 2
        assert "NO_TRADES" in ema["rejection_reasons"]
    finally:
        art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# Weekly report
# ---------------------------------------------------------------------------

def test_weekly_report_produces_markdown():
    fv = _build_forward_validation("rpt_test", set(), None, 10)
    report = _build_weekly_report(fv, None)
    assert isinstance(report, str)
    assert report.startswith("# Weekly Research Report")
    assert "## Family Results" in report
    assert "## Forward Validation Questions" in report
    assert "## Top Ideas" in report
    assert "cd vs baseline" in report
    assert "degraded" in report.lower()


def test_weekly_report_with_degraded_ideas(tmp_path):
    """Report renders degraded ideas section when they exist."""
    orig = art_mod.CANDIDATE_HISTORY
    params = {"atr_stop_mult": 2.5}
    records = [
        _make_record("run_old", "NQ_daily", "ema_crossover", "PASS", 0.80, params),
        _make_record("run_new", "NQ_daily", "ema_crossover", "PASS", 0.40, params),
    ]
    art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
    try:
        fv = _build_forward_validation("test", {"run_new"}, None, 5)
        report = _build_weekly_report(fv, None)
        assert "Degraded Prior Ideas" in report
        assert "dropped" in report
    finally:
        art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# History snapshot
# ---------------------------------------------------------------------------

def test_history_snapshot():
    snap = _history_snapshot()
    assert "count" in snap
    assert "run_ids" in snap
    assert isinstance(snap["count"], int)
    assert isinstance(snap["run_ids"], set)
