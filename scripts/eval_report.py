#!/usr/bin/env python3
"""eval_report — operator-facing eval/regression command with run comparison.

Runs regression scoring against live execution traces, compares to the
prior eval run, and shows pass/fail with deltas.

Usage:
    python3 scripts/eval_report.py                    # run eval + compare
    python3 scripts/eval_report.py --compare-only     # compare last two runs
    python3 scripts/eval_report.py --history           # show all eval runs
    python3 scripts/eval_report.py --json              # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_regression import run_regression
from runtime.evals.replay_runner import list_eval_runs


# ---------------------------------------------------------------------------
# Per-scorer aggregation
# ---------------------------------------------------------------------------

def _aggregate_scores(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate per-scorer pass rates from a regression run's results."""
    agg: dict[str, dict[str, int]] = {}
    for result in results:
        for score in result.get("scores", []):
            scorer = score.get("scorer", "unknown")
            agg.setdefault(scorer, {"passed": 0, "failed": 0, "total": 0})
            agg[scorer]["total"] += 1
            if score.get("passed"):
                agg[scorer]["passed"] += 1
            else:
                agg[scorer]["failed"] += 1

    out: dict[str, dict[str, Any]] = {}
    for scorer, counts in agg.items():
        total = counts["total"]
        out[scorer] = {
            "passed": counts["passed"],
            "failed": counts["failed"],
            "total": total,
            "rate": round(counts["passed"] / max(total, 1), 2),
        }
    return out


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _compare_runs(
    current: dict[str, Any],
    previous: dict[str, Any],
) -> dict[str, Any]:
    """Compare two eval runs and produce deltas."""
    cur_rate = current.get("pass_rate", 0)
    prev_rate = previous.get("pass_rate", 0)
    cur_scored = current.get("traces_scored", 0)
    prev_scored = previous.get("traces_scored", 0)
    cur_failed = current.get("failed", 0)
    prev_failed = previous.get("failed", 0)

    delta_rate = round(cur_rate - prev_rate, 2)
    delta_failed = cur_failed - prev_failed

    if delta_rate > 0:
        trend = "improved"
    elif delta_rate < 0:
        trend = "regressed"
    else:
        trend = "stable"

    # Per-scorer comparison
    cur_agg = _aggregate_scores(current.get("results", []))
    prev_agg = _aggregate_scores(previous.get("results", []))
    scorer_deltas: dict[str, dict[str, Any]] = {}
    all_scorers = set(cur_agg.keys()) | set(prev_agg.keys())
    for scorer in sorted(all_scorers):
        cur_s = cur_agg.get(scorer, {"rate": 0, "passed": 0, "failed": 0, "total": 0})
        prev_s = prev_agg.get(scorer, {"rate": 0, "passed": 0, "failed": 0, "total": 0})
        scorer_deltas[scorer] = {
            "current_rate": cur_s["rate"],
            "previous_rate": prev_s["rate"],
            "delta": round(cur_s["rate"] - prev_s["rate"], 2),
            "current_failed": cur_s["failed"],
            "previous_failed": prev_s["failed"],
        }

    return {
        "previous_run_id": previous.get("regression_run_id", previous.get("eval_run_id", "?")),
        "previous_created_at": previous.get("created_at", ""),
        "current_rate": cur_rate,
        "previous_rate": prev_rate,
        "delta_rate": delta_rate,
        "current_scored": cur_scored,
        "previous_scored": prev_scored,
        "delta_failed": delta_failed,
        "trend": trend,
        "scorer_deltas": scorer_deltas,
    }


