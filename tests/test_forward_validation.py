"""Tests for forward_validation module (extracted from weekly_runner)."""

import json
from pathlib import Path

import strategy_factory.artifacts as art_mod
from strategy_factory.analysis import compute_candidate_signature
from strategy_factory.forward_validation import (
    build_forward_validation,
    build_weekly_report,
    build_operator_packet,
    history_snapshot,
    _classify_idea,
    _family_is_honest_failure,
)


def _write_history(tmp_path, records):
    """Write test records to a temp CANDIDATE_HISTORY.jsonl."""
    hist_path = tmp_path / "CANDIDATE_HISTORY.jsonl"
    with open(hist_path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return hist_path


def _make_record(run_id, dataset_id, family, status, score, params=None,
                 promotion_eligible=False):
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
            "promotion_eligible": promotion_eligible,
        },
    }


# ---------------------------------------------------------------------------
# build_forward_validation — schema tests
# ---------------------------------------------------------------------------

class TestBuildForwardValidation:
    """Verify build_forward_validation produces the correct schema."""

    def test_schema_keys(self):
        fv = build_forward_validation("test_cycle", set(), None, 10)
        assert fv["cycle_id"] == "test_cycle"
        assert "generated_at" in fv
        assert "run_ids" in fv
        assert "families_run" in fv
        assert "questions" in fv
        assert "shortlist_snapshot" in fv

    def test_summary_block_present(self):
        fv = build_forward_validation("sum_test", set(), None, 10)
        assert "summary" in fv
        s = fv["summary"]
        required = [
            "priority_family", "monitor_family", "drop_family",
            "review_worthy_now", "strongest_dataset", "weakest_dataset",
            "notable_change", "degraded_count", "honest_failures",
        ]
        for key in required:
            assert key in s, f"missing summary field: {key}"

    def test_summary_types(self):
        fv = build_forward_validation("type_test", set(), None, 10)
        s = fv["summary"]
        assert isinstance(s["review_worthy_now"], bool)
        assert isinstance(s["degraded_count"], int)
        assert isinstance(s["honest_failures"], list)
        assert s["drop_family"] is None or isinstance(s["drop_family"], str)
        assert isinstance(s["notable_change"], str)

    def test_all_questions_present(self):
        fv = build_forward_validation("q_test", set(), None, 10)
        required = [
            "cd_vs_baseline", "cooldown_regime_present", "breakout_coverage",
            "hourly_status", "priority_family", "monitor_family",
            "new_shortlist_entries", "new_entry_signatures",
            "degraded_prior_ideas",
        ]
        for key in required:
            assert key in fv["questions"], f"missing question: {key}"

    def test_all_families_present(self):
        fv = build_forward_validation("f_test", set(), None, 10)
        for key in ["ema_crossover_daily", "ema_crossover_cd_daily",
                     "breakout_daily", "hourly_all"]:
            assert key in fv["families_run"], f"missing family: {key}"

    def test_deterministic(self):
        fv1 = build_forward_validation("det", set(), None, 10)
        fv2 = build_forward_validation("det", set(), None, 10)
        assert fv1["questions"] == fv2["questions"]
        assert fv1["shortlist_snapshot"] == fv2["shortlist_snapshot"]
        assert fv1["summary"] == fv2["summary"]

    def test_fake_run_ids_graceful(self):
        fv = build_forward_validation("fake", {"run_nonexistent"}, None, 5)
        assert fv["questions"]["cd_vs_baseline"] == "insufficient_data"
        assert fv["questions"]["hourly_status"] == "no_data"
        assert fv["questions"]["degraded_prior_ideas"] == []

    def test_shortlist_snapshot_shape(self):
        fv = build_forward_validation("snap", set(), None, 10)
        snap = fv["shortlist_snapshot"]
        assert "total_ideas" in snap
        assert isinstance(snap["top_5"], list)
        for idea in snap["top_5"]:
            for field in ("signature", "family", "appearances",
                          "best_score", "classification"):
                assert field in idea

    def test_classification_in_top_5(self):
        fv = build_forward_validation("cls_test", set(), None, 10)
        valid_labels = {"structural_improvement", "evidence_capped",
                        "sample_size_illusion"}
        for idea in fv["shortlist_snapshot"]["top_5"]:
            assert idea["classification"] in valid_labels

    def test_no_data_not_review_worthy(self):
        fv = build_forward_validation("empty", set(), None, 10)
        # With no cycle data, review_worthy depends on historical ideas
        assert isinstance(fv["summary"]["review_worthy_now"], bool)


