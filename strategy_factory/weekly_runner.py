"""Weekly forward-validation runner.

Orchestrates a full research cycle:
    1. ingest-update (refresh market data)
    2. run --dataset NQ_daily --family ema_crossover
    3. run --dataset NQ_daily --family ema_crossover_cd
    4. run --dataset NQ_daily --family breakout
    5. run --dataset NQ_hourly (all compatible families)
    6. Regenerate shortlist outputs: compare, watchlist, review-queue, export, rollup
    7. Write forward_validation.json (cross-family analysis)
    8. Write weekly_report.md (human-readable operator report)

All artifacts land under:
    ~/.openclaw/workspace/artifacts/strategy_factory/<date>/

Usage:
    python3 -m strategy_factory weekly-run
    python3 -m strategy_factory weekly-run --n-candidates 10
"""

import argparse
import json
import traceback
import uuid
from pathlib import Path

from . import artifacts as _art
from .analysis import (
    compare_runs, generate_watchlist, generate_review_queue,
    export_candidate_packets, research_rollup, list_runs,
    append_watchlist_history,
)
from .forward_validation import (
    build_forward_validation,
    build_weekly_report,
    build_operator_packet,
    history_snapshot,
)

# Keep underscore-prefixed aliases so any external code that imported
# the old private names from this module continues to work.
_build_forward_validation = build_forward_validation
_build_weekly_report = build_weekly_report
_history_snapshot = history_snapshot


# ---------------------------------------------------------------------------
# Internal run helper — calls _run() in-process
# ---------------------------------------------------------------------------

def _do_run(dataset, family=None, n_candidates=None):
    """Execute a single pipeline run in-process.

    Constructs an args namespace and delegates to cli._run().
    Returns the run_id if successful (extracted from research_summary).
    """
    from .cli import _run

    args = argparse.Namespace(
        config="configs/default.yaml",
        dataset=dataset,
        family=family,
        data_path=None,
        synthetic=False,
        sentinel=False,
        n_candidates=str(n_candidates) if n_candidates else None,
        candidate_id=None,
    )
    _run(args)

    # Extract run_id from the research_summary that _run just wrote
    art_dir = _art.ensure_artifact_dir()
    rs_path = art_dir / "research_summary.json"
    if rs_path.exists():
        rs = json.loads(rs_path.read_text(encoding="utf-8"))
        return rs.get("run_id")
    return None


