#!/usr/bin/env python3
"""run_regression.py — Run regression scoring against stored execution traces.

Usage:
    python3 scripts/run_regression.py                     # score all ralph traces
    python3 scripts/run_regression.py --trace-id <id>     # score one trace
    python3 scripts/run_regression.py --agent hal          # score only HAL traces
    python3 scripts/run_regression.py --expected-model qwen3.5-35b-a3b  # check model match
    python3 scripts/run_regression.py --json               # JSON output

Produces a pass/fail regression report from real execution traces.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.evals.scorers import run_all_scorers
from runtime.evals.trace_store import list_run_traces, load_run_trace
from runtime.evals.replay_runner import save_eval_run
from runtime.core.models import new_id, now_iso


def run_regression(
    *,
    root: Path,
    trace_id: str = "",
    agent_filter: str = "",
    expected_model: str = "",
    limit: int = 20,
) -> dict:
    """Score traces and produce a regression report."""
    if trace_id:
        trace = load_run_trace(trace_id, root=root)
        if trace is None:
            return {"ok": False, "error": f"Trace not found: {trace_id}"}
        traces = [trace]
    else:
        all_traces = list_run_traces(root=root, limit=200)
        # Filter to ralph traces
        traces = [t for t in all_traces if "ralph" in (t.trace_kind or "")]
        if agent_filter:
            traces = [t for t in traces if agent_filter in (t.trace_kind or "")]
        traces = traces[:limit]

    if not traces:
        return {"ok": True, "traces_scored": 0, "message": "No matching traces found"}

    results = []
    total_passed = 0
    total_failed = 0

    for trace in traces:
        trace_dict = trace.to_dict()
        scores = run_all_scorers(trace_dict, expected_model=expected_model)
        all_passed = all(s["passed"] for s in scores)
        if all_passed:
            total_passed += 1
        else:
            total_failed += 1
        results.append({
            "trace_id": trace.trace_id,
            "trace_kind": trace.trace_kind,
            "task_id": trace.task_id,
            "status": trace.status,
            "all_passed": all_passed,
            "scores": scores,
        })

    total = len(results)
    report = {
        "ok": total_failed == 0,
        "regression_run_id": new_id("regrun"),
        "created_at": now_iso(),
        "traces_scored": total,
        "passed": total_passed,
        "failed": total_failed,
        "pass_rate": round(total_passed / max(total, 1), 2),
        "verdict": "PASS" if total_failed == 0 else "FAIL",
        "results": results,
    }

    # Save as eval run
    eval_payload = {
        "eval_run_id": report["regression_run_id"],
        "created_at": report["created_at"],
        "updated_at": report["created_at"],
        "actor": "operator",
        "lane": "regression",
        "status": "completed",
        "replay_mode": "regression_scoring",
        "scoring": [s for r in results for s in r["scores"]],
        "trace_snapshot": {
            "traces_scored": total,
            "pass_rate": report["pass_rate"],
        },
    }
    save_eval_run(eval_payload, root=root)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run regression scoring on execution traces")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--trace-id", default="", help="Score a single trace")
    parser.add_argument("--agent", default="", help="Filter by agent (hal, archimedes)")
    parser.add_argument("--expected-model", default="", help="Check model match against this")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    report = run_regression(
        root=root,
        trace_id=args.trace_id,
        agent_filter=args.agent,
        expected_model=args.expected_model,
        limit=args.limit,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Regression: {report['verdict']}")
        print(f"  Traces scored: {report['traces_scored']}")
        print(f"  Passed: {report['passed']}  Failed: {report['failed']}  Rate: {report['pass_rate']}")
        if report.get("results"):
            for r in report["results"]:
                status = "PASS" if r["all_passed"] else "FAIL"
                print(f"  {r['trace_id']}: {status} ({r['trace_kind']})")
                for s in r["scores"]:
                    if not s["passed"]:
                        print(f"    FAIL: {s['scorer']} — {'; '.join(s.get('notes', []))}")

    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