# ---------------------------------------------------------------------------
# build_forward_validation — with mock history
# ---------------------------------------------------------------------------

class TestForwardValidationWithHistory:

    def test_cd_outperforms(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.5),
            _make_record("run_a", "NQ_daily", "ema_crossover_cd", "PASS", 0.7),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            assert fv["questions"]["cd_vs_baseline"] == "cd_higher_top_score"
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_baseline_higher(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.8),
            _make_record("run_a", "NQ_daily", "ema_crossover_cd", "PASS", 0.4),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            assert fv["questions"]["cd_vs_baseline"] == "baseline_higher"
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_breakout_survivors(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_daily", "breakout", "PASS", 0.6,
                          {"lookback": 20, "atr_stop_mult": 1.5}),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            assert fv["questions"]["breakout_coverage"] == "breakout_has_survivors"
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_breakout_all_fail(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_daily", "breakout", "REJECT", 0.0),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            assert fv["questions"]["breakout_coverage"] == "breakout_all_fail"
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_hourly_signal(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_hourly", "ema_crossover", "PASS", 0.65),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            assert fv["questions"]["hourly_status"] == "showing_signal"
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_hourly_shallow(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_hourly", "ema_crossover", "PASS", 0.3),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            assert fv["questions"]["hourly_status"] == "still_shallow"
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_degraded_idea(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        params = {"atr_stop_mult": 2.5}
        sig = compute_candidate_signature("ema_crossover", params)
        records = [
            _make_record("run_old", "NQ_daily", "ema_crossover", "PASS", 0.80, params),
            _make_record("run_new", "NQ_daily", "ema_crossover", "PASS", 0.50, params),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_new"}, None, 5)
            degraded = fv["questions"]["degraded_prior_ideas"]
            assert len(degraded) == 1
            assert degraded[0]["signature"] == sig
            assert degraded[0]["this_cycle_score"] == 0.50
            assert degraded[0]["drop_pct"] > 0
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_no_degradation(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        params = {"atr_stop_mult": 2.5}
        records = [
            _make_record("run_old", "NQ_daily", "ema_crossover", "PASS", 0.70, params),
            _make_record("run_new", "NQ_daily", "ema_crossover", "PASS", 0.68, params),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_new"}, None, 5)
            assert fv["questions"]["degraded_prior_ideas"] == []
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_new_shortlist_entry(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_daily", "breakout", "PASS", 0.6,
                          {"lookback": 30, "atr_stop_mult": 1.5}),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            assert fv["questions"]["new_shortlist_entries"] >= 1
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_family_summary_rejection_reasons(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_daily", "ema_crossover", "REJECT", 0.0),
            _make_record("run_a", "NQ_daily", "ema_crossover", "REJECT", 0.0),
            _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.5),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            ema = fv["families_run"]["ema_crossover_daily"]
            assert ema["evaluated"] == 3
            assert ema["passed"] == 1
            assert ema["rejected"] == 2
            assert "NO_TRADES" in ema["rejection_reasons"]
        finally:
            art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# Summary block scenarios
# ---------------------------------------------------------------------------

class TestSummaryBlock:

    def test_honest_failure_detected(self, tmp_path):
        """When breakout has candidates but zero passes, it is an honest failure."""
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_daily", "breakout", "REJECT", 0.0),
            _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.6),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            assert "breakout_daily" in fv["summary"]["honest_failures"]
            assert fv["summary"]["drop_family"] == "breakout_daily"
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_no_honest_failure_when_passes_exist(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_daily", "breakout", "PASS", 0.6,
                          {"lookback": 20, "atr_stop_mult": 1.5}),
            _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.5),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            assert fv["summary"]["honest_failures"] == []
            assert fv["summary"]["drop_family"] is None
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_review_worthy_multi_run(self, tmp_path):
        """review_worthy_now is True when a multi-run survivor has score >= 0.5."""
        orig = art_mod.CANDIDATE_HISTORY
        params = {"atr_stop_mult": 2.0}
        records = [
            _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.6, params),
            _make_record("run_b", "NQ_daily", "ema_crossover", "PASS", 0.65, params),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a", "run_b"}, None, 5)
            assert fv["summary"]["review_worthy_now"] is True
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_not_review_worthy_single_run(self, tmp_path):
        """Single-run survivor is not review-worthy."""
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.9),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            assert fv["summary"]["review_worthy_now"] is False
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_not_review_worthy_low_score(self, tmp_path):
        """Multi-run survivor with low score is not review-worthy."""
        orig = art_mod.CANDIDATE_HISTORY
        params = {"atr_stop_mult": 2.0}
        records = [
            _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.2, params),
            _make_record("run_b", "NQ_daily", "ema_crossover", "PASS", 0.3, params),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a", "run_b"}, None, 5)
            assert fv["summary"]["review_worthy_now"] is False
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_strongest_weakest_dataset(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.8),
            _make_record("run_a", "NQ_hourly", "ema_crossover", "PASS", 0.3),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            assert fv["summary"]["strongest_dataset"] == "NQ_daily"
            assert fv["summary"]["weakest_dataset"] == "NQ_hourly"
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_notable_change_degradation(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        params = {"atr_stop_mult": 2.5}
        records = [
            _make_record("run_old", "NQ_daily", "ema_crossover", "PASS", 0.80, params),
            _make_record("run_new", "NQ_daily", "ema_crossover", "PASS", 0.50, params),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_new"}, None, 5)
            assert "degraded" in fv["summary"]["notable_change"]
            assert fv["summary"]["degraded_count"] == 1
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_notable_change_new_entries(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_daily", "breakout", "PASS", 0.6,
                          {"lookback": 30, "atr_stop_mult": 1.5}),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            assert "new shortlist" in fv["summary"]["notable_change"]
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_notable_change_stable(self):
        fv = build_forward_validation("stable", set(), None, 10)
        # With no cycle data matching, notable_change depends on history
        assert isinstance(fv["summary"]["notable_change"], str)


# ---------------------------------------------------------------------------
# Idea classification
# ---------------------------------------------------------------------------

class TestClassifyIdea:

    def test_single_appearance_is_sample_size(self):
        idea = {"appearances": 1, "distinct_runs": 1,
                "promotion_eligible": True}
        assert _classify_idea(idea, set()) == "sample_size_illusion"

    def test_multi_run_not_eligible_is_capped(self):
        idea = {"appearances": 3, "distinct_runs": 2,
                "promotion_eligible": False}
        assert _classify_idea(idea, set()) == "evidence_capped"

    def test_multi_run_eligible_is_structural(self):
        idea = {"appearances": 3, "distinct_runs": 2,
                "promotion_eligible": True}
        assert _classify_idea(idea, set()) == "structural_improvement"

    def test_multi_appearance_single_run_is_sample_size(self):
        idea = {"appearances": 3, "distinct_runs": 1,
                "promotion_eligible": True}
        assert _classify_idea(idea, set()) == "sample_size_illusion"


class TestFamilyIsHonestFailure:

    def test_no_records_is_not_failure(self):
        assert _family_is_honest_failure({"status": "no_records"}) is False

    def test_all_rejected_is_failure(self):
        assert _family_is_honest_failure(
            {"evaluated": 5, "passed": 0, "rejected": 5}) is True

    def test_some_passed_is_not_failure(self):
        assert _family_is_honest_failure(
            {"evaluated": 5, "passed": 2, "rejected": 3}) is False


# ---------------------------------------------------------------------------
# build_weekly_report
# ---------------------------------------------------------------------------

class TestBuildWeeklyReport:

    def test_produces_markdown(self):
        fv = build_forward_validation("rpt_test", set(), None, 10)
        report = build_weekly_report(fv, None)
        assert isinstance(report, str)
        assert report.startswith("# Weekly Research Report")
        assert "## Family Results" in report
        assert "## Forward Validation Questions" in report
        assert "## Top Ideas" in report
        assert "cd vs baseline" in report
        assert "degraded" in report.lower()

    def test_decision_summary_section(self):
        fv = build_forward_validation("dec_test", set(), None, 10)
        report = build_weekly_report(fv, None)
        assert "## Decision Summary" in report
        assert "Priority this week" in report
        assert "Monitor only" in report
        assert "Drop / deprioritize" in report
        assert "Strongest dataset" in report
        assert "Weakest dataset" in report
        assert "Notable change" in report

    def test_not_review_worthy_stated_plainly(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        # Single-run survivor only — not review-worthy
        records = [
            _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.6),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("no_review", {"run_a"}, None, 10)
            report = build_weekly_report(fv, None)
            assert "Nothing is review-worthy right now" in report
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_review_worthy_stated(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        params = {"atr_stop_mult": 2.0}
        records = [
            _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.6, params),
            _make_record("run_b", "NQ_daily", "ema_crossover", "PASS", 0.65, params),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a", "run_b"}, None, 5)
            report = build_weekly_report(fv, None)
            assert "Review-worthy candidates exist" in report
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_classification_column_in_table(self):
        fv = build_forward_validation("cls_test", set(), None, 10)
        report = build_weekly_report(fv, None)
        assert "classification" in report

    def test_classification_legend(self):
        fv = build_forward_validation("legend_test", set(), None, 10)
        report = build_weekly_report(fv, None)
        assert "structural_improvement" in report
        assert "evidence_capped" in report
        assert "sample_size_illusion" in report

    def test_honest_failures_section(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_daily", "breakout", "REJECT", 0.0),
            _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.6),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            report = build_weekly_report(fv, None)
            assert "Honest Failures" in report
            assert "breakout_daily" in report
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_with_degraded_ideas(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        params = {"atr_stop_mult": 2.5}
        records = [
            _make_record("run_old", "NQ_daily", "ema_crossover", "PASS", 0.80, params),
            _make_record("run_new", "NQ_daily", "ema_crossover", "PASS", 0.40, params),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_new"}, None, 5)
            report = build_weekly_report(fv, None)
            assert "Degraded Prior Ideas" in report
            assert "dropped" in report
        finally:
            art_mod.CANDIDATE_HISTORY = orig


# ---------------------------------------------------------------------------
# history_snapshot
# ---------------------------------------------------------------------------

class TestHistorySnapshot:

    def test_shape(self):
        snap = history_snapshot()
        assert "count" in snap
        assert "run_ids" in snap
        assert isinstance(snap["count"], int)
        assert isinstance(snap["run_ids"], set)


# ---------------------------------------------------------------------------
# Backward-compat: old private names still importable from weekly_runner
# ---------------------------------------------------------------------------

class TestBackwardCompat:

    def test_private_aliases_importable(self):
        from strategy_factory.weekly_runner import (
            _build_forward_validation,
            _build_weekly_report,
            _history_snapshot,
        )
        assert _build_forward_validation is build_forward_validation
        assert _build_weekly_report is build_weekly_report
        assert _history_snapshot is history_snapshot


# ---------------------------------------------------------------------------
# Operator packet
# ---------------------------------------------------------------------------

class TestOperatorPacketSchema:
    """Verify operator_packet.json schema completeness."""

    def test_all_required_fields(self):
        fv = build_forward_validation("pkt_test", set(), None, 10)
        pkt = build_operator_packet(fv, None)
        required = [
            "cycle_id", "generated_at", "priority_family", "monitor_family",
            "drop_family", "review_worthy_now", "strongest_dataset",
            "weakest_dataset", "notable_change", "degraded_count",
            "honest_failures", "top_ideas", "action_recommendation",
            "operator_status", "supporting_artifacts",
        ]
        for key in required:
            assert key in pkt, f"missing field: {key}"

    def test_field_types(self):
        fv = build_forward_validation("type_test", set(), None, 10)
        pkt = build_operator_packet(fv, None)
        assert isinstance(pkt["cycle_id"], str)
        assert isinstance(pkt["generated_at"], str)
        assert isinstance(pkt["review_worthy_now"], bool)
        assert isinstance(pkt["degraded_count"], int)
        assert isinstance(pkt["honest_failures"], list)
        assert isinstance(pkt["top_ideas"], list)
        assert isinstance(pkt["action_recommendation"], str)
        assert pkt["operator_status"] in ("review", "monitor", "hold")
        assert isinstance(pkt["supporting_artifacts"], dict)
        assert pkt["drop_family"] is None or isinstance(pkt["drop_family"], str)

    def test_supporting_artifacts_keys(self):
        fv = build_forward_validation("art_test", set(), None, 10)
        pkt = build_operator_packet(fv, None)
        expected = {"forward_validation", "weekly_report", "watchlist",
                    "review_queue", "candidate_packets"}
        assert set(pkt["supporting_artifacts"].keys()) == expected

    def test_top_ideas_max_3(self):
        fv = build_forward_validation("cap_test", set(), None, 10)
        pkt = build_operator_packet(fv, None)
        assert len(pkt["top_ideas"]) <= 3

    def test_top_ideas_entry_shape(self):
        fv = build_forward_validation("shape_test", set(), None, 10)
        pkt = build_operator_packet(fv, None)
        required_fields = {"signature", "family", "best_score",
                           "appearances", "distinct_runs", "classification"}
        for idea in pkt["top_ideas"]:
            assert set(idea.keys()) == required_fields

    def test_inherits_cycle_id(self):
        fv = build_forward_validation("inherit_test", set(), None, 10)
        pkt = build_operator_packet(fv, None)
        assert pkt["cycle_id"] == "inherit_test"
        assert pkt["generated_at"] == fv["generated_at"]


class TestOperatorStatus:

    def test_review_when_worthy(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        params = {"atr_stop_mult": 2.0}
        records = [
            _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.6, params),
            _make_record("run_b", "NQ_daily", "ema_crossover", "PASS", 0.65, params),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a", "run_b"}, None, 5)
            pkt = build_operator_packet(fv, None)
            assert pkt["operator_status"] == "review"
            assert "Review" in pkt["action_recommendation"]
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_monitor_when_ideas_but_not_worthy(self, tmp_path):
        """Single-run survivors exist but none are review-worthy."""
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.6),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            pkt = build_operator_packet(fv, None)
            assert pkt["operator_status"] == "monitor"
            assert "monitoring" in pkt["action_recommendation"].lower()
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_hold_when_no_survivors(self, tmp_path):
        """All candidates failed — hold."""
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_daily", "ema_crossover", "REJECT", 0.0),
            _make_record("run_a", "NQ_daily", "breakout", "REJECT", 0.0),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            pkt = build_operator_packet(fv, None)
            assert pkt["operator_status"] == "hold"
            assert "Hold" in pkt["action_recommendation"]
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_drop_family_appended_to_recommendation(self, tmp_path):
        orig = art_mod.CANDIDATE_HISTORY
        records = [
            _make_record("run_a", "NQ_daily", "breakout", "REJECT", 0.0),
            _make_record("run_a", "NQ_daily", "ema_crossover", "PASS", 0.6),
        ]
        art_mod.CANDIDATE_HISTORY = _write_history(tmp_path, records)
        try:
            fv = build_forward_validation("test", {"run_a"}, None, 5)
            pkt = build_operator_packet(fv, None)
            assert "Deprioritize" in pkt["action_recommendation"]
            assert "breakout_daily" in pkt["action_recommendation"]
        finally:
            art_mod.CANDIDATE_HISTORY = orig

    def test_action_recommendation_always_nonempty(self):
        fv = build_forward_validation("rec_test", set(), None, 10)
        pkt = build_operator_packet(fv, None)
        assert len(pkt["action_recommendation"]) > 0
