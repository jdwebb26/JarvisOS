"""Tests for eval_report — regression scoring, comparison, and rendering."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eval_report import (
    _aggregate_scores,
    _compare_runs,
    render_report,
    render_history,
)


# ---------------------------------------------------------------------------
# Aggregate scores
# ---------------------------------------------------------------------------

def _make_results(scores_per_trace: list[list[dict]]) -> list[dict]:
    """Build results list from per-trace score lists."""
    results = []
    for scores in scores_per_trace:
        results.append({
            "trace_id": f"trace_{len(results)}",
            "all_passed": all(s["passed"] for s in scores),
            "scores": scores,
        })
    return results


class TestAggregateScores:
    def test_all_pass(self):
        results = _make_results([
            [{"scorer": "completeness", "passed": True}, {"scorer": "routing", "passed": True}],
            [{"scorer": "completeness", "passed": True}, {"scorer": "routing", "passed": True}],
        ])
        agg = _aggregate_scores(results)
        assert agg["completeness"]["rate"] == 1.0
        assert agg["routing"]["rate"] == 1.0

    def test_partial_fail(self):
        results = _make_results([
            [{"scorer": "completeness", "passed": True}, {"scorer": "routing", "passed": False}],
            [{"scorer": "completeness", "passed": True}, {"scorer": "routing", "passed": True}],
        ])
        agg = _aggregate_scores(results)
        assert agg["completeness"]["rate"] == 1.0
        assert agg["routing"]["rate"] == 0.5
        assert agg["routing"]["failed"] == 1

    def test_empty(self):
        assert _aggregate_scores([]) == {}


# ---------------------------------------------------------------------------
# Compare runs
# ---------------------------------------------------------------------------

class TestCompareRuns:
    def test_stable(self):
        current = {"pass_rate": 1.0, "traces_scored": 10, "failed": 0, "results": []}
        previous = {"pass_rate": 1.0, "traces_scored": 8, "failed": 0, "results": [],
                     "regression_run_id": "prev_1"}
        comp = _compare_runs(current, previous)
        assert comp["trend"] == "stable"
        assert comp["delta_rate"] == 0

    def test_improved(self):
        current = {"pass_rate": 1.0, "traces_scored": 10, "failed": 0, "results": []}
        previous = {"pass_rate": 0.8, "traces_scored": 10, "failed": 2, "results": [],
                     "regression_run_id": "prev_2"}
        comp = _compare_runs(current, previous)
        assert comp["trend"] == "improved"
        assert comp["delta_rate"] == 0.2

    def test_regressed(self):
        current = {"pass_rate": 0.7, "traces_scored": 10, "failed": 3, "results": []}
        previous = {"pass_rate": 1.0, "traces_scored": 10, "failed": 0, "results": [],
                     "regression_run_id": "prev_3"}
        comp = _compare_runs(current, previous)
        assert comp["trend"] == "regressed"
        assert comp["delta_rate"] == -0.3
        assert comp["delta_failed"] == 3

    def test_scorer_deltas(self):
        cur_results = _make_results([
            [{"scorer": "completeness", "passed": True}, {"scorer": "routing", "passed": False}],
        ])
        prev_results = _make_results([
            [{"scorer": "completeness", "passed": True}, {"scorer": "routing", "passed": True}],
        ])
        current = {"pass_rate": 0.5, "traces_scored": 1, "failed": 1, "results": cur_results}
        previous = {"pass_rate": 1.0, "traces_scored": 1, "failed": 0, "results": prev_results,
                     "regression_run_id": "prev_4"}
        comp = _compare_runs(current, previous)
        assert comp["scorer_deltas"]["routing"]["delta"] == -1.0
        assert comp["scorer_deltas"]["completeness"]["delta"] == 0


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

class TestRenderReport:
    def test_pass_report(self):
        report = {
            "verdict": "PASS", "regression_run_id": "regrun_test",
            "traces_scored": 5, "passed": 5, "failed": 0, "pass_rate": 1.0,
            "results": _make_results([
                [{"scorer": "completeness", "passed": True}],
            ] * 5),
        }
        text = render_report(report)
        assert "PASS" in text
        assert "completeness" in text
        assert "5/5" in text

    def test_fail_report_shows_failures(self):
        report = {
            "verdict": "FAIL", "regression_run_id": "regrun_fail",
            "traces_scored": 2, "passed": 1, "failed": 1, "pass_rate": 0.5,
            "results": [
                {"trace_id": "trace_ok", "trace_kind": "ralph_hal", "all_passed": True,
                 "scores": [{"scorer": "completeness", "passed": True}]},
                {"trace_id": "trace_bad", "trace_kind": "ralph_hal", "all_passed": False,
                 "scores": [{"scorer": "completeness", "passed": False,
                             "notes": ["No usable output"]}]},
            ],
        }
        text = render_report(report)
        assert "FAIL" in text
        assert "FAILURES" in text
        assert "trace_bad" in text
        assert "No usable output" in text

    def test_comparison_shown(self):
        report = {
            "verdict": "PASS", "regression_run_id": "regrun_cur",
            "traces_scored": 10, "passed": 10, "failed": 0, "pass_rate": 1.0,
            "results": [],
        }
        comp = {
            "previous_run_id": "regrun_prev", "previous_created_at": "2026-03-18T10:00:00",
            "current_rate": 1.0, "previous_rate": 0.8, "delta_rate": 0.2,
            "current_scored": 10, "previous_scored": 8, "delta_failed": -2,
            "trend": "improved", "scorer_deltas": {},
        }
        text = render_report(report, comp)
        assert "IMPROVED" in text
        assert "80%" in text
        assert "100%" in text


class TestRenderHistory:
    def test_empty(self):
        assert "No eval runs" in render_history([])

    def test_with_runs(self):
        runs = [
            {"eval_run_id": "r1", "created_at": "2026-03-18T10:00:00", "status": "completed",
             "scoring": [{"passed": True}, {"passed": True}],
             "trace_snapshot": {"traces_scored": 2}},
        ]
        text = render_history(runs)
        assert "EVAL HISTORY" in text
        assert "r1" in text
        assert "100%" in text