def _load_previous_run(root: Path, exclude_id: str = "") -> Optional[dict[str, Any]]:
    """Load the most recent eval run that isn't the current one."""
    runs = list_eval_runs(root=root)
    for run in runs:
        run_id = run.get("eval_run_id", "")
        if run_id and run_id != exclude_id:
            # Convert to regression format if needed
            scoring = run.get("scoring", [])
            if scoring and "results" not in run:
                # This is a replay_runner format — convert
                passed = sum(1 for s in scoring if s.get("passed"))
                total = len(scoring)
                run["traces_scored"] = run.get("trace_snapshot", {}).get("traces_scored", total)
                run["passed"] = passed
                run["failed"] = total - passed
                run["pass_rate"] = round(passed / max(total, 1), 2)
                run["results"] = [{"scores": scoring, "all_passed": all(s.get("passed") for s in scoring)}]
            return run
    return None


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def render_report(
    current: dict[str, Any],
    comparison: Optional[dict[str, Any]] = None,
) -> str:
    lines: list[str] = []
    verdict = current.get("verdict", "?")
    icon = "\u2705" if verdict == "PASS" else "\u274c"

    lines.append(f"EVAL REPORT  {icon} {verdict}")
    lines.append(f"  Run:     {current.get('regression_run_id', '?')}")
    lines.append(f"  Scored:  {current.get('traces_scored', 0)} traces")
    lines.append(f"  Passed:  {current.get('passed', 0)}  Failed: {current.get('failed', 0)}  Rate: {current.get('pass_rate', 0)}")
    lines.append("")

    # Per-scorer breakdown
    agg = _aggregate_scores(current.get("results", []))
    if agg:
        lines.append("SCORERS:")
        for scorer, stats in sorted(agg.items()):
            icon_s = "\u2705" if stats["failed"] == 0 else "\u274c"
            delta_str = ""
            if comparison:
                sd = comparison.get("scorer_deltas", {}).get(scorer, {})
                d = sd.get("delta", 0)
                if d > 0:
                    delta_str = f"  \u2191{d:+.0%}"
                elif d < 0:
                    delta_str = f"  \u2193{d:+.0%}"
            lines.append(f"  {icon_s} {scorer:25}  {stats['passed']}/{stats['total']} ({stats['rate']:.0%}){delta_str}")
        lines.append("")

    # Comparison
    if comparison:
        trend = comparison["trend"]
        trend_icon = {
            "improved": "\u2191 IMPROVED",
            "regressed": "\u2193 REGRESSED",
            "stable": "\u2192 STABLE",
        }.get(trend, trend)

        lines.append(f"COMPARISON: {trend_icon}")
        lines.append(f"  vs:      {comparison['previous_run_id'][:20]}")
        lines.append(f"  rate:    {comparison['previous_rate']:.0%} \u2192 {comparison['current_rate']:.0%} ({comparison['delta_rate']:+.0%})")
        lines.append(f"  scored:  {comparison['previous_scored']} \u2192 {comparison['current_scored']}")
        if comparison["delta_failed"] != 0:
            lines.append(f"  failed:  {comparison['delta_failed']:+d}")
        lines.append("")
    elif current.get("traces_scored", 0) > 0:
        lines.append("COMPARISON: (no prior run to compare)")
        lines.append("")

    # Failed traces detail
    failed_results = [r for r in current.get("results", []) if not r.get("all_passed")]
    if failed_results:
        lines.append(f"FAILURES ({len(failed_results)}):")
        for r in failed_results[:5]:
            lines.append(f"  {r.get('trace_id', '?')[:20]}  {r.get('trace_kind', '?')}")
            for s in r.get("scores", []):
                if not s.get("passed"):
                    notes = "; ".join(s.get("notes", []))[:60]
                    lines.append(f"    \u274c {s['scorer']}: {notes}")
        if len(failed_results) > 5:
            lines.append(f"  ... +{len(failed_results) - 5} more")
        lines.append("")

    return "\n".join(lines)


def render_history(runs: list[dict[str, Any]]) -> str:
    if not runs:
        return "No eval runs found."
    lines = ["EVAL HISTORY", ""]
    for run in runs[:10]:
        run_id = run.get("regression_run_id", run.get("eval_run_id", "?"))
        created = run.get("created_at", "")[:19]
        scored = run.get("traces_scored", run.get("trace_snapshot", {}).get("traces_scored", "?"))
        rate = run.get("pass_rate")
        if rate is None:
            # Compute from scoring data
            scoring = run.get("scoring", [])
            if scoring:
                passed = sum(1 for s in scoring if s.get("passed"))
                rate = round(passed / max(len(scoring), 1), 2)
        rate_str = f"{rate:.0%}" if isinstance(rate, (int, float)) else "?"
        verdict = run.get("verdict", run.get("status", "?"))
        lines.append(f"  {run_id[:20]}  {created}  scored={scored}  rate={rate_str}  {verdict}")
    if len(runs) > 10:
        lines.append(f"  ... +{len(runs) - 10} more")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Run eval/regression with comparison to prior run")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--limit", type=int, default=20, help="Max traces to score")
    parser.add_argument("--agent", default="", help="Filter by agent")
    parser.add_argument("--expected-model", default="", help="Check model match")
    parser.add_argument("--compare-only", action="store_true", help="Compare last two runs without re-running")
    parser.add_argument("--history", action="store_true", help="Show eval run history")
    parser.add_argument("--json", action="store_true", dest="json_out")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    if args.history:
        runs = list_eval_runs(root=root)
        if args.json_out:
            print(json.dumps(runs, indent=2))
        else:
            print(render_history(runs))
        return 0

    if args.compare_only:
        runs = list_eval_runs(root=root, limit=2)
        if len(runs) < 2:
            print("Need at least 2 eval runs to compare.")
            return 1
        current_raw = runs[0]
        previous_raw = runs[1]
        # Normalize both to regression format
        for r in [current_raw, previous_raw]:
            scoring = r.get("scoring", [])
            if scoring and "results" not in r:
                passed = sum(1 for s in scoring if s.get("passed"))
                total = len(scoring)
                r["traces_scored"] = r.get("trace_snapshot", {}).get("traces_scored", total)
                r["passed"] = passed
                r["failed"] = total - passed
                r["pass_rate"] = round(passed / max(total, 1), 2)
                r["verdict"] = "PASS" if r["failed"] == 0 else "FAIL"
                r["results"] = [{"scores": scoring, "all_passed": all(s.get("passed") for s in scoring)}]
        comp = _compare_runs(current_raw, previous_raw)
        if args.json_out:
            print(json.dumps({"current": current_raw, "previous": previous_raw, "comparison": comp}, indent=2))
        else:
            print(render_report(current_raw, comp))
        return 0

    # Run regression
    report = run_regression(
        root=root,
        agent_filter=args.agent,
        expected_model=args.expected_model,
        limit=args.limit,
    )

    # Compare to prior run
    previous = _load_previous_run(root, exclude_id=report.get("regression_run_id", ""))
    comparison = _compare_runs(report, previous) if previous else None

    if args.json_out:
        print(json.dumps({"report": report, "comparison": comparison}, indent=2))
    else:
        print(render_report(report, comparison))

    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