def _do_ingest_update():
    """Run ingest-update in-process."""
    from .ingest import update
    update(data_dir=None)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_weekly(n_candidates=10, extended_intraday=False):
    """Execute a full weekly research cycle.

    Args:
        n_candidates: candidates per family per run.
        extended_intraday: if True, also run NQ_15m and NQ_4h datasets
            in addition to the default NQ_daily + NQ_hourly workload.
            Default False — the standard weekly remains unchanged.

    Calls pipeline functions in-process (no subprocess shelling).
    Returns the forward_validation dict.
    """
    cycle_id = f"weekly_{uuid.uuid4().hex[:8]}"
    print(f"=== Weekly Research Cycle: {cycle_id} ===")
    print()

    snap_before = history_snapshot()

    # --- Phase 1: Ingest ---
    print("Phase 1: Ingest update")
    try:
        _do_ingest_update()
        print("  ok")
    except Exception as exc:
        print(f"  WARNING: ingest-update failed: {exc}")
        print("  continuing with existing data...")
    print()

    # --- Phase 2: Research runs (in-process) ---
    print("Phase 2: Research runs")
    run_ids = set()
    run_specs = [
        ("NQ_daily", "ema_crossover", "daily / ema_crossover"),
        ("NQ_daily", "ema_crossover_cd", "daily / ema_crossover_cd"),
        ("NQ_daily", "breakout", "daily / breakout"),
        ("NQ_hourly", None, "hourly / all"),
    ]
    if extended_intraday:
        run_specs += [
            ("NQ_4h", None, "4h / all"),
            ("NQ_15m", None, "15m / all"),
        ]
        print("  (extended intraday mode: including NQ_4h and NQ_15m)")
        print()
    for dataset, family, label in run_specs:
        print(f"  [{label}]")
        try:
            rid = _do_run(dataset, family, n_candidates)
            if rid:
                run_ids.add(rid)
                print(f"    run_id: {rid}")
            else:
                print("    completed (no run_id extracted)")
        except Exception as exc:
            print(f"    ERROR: {exc}")
            traceback.print_exc()
    print()

    if not run_ids:
        print("WARNING: no runs produced run_ids, using recent history")
        recent = list_runs()
        run_ids = set(r["run_id"] for r in recent[:4])

    # --- Phase 3: Shortlist regeneration ---
    print("Phase 3: Shortlist outputs")
    art_dir = _art.ensure_artifact_dir()

    shortlist_outputs = {}

    # Compare
    try:
        cmp = compare_runs(last_n=4, dataset_id="NQ_daily")
        _art.write_json(art_dir / "compare.json", cmp)
        shortlist_outputs["compare"] = "ok"
        print("  compare.json")
    except Exception as exc:
        shortlist_outputs["compare"] = f"error: {exc}"

    # Watchlist
    try:
        wl = generate_watchlist(top_n=10)
        _art.write_json(art_dir / "watchlist.json", wl)
        if wl.get("status") != "no_history":
            append_watchlist_history(wl)
        shortlist_outputs["watchlist"] = "ok"
        print("  watchlist.json + history")
    except Exception as exc:
        shortlist_outputs["watchlist"] = f"error: {exc}"

    # Review queue
    try:
        rq = generate_review_queue(top_n=10)
        _art.write_json(art_dir / "review_queue.json", rq)
        shortlist_outputs["review_queue"] = "ok"
        print("  review_queue.json")
    except Exception as exc:
        shortlist_outputs["review_queue"] = f"error: {exc}"

    # Export packets
    try:
        pkts = export_candidate_packets(top_n=10)
        _art.write_json(art_dir / "candidate_packets.json", pkts)
        shortlist_outputs["export"] = "ok"
        print("  candidate_packets.json")
    except Exception as exc:
        shortlist_outputs["export"] = f"error: {exc}"

    # Rollup
    try:
        rollup = research_rollup()
        _art.write_json(art_dir / "rollup.json", rollup)
        shortlist_outputs["rollup"] = "ok"
        print("  rollup.json")
    except Exception as exc:
        shortlist_outputs["rollup"] = f"error: {exc}"

    print()

    # --- Phase 4: Forward validation ---
    print("Phase 4: Forward validation")
    fv = build_forward_validation(cycle_id, run_ids, art_dir, n_candidates)
    _art.write_json(art_dir / "forward_validation.json", fv)
    print(f"  forward_validation.json -> {art_dir / 'forward_validation.json'}")
    print()

    # --- Phase 5: Weekly report ---
    print("Phase 5: Weekly report")
    report_text = build_weekly_report(fv, art_dir)
    report_path = art_dir / "weekly_report.md"
    report_path.write_text(report_text, encoding="utf-8")
    print(f"  weekly_report.md -> {report_path}")
    print()

    # --- Phase 6: Operator packet ---
    print("Phase 6: Operator packet")
    packet = build_operator_packet(fv, art_dir)
    _art.write_json(art_dir / "operator_packet.json", packet)
    print(f"  operator_packet.json -> {art_dir / 'operator_packet.json'}")
    print(f"  status: {packet['operator_status']}")
    print()

    # --- Phase 7: Emit to Jarvis runtime ---
    print("Phase 7: Emit to Jarvis runtime")
    try:
        from .jarvis_emit import emit_factory_summary
        emit_result = emit_factory_summary(art_dir / "operator_packet.json")
        print(f"  event: {emit_result['event_result']['event_id']}")
        print(f"  outbox: {len(emit_result['event_result'].get('outbox_entries', []))} entries")
        print(f"  brief: {emit_result['kitt_brief_path']}")
    except Exception as exc:
        print(f"  WARNING: Jarvis emit failed (non-fatal): {exc}")
        print("  pipeline artifacts are intact — emit can be retried manually")
    print()

    # --- Summary ---
    snap_after = history_snapshot()
    new_records = snap_after["count"] - snap_before["count"]
    new_runs = snap_after["run_ids"] - snap_before["run_ids"]

    print(f"=== Cycle Complete: {cycle_id} ===")
    print(f"  new records: {new_records}")
    print(f"  new runs: {len(new_runs)}")
    print(f"  artifacts: {art_dir}")
    print()

    q = fv["questions"]
    print(f"  cd vs baseline: {q['cd_vs_baseline']}")
    print(f"  cooldown regime: {q['cooldown_regime_present']}")
    print(f"  breakout coverage: {q['breakout_coverage']}")
    print(f"  hourly status: {q['hourly_status']}")
    print(f"  priority: {q['priority_family']}")
    print(f"  monitor: {q['monitor_family']}")
    if q.get("degraded_prior_ideas"):
        print(f"  degraded ideas: {len(q['degraded_prior_ideas'])}")

    return fv
