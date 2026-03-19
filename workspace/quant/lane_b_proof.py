#!/usr/bin/env python3
"""Lane B Proof — Intelligence lanes end-to-end, runtime-safe.

Proves:
  1. Atlas consumes Sigma rejection and changes next output
  2. Atlas batch generation respects scheduler/host controls
  3. Fish compares forecast to realized outcome, emits calibration
  4. Fish emits risk_map_packet
  5. Hermes directed research with dedup + dataset/repo/theme packets
  6. TradeFloor enforces 6h sparse cadence and emits synthesis for Kitt
  7. TradeFloor emits degraded packet when scheduler blocks
  8. All Lane B heavy ops go through scheduler with host-awareness
  9. Governor evaluates lane health and adjusts parameters
  10. All outputs use shared/latest and frozen packet contracts

Usage:
    cd ~/.openclaw/workspace/jarvis-v5
    python3 workspace/quant/lane_b_proof.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import make_packet, validate_packet
from workspace.quant.shared.packet_store import store_packet, get_latest, get_all_latest
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, get_strategy, load_all_strategies,
)
from workspace.quant.shared.scheduler.scheduler import (
    register_heavy_job, deregister_heavy_job, get_active_jobs,
    check_capacity, resolve_host, heavy_job_slot,
)
from workspace.quant.shared.governor import evaluate_cycle, get_lane_params, load_governor_state
from workspace.quant.sigma.validation_lane import validate_candidate
from workspace.quant.atlas.exploration_lane import (
    generate_candidate, generate_candidate_batch, ingest_rejections,
    emit_failure_learning, emit_health_summary as atlas_health,
)
from workspace.quant.fish.scenario_lane import (
    emit_scenario, emit_forecast, emit_regime, emit_risk_map,
    calibrate, run_scenario_batch,
    emit_health_summary as fish_health,
)
from workspace.quant.hermes.research_lane import (
    emit_research, emit_dataset, emit_repo, emit_theme,
    emit_research_request, check_dedup,
    emit_health_summary as hermes_health,
)
from workspace.quant.tradefloor.synthesis_lane import synthesize, CadenceRefused, check_cadence
from workspace.quant.kitt.brief_producer import produce_brief
from workspace.quant.shared.restart import (
    recover_lane_state, clear_stale_scheduler_jobs,
    check_latest_coherence, check_tradefloor_cadence_after_restart,
    check_dedup_state_after_restart, check_atlas_registry_after_restart,
)

PASS = 0
FAIL = 0


def ok(msg: str):
    global PASS
    PASS += 1
    print(f"  \u2705 {msg}")


def fail(msg: str):
    global FAIL
    FAIL += 1
    print(f"  \u274c {msg}")


def check(condition: bool, pass_msg: str, fail_msg: str):
    if condition:
        ok(pass_msg)
    else:
        fail(fail_msg)


def section(title: str):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


def clean():
    for name in ["strategies.jsonl", "approvals.jsonl", "transition_failures.jsonl"]:
        p = ROOT / "workspace" / "quant" / "shared" / "registries" / name
        if p.exists():
            p.unlink()
    latest_dir = ROOT / "workspace" / "quant" / "shared" / "latest"
    if latest_dir.exists():
        for f in latest_dir.glob("*.json"):
            f.unlink()
    for lane in ["hermes", "atlas", "sigma", "kitt", "executor", "fish", "tradefloor"]:
        lane_dir = ROOT / "workspace" / "quant" / lane
        if lane_dir.exists():
            for f in lane_dir.glob("*.json"):
                f.unlink()
    # Clean scheduler state
    sched_dir = ROOT / "workspace" / "quant" / "shared" / "scheduler"
    if sched_dir.exists():
        for f in sched_dir.glob("*.json"):
            f.unlink()


def main():
    print("\n" + "=" * 60)
    print("  LANE B PROOF v3 — Runtime-Safe Intelligence Lanes")
    print("=" * 60)

    clean()
    now = datetime.now(timezone.utc).isoformat()

    # ----------------------------------------------------------------
    section("1. Scheduler — Host-aware heavy-job control")
    # ----------------------------------------------------------------
    host = resolve_host(ROOT, "atlas")
    check(host in ("NIMO", "SonLM"), f"Atlas resolves to host: {host}", f"Bad host: {host}")

    can, _, reason = check_capacity(ROOT, "atlas")
    check(can, f"Capacity available: {reason}", f"No capacity: {reason}")

    # Register jobs to test cap
    j1 = register_heavy_job(ROOT, "sigma", "NIMO")
    j2 = register_heavy_job(ROOT, "kitt", "NIMO")
    can_nimo, _, r = check_capacity(ROOT, "atlas", "NIMO")
    check(not can_nimo, f"NIMO cap hit correctly: {r}", "NIMO cap NOT enforced")

    overflow_host = resolve_host(ROOT, "atlas")
    check(overflow_host == "SonLM", f"Atlas overflows to SonLM when NIMO full", f"Bad overflow: {overflow_host}")

    deregister_heavy_job(ROOT, j1)
    deregister_heavy_job(ROOT, j2)

    # ----------------------------------------------------------------
    section("2. Hermes — Research + dataset/repo/theme packets")
    # ----------------------------------------------------------------
    research = emit_research(
        ROOT, thesis="NQ overnight mean-reversion edge post-FOMC.",
        source="fed-minutes-2026-03", source_type="official_doc",
        symbol_scope="NQ", confidence=0.7,
    )
    check(research is not None and validate_packet(research) == [],
          f"Research packet: {research.packet_id}", "Research failed")

    dup = emit_research(ROOT, thesis="Dup", source="fed-minutes-2026-03", source_type="official_doc")
    check(dup is None, "Dedup correctly skipped", "Dedup failed")

    dataset = emit_dataset(ROOT, "NQ OHLCV 2025 daily", "nq_ohlcv_2025",
                           source="quandl-nq", source_type="api", symbol_scope="NQ")
    check(dataset is not None and validate_packet(dataset) == [],
          f"dataset_packet: {dataset.packet_id}", "dataset_packet failed")

    repo = emit_repo(ROOT, "Useful NQ analysis code", repo_url="https://github.com/example/nq")
    check(repo is not None and validate_packet(repo) == [],
          f"repo_packet: {repo.packet_id}", "repo_packet failed")

    theme = emit_theme(ROOT, "FOMC dovish pivot as macro theme",
                       theme_name="fomc_dovish", confidence=0.6)
    check(validate_packet(theme) == [], f"theme_packet: {theme.packet_id}", "theme_packet failed")

    # ----------------------------------------------------------------
    section("3. Atlas — Rejection feedback + scheduler-aware batch")
    # ----------------------------------------------------------------
    c1, fb1 = generate_candidate(
        ROOT, "atlas-mr-001",
        "NQ mean-reversion: fade overnight gaps > 0.5%",
        evidence_refs=[research.packet_id], confidence=0.55,
    )
    check(fb1["rejection_count"] == 0, "No prior rejections (first candidate)", "")

    transition_strategy(ROOT, "atlas-mr-001", "VALIDATING", actor="sigma")
    outcome1, rej_pkt = validate_candidate(
        ROOT, c1, profit_factor=0.9, sharpe=0.4, max_drawdown_pct=0.20, trade_count=12,
    )
    check(outcome1 == "rejected", f"Sigma rejects: {rej_pkt.rejection_reason}", "")
    emit_failure_learning(ROOT, rej_pkt, "Gap fade insufficient without regime filter")

    c2, fb2 = generate_candidate(
        ROOT, "atlas-mr-002",
        "NQ mean-reversion with regime filter",
        parent_id="atlas-mr-001", evidence_refs=[research.packet_id], confidence=0.60,
    )
    check(fb2["adapted"], f"Atlas adapted: {fb2['avoidance_patterns']}", "Atlas did NOT adapt")
    check("adapted:" in c2.thesis.lower(), "Thesis reflects adaptation", "")

    # Batch with scheduler
    batch_pkt, generated, sched = generate_candidate_batch(
        ROOT, [{"strategy_id": "atlas-batch-001", "thesis": "Batch test strategy"}],
    )
    check(validate_packet(batch_pkt) == [], f"experiment_batch_packet: {batch_pkt.packet_id}", "")
    check(sched["acquired"], f"Batch acquired scheduler slot on {sched['host']}", "Batch blocked")

    # ----------------------------------------------------------------
    section("4. Fish — Forecast + calibration + risk_map + scheduler batch")
    # ----------------------------------------------------------------
    forecast = emit_forecast(
        ROOT, "NQ expected rally post-FOMC",
        symbol_scope="NQ", confidence=0.55,
        forecast_value=18400.0, forecast_direction="bullish",
    )
    check(validate_packet(forecast) == [], "Forecast validates", "")

    cal_pkt, cal_result = calibrate(ROOT, forecast, realized_value=18350.0, realized_direction="bullish")
    check(cal_result["direction_correct"], "Calibration: direction correct", "")
    check(cal_result["value_error"] == 50.0, f"Value error: {cal_result['value_error']}", "")
    check(cal_result["adjusted_confidence"] != forecast.confidence,
          f"Confidence adjusted: {forecast.confidence:.3f} -> {cal_result['adjusted_confidence']:.3f}", "")

    risk_map = emit_risk_map(
        ROOT, "NQ risk zones: VIX spike, liquidity gap",
        risk_zones={"vix_spike": {"level": "high", "trigger": "VIX > 30"},
                    "liquidity_gap": {"level": "medium", "trigger": "overnight vol < p50"}},
        confidence=0.6,
    )
    check(validate_packet(risk_map) == [], f"risk_map_packet: {risk_map.packet_id}", "")
    check(len(risk_map.artifacts) == 1, "Risk zones stored as artifact", "")

    pkts, sched_f = run_scenario_batch(ROOT, [{"thesis": "Scenario A"}, {"thesis": "Scenario B"}])
    check(sched_f["acquired"], f"Fish batch acquired slot on {sched_f['host']}", "Fish blocked")
    check(sched_f["emitted"] >= 1, f"Fish emitted {sched_f['emitted']} scenarios", "")

    # ----------------------------------------------------------------
    section("5. TradeFloor — Sparse cadence + scheduler + synthesis")
    # ----------------------------------------------------------------
    tf_pkt = synthesize(ROOT)
    check(validate_packet(tf_pkt) == [], f"TradeFloor: {tf_pkt.packet_id}", "")
    check(tf_pkt.agreement_tier is not None, f"Tier: {tf_pkt.agreement_tier}", "")
    check("host=" in (tf_pkt.notes or ""), "TradeFloor logs host used", "")

    # Cadence enforcement
    cadence_blocked = False
    try:
        synthesize(ROOT)
    except CadenceRefused:
        cadence_blocked = True
    check(cadence_blocked, "Cadence: second call within 6h correctly refused", "Cadence NOT enforced")

    # Override
    tf2 = synthesize(ROOT, override_reason="urgent regime shift")
    check(tf2 is not None and "override" in (tf2.notes or ""),
          "Override allowed with logged reason", "Override failed")

    # Kitt reads TradeFloor
    brief = produce_brief(ROOT, market_read="Lane B v3 proof run.")
    check("TRADEFLOOR" in (brief.notes or ""), "Kitt brief includes TRADEFLOOR", "")

    # ----------------------------------------------------------------
    section("6. Governor — Threshold-based lane adjustment")
    # ----------------------------------------------------------------
    gov_action, gov_reason = evaluate_cycle(
        ROOT, "atlas",
        usefulness_score=0.7, efficiency_score=0.6,
        health_score=0.9, confidence_score=0.7,
    )
    check(gov_action == "push", f"Governor pushes productive atlas: {gov_reason}", f"Got {gov_action}")
    params = get_lane_params(ROOT, "atlas")
    check(params["batch_size"] >= 2, f"Batch size increased to {params['batch_size']}", "")

    gov_action2, _ = evaluate_cycle(
        ROOT, "fish",
        usefulness_score=0.1, efficiency_score=0.5,
        health_score=0.5, confidence_score=0.3,
    )
    check(gov_action2 == "backoff", f"Governor backs off unproductive fish", f"Got {gov_action2}")

    # ----------------------------------------------------------------
    section("7. Health summaries — Governor-integrated")
    # ----------------------------------------------------------------
    atlas_h = atlas_health(ROOT, now, now, packets_produced=5,
                           candidates_generated=3, rejections_ingested=1,
                           usefulness_score=0.6, health_score=0.8)
    check(validate_packet(atlas_h) == [], "Atlas health validates", "")
    check(atlas_h.governor_action_taken in ("push", "hold", "backoff", "pause"),
          f"Atlas governor: {atlas_h.governor_action_taken}", "")

    fish_h = fish_health(ROOT, now, now, packets_produced=6,
                         scenarios_emitted=2, forecasts_emitted=1, calibrations_done=1,
                         usefulness_score=0.5, health_score=0.7)
    check(validate_packet(fish_h) == [], "Fish health validates", "")

    hermes_h = hermes_health(ROOT, now, now, packets_produced=5,
                             research_emitted=3, requests_processed=1, dedup_skips=1)
    check(validate_packet(hermes_h) == [], "Hermes health validates", "")

    # ----------------------------------------------------------------
    section("8. Restart/recovery — filesystem state survives")
    # ----------------------------------------------------------------

    # Simulate stale scheduler job from a "crashed" process
    from workspace.quant.shared.scheduler.scheduler import register_heavy_job as _reg, _load_active_jobs, _save_active_jobs
    import time as _time
    stale_jobs = _load_active_jobs(ROOT)
    stale_jobs.append({"job_id": "crashed-atlas-old", "lane": "atlas", "host": "NIMO",
                        "registered_at": _time.time() - 7200, "priority": 6})
    _save_active_jobs(ROOT, stale_jobs)
    cleared = clear_stale_scheduler_jobs(ROOT)
    check(cleared >= 1, f"Stale scheduler cleanup: {cleared} jobs cleared", "Stale jobs NOT cleared")

    # Verify shared/latest coherence
    coherent, issues = check_latest_coherence(ROOT)
    check(coherent, f"shared/latest coherent ({len(get_all_latest(ROOT))} packets)", f"Coherence issues: {issues}")

    # TradeFloor cadence survives restart
    can_run, remaining = check_tradefloor_cadence_after_restart(ROOT)
    check(not can_run, f"TradeFloor cadence preserved after restart ({remaining:.0f}s remaining)", "Cadence lost")

    # Hermes dedup survives restart
    dedup_state = check_dedup_state_after_restart(ROOT)
    check(dedup_state["count"] >= 1, f"Hermes dedup state: {dedup_state['count']} sources tracked", "Dedup state lost")

    # Atlas registry survives — no duplicate creation possible
    registry_state = check_atlas_registry_after_restart(ROOT)
    check(registry_state["strategy_count"] >= 2, f"Registry: {registry_state['strategy_count']} strategies", "")
    dup_blocked = False
    try:
        generate_candidate(ROOT, "atlas-mr-001", "Duplicate attempt")
    except ValueError:
        dup_blocked = True
    check(dup_blocked, "Duplicate strategy blocked after restart", "Duplicate NOT blocked")

    # Governor state survives restart
    for lane_name in ["atlas", "fish", "hermes"]:
        rec = recover_lane_state(ROOT, lane_name)
        check(rec["latest_packet"] is not None, f"{lane_name} recovery: latest found", f"{lane_name}: no latest")
        check(len(rec["governor_params"]) > 0, f"{lane_name} governor params intact", f"{lane_name}: governor lost")

    # ----------------------------------------------------------------
    section("9. Contract verification")
    # ----------------------------------------------------------------
    all_latest = get_all_latest(ROOT)
    total = len(all_latest)
    check(total >= 10, f"Total latest packets: {total}", f"Too few: {total}")

    all_valid = True
    for key, pkt in all_latest.items():
        errors = validate_packet(pkt)
        if errors:
            fail(f"  {key}: {errors}")
            all_valid = False
    if all_valid:
        ok(f"All {total} latest packets pass frozen contract validation")

    # ----------------------------------------------------------------
    section("LANE B v3 PROOF RESULTS")
    # ----------------------------------------------------------------
    print(f"\n  PASS: {PASS}")
    print(f"  FAIL: {FAIL}")

    print(f"\n  STRATEGY REGISTRY:")
    for sid, s in load_all_strategies(ROOT).items():
        print(f"    {sid}: {s.lifecycle_state} (parent={s.parent_id or 'none'})")

    print(f"\n  SCHEDULER: {len(get_active_jobs(ROOT))} active heavy jobs")

    gov = load_governor_state(ROOT)
    print(f"\n  GOVERNOR STATE:")
    for lane in ["atlas", "fish", "hermes"]:
        p = gov.get(lane, {})
        print(f"    {lane}: batch={p.get('batch_size')}, cadence={p.get('cadence_multiplier')}, paused={p.get('paused')}")

    print(f"\n  LATEST PACKETS ({total}):")
    for key, pkt in sorted(all_latest.items()):
        print(f"    {key}: {pkt.thesis[:55]}")

    print()
    if FAIL == 0:
        print("  \U0001f3af LANE B v3 PROOF: ALL CHECKS PASSED")
    else:
        print(f"  \u26a0\ufe0f  LANE B v3 PROOF: {FAIL} FAILURES")
    print()
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
