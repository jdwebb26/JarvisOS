#!/usr/bin/env python3
"""Lane B Proof — Intelligence lanes end-to-end.

Proves:
  1. Atlas consumes a Sigma rejection packet and changes its next output
  2. Fish compares a prior forecast to realized outcome and emits calibration
  3. TradeFloor reads latest packets and emits a synthesis packet for Kitt
  4. Hermes directed research with dedup
  5. All outputs use shared/latest and frozen packet contracts
  6. Health summaries emitted by all Lane B agents

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
from workspace.quant.sigma.validation_lane import validate_candidate
from workspace.quant.atlas.exploration_lane import (
    generate_candidate, ingest_rejections, emit_failure_learning,
    emit_health_summary as atlas_health,
)
from workspace.quant.fish.scenario_lane import (
    emit_scenario, emit_forecast, emit_regime, calibrate,
    emit_health_summary as fish_health,
)
from workspace.quant.hermes.research_lane import (
    emit_research, emit_research_request, check_dedup,
    emit_health_summary as hermes_health,
)
from workspace.quant.tradefloor.synthesis_lane import synthesize
from workspace.quant.kitt.brief_producer import produce_brief

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
    """Clean up all quant state from prior runs."""
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


def main():
    print("\n" + "=" * 60)
    print("  LANE B PROOF — Intelligence Lanes")
    print("=" * 60)

    clean()
    now = datetime.now(timezone.utc).isoformat()

    # ----------------------------------------------------------------
    # MILESTONE 1: Hermes directed research
    # ----------------------------------------------------------------
    section("1. Hermes — Directed Research with Dedup")

    # Emit research from a directed request
    research = emit_research(
        ROOT,
        thesis="NQ overnight session shows persistent mean-reversion edge post-FOMC.",
        source="fed-minutes-2026-03",
        source_type="official_doc",
        symbol_scope="NQ",
        confidence=0.7,
    )
    check(research is not None, "Research packet emitted", "Research packet failed")
    check(
        validate_packet(research) == [],
        f"Research packet validates: {research.packet_id}",
        f"Research packet validation errors: {validate_packet(research)}",
    )

    # Verify latest updated
    latest_r = get_latest(ROOT, "hermes", "research_packet")
    check(
        latest_r and latest_r.packet_id == research.packet_id,
        "shared/latest/ updated for hermes research",
        "shared/latest/ NOT updated",
    )

    # Dedup: same source within window should be skipped
    dup = emit_research(ROOT, thesis="Duplicate", source="fed-minutes-2026-03", source_type="official_doc")
    check(dup is None, "Dedup correctly skipped duplicate source", "Dedup failed — duplicate was emitted")

    # Force override dedup
    forced = emit_research(ROOT, thesis="Forced re-research", source="fed-minutes-2026-03",
                           source_type="official_doc", force=True)
    check(forced is not None, "Force flag overrides dedup", "Force flag did not override dedup")

    # Research request from another lane
    req = emit_research_request(ROOT, "atlas", "Research vol surface changes around FOMC",
                                source="vol-surface-fomc", symbol_scope="NQ")
    check(validate_packet(req) == [], "Research request packet validates", "Research request validation failed")

    # ----------------------------------------------------------------
    # MILESTONE 2: Atlas generates candidate, gets rejected, adapts
    # ----------------------------------------------------------------
    section("2. Atlas — First Candidate (will be rejected by Sigma)")

    candidate1, feedback1 = generate_candidate(
        ROOT, "atlas-mr-001",
        "NQ mean-reversion: fade overnight gaps > 0.5% with VIX < 20",
        evidence_refs=[research.packet_id],
        confidence=0.55,
    )
    check(
        validate_packet(candidate1) == [],
        f"Candidate packet validates: {candidate1.packet_id}",
        f"Candidate validation errors: {validate_packet(candidate1)}",
    )
    check(
        feedback1["rejection_count"] == 0,
        "No prior rejections (first candidate)",
        f"Unexpected rejections: {feedback1}",
    )

    # Sigma validates → reject (poor stats)
    transition_strategy(ROOT, "atlas-mr-001", "VALIDATING", actor="sigma")
    outcome1, rej_pkt = validate_candidate(
        ROOT, candidate1,
        profit_factor=0.9, sharpe=0.4, max_drawdown_pct=0.20, trade_count=12,
    )
    check(outcome1 == "rejected", "Sigma correctly rejects atlas-mr-001", f"Expected rejection, got {outcome1}")
    check(
        rej_pkt.rejection_reason in ("poor_oos", "excessive_drawdown", "insufficient_trades"),
        f"Rejection reason valid: {rej_pkt.rejection_reason}",
        f"Invalid rejection reason: {rej_pkt.rejection_reason}",
    )

    # Atlas processes rejection → emits failure_learning
    learning = emit_failure_learning(ROOT, rej_pkt, "Mean-reversion with simple gap fade insufficient. Need regime filter.")
    check(
        validate_packet(learning) == [],
        f"Failure learning packet validates: {learning.packet_id}",
        "Failure learning validation failed",
    )

    section("3. Atlas — Second Candidate (adapted from rejection)")

    # Generate second candidate — should now have avoidance patterns
    candidate2, feedback2 = generate_candidate(
        ROOT, "atlas-mr-002",
        "NQ mean-reversion with regime filter: only trade in low-vol regime",
        parent_id="atlas-mr-001",
        lineage_note="Mutation of atlas-mr-001 after poor_oos rejection",
        evidence_refs=[research.packet_id, learning.packet_id],
        confidence=0.60,
    )

    # KEY PROOF: Atlas consumed rejection and changed behavior
    check(
        feedback2["rejection_count"] >= 1,
        f"Atlas sees {feedback2['rejection_count']} prior rejection(s)",
        "Atlas did NOT see prior rejections",
    )
    check(
        feedback2["adapted"],
        f"Atlas adapted — avoidance: {feedback2['avoidance_patterns']}",
        "Atlas did NOT adapt from rejection",
    )
    check(
        "adapted:" in candidate2.thesis.lower() or "avoid" in (candidate2.notes or "").lower(),
        "Candidate thesis reflects adaptation from rejection",
        "Candidate thesis does NOT reflect adaptation",
    )

    # Verify different confidence (adjusted)
    check(
        candidate2.confidence != 0.60,
        f"Confidence adjusted from rejection feedback: {candidate2.confidence:.3f}",
        "Confidence was NOT adjusted",
    )

    # Registry shows lineage
    strat2 = get_strategy(ROOT, "atlas-mr-002")
    check(
        strat2 and strat2.parent_id == "atlas-mr-001",
        "Strategy registry preserves lineage (parent_id)",
        "Lineage not preserved in registry",
    )

    # ----------------------------------------------------------------
    # MILESTONE 3: Fish forecast → calibration feedback loop
    # ----------------------------------------------------------------
    section("4. Fish — Emit Forecast")

    scenario = emit_scenario(
        ROOT, "NQ likely range-bound 18000-18500 this week, FOMC uncertainty dominant",
        symbol_scope="NQ", confidence=0.6,
    )
    check(validate_packet(scenario) == [], "Scenario packet validates", "Scenario validation failed")

    forecast = emit_forecast(
        ROOT, "NQ expected to test 18200 support before FOMC, then rally",
        symbol_scope="NQ", timeframe_scope="1W",
        confidence=0.55,
        forecast_value=18400.0, forecast_direction="bullish",
    )
    check(validate_packet(forecast) == [], "Forecast packet validates", "Forecast validation failed")
    check(
        forecast.notes and "direction=bullish" in forecast.notes,
        "Forecast has direction metadata",
        "Forecast missing direction metadata",
    )

    regime = emit_regime(ROOT, "Current regime: low-volatility mean-reversion", regime_label="low_vol", confidence=0.65)
    check(validate_packet(regime) == [], "Regime packet validates", "Regime validation failed")

    section("5. Fish — Calibration (forecast vs. realized)")

    # Simulate realized outcome: NQ went to 18350 (bullish was correct, but value slightly off)
    cal_pkt, cal_result = calibrate(
        ROOT,
        prior_forecast=forecast,
        realized_value=18350.0,
        realized_direction="bullish",
    )

    # KEY PROOF: Fish compared forecast to outcome and emitted calibration
    check(
        validate_packet(cal_pkt) == [],
        f"Calibration packet validates: {cal_pkt.packet_id}",
        f"Calibration validation errors: {validate_packet(cal_pkt)}",
    )
    check(
        cal_result["direction_correct"] is True,
        "Calibration: direction was correct (bullish)",
        f"Calibration: direction check failed: {cal_result}",
    )
    check(
        cal_result["value_error"] is not None and cal_result["value_error"] == 50.0,
        f"Calibration: value error = {cal_result['value_error']} (18400 vs 18350)",
        f"Calibration: unexpected value error: {cal_result.get('value_error')}",
    )
    check(
        cal_result["calibration_score"] > 0,
        f"Calibration score: {cal_result['calibration_score']:.3f}",
        "Calibration score is zero or negative",
    )
    check(
        cal_result["adjusted_confidence"] != forecast.confidence,
        f"Confidence adjusted: {forecast.confidence:.3f} → {cal_result['adjusted_confidence']:.3f}",
        "Confidence was NOT adjusted by calibration",
    )

    # Second calibration — bad prediction
    section("5b. Fish — Calibration (incorrect forecast)")
    bad_forecast = emit_forecast(
        ROOT, "NQ expected sharp decline to 17800",
        symbol_scope="NQ", confidence=0.5,
        forecast_value=17800.0, forecast_direction="bearish",
    )
    cal_pkt2, cal_result2 = calibrate(ROOT, bad_forecast, realized_value=18500.0, realized_direction="bullish")
    check(
        cal_result2["direction_correct"] is False,
        "Calibration: correctly identified wrong direction",
        "Calibration: direction error not detected",
    )
    check(
        cal_result2["adjusted_confidence"] < bad_forecast.confidence,
        f"Confidence decreased after bad prediction: {bad_forecast.confidence:.3f} → {cal_result2['adjusted_confidence']:.3f}",
        "Confidence did NOT decrease after bad prediction",
    )

    # ----------------------------------------------------------------
    # MILESTONE 4: TradeFloor synthesis for Kitt
    # ----------------------------------------------------------------
    section("6. TradeFloor — Synthesis")

    # First, make sure there are latest packets from multiple lanes
    # (hermes research, atlas candidate, fish scenario/regime, sigma rejection are all stored)
    all_latest = get_all_latest(ROOT)
    lane_count = len(set(p.lane for p in all_latest.values()))
    check(lane_count >= 3, f"Latest has packets from {lane_count} lanes", f"Only {lane_count} lanes in latest")

    tf_pkt = synthesize(ROOT)

    # KEY PROOF: TradeFloor reads latest and emits synthesis
    check(
        validate_packet(tf_pkt) == [],
        f"TradeFloor packet validates: {tf_pkt.packet_id}",
        f"TradeFloor validation errors: {validate_packet(tf_pkt)}",
    )
    check(
        tf_pkt.agreement_tier is not None and 0 <= tf_pkt.agreement_tier <= 4,
        f"Agreement tier: {tf_pkt.agreement_tier}",
        f"Invalid agreement tier: {tf_pkt.agreement_tier}",
    )
    check(
        tf_pkt.agreement_tier_reasoning is not None and len(tf_pkt.agreement_tier_reasoning) > 0,
        f"Tier reasoning present: {tf_pkt.agreement_tier_reasoning[:80]}",
        "No tier reasoning",
    )
    check(
        tf_pkt.agreement_matrix is not None,
        "Agreement matrix present",
        "Agreement matrix missing",
    )
    check(
        tf_pkt.confidence_weighted_synthesis is not None,
        "Confidence-weighted synthesis present",
        "Synthesis text missing",
    )
    check(
        tf_pkt.pipeline_snapshot is not None and "total_strategies" in tf_pkt.pipeline_snapshot,
        f"Pipeline snapshot: {tf_pkt.pipeline_snapshot}",
        "Pipeline snapshot missing",
    )
    check(
        tf_pkt.operator_recommendation in ("notify", "skip", "schedule"),
        f"Operator recommendation: {tf_pkt.operator_recommendation}",
        f"Invalid operator recommendation: {tf_pkt.operator_recommendation}",
    )

    # Verify TradeFloor packet is in shared/latest for Kitt
    latest_tf = get_latest(ROOT, "tradefloor", "tradefloor_packet")
    check(
        latest_tf and latest_tf.packet_id == tf_pkt.packet_id,
        "TradeFloor packet in shared/latest/ for Kitt consumption",
        "TradeFloor packet NOT in shared/latest/",
    )

    # ----------------------------------------------------------------
    # MILESTONE 5: Kitt reads TradeFloor synthesis in brief
    # ----------------------------------------------------------------
    section("7. Kitt — Brief includes TradeFloor")

    brief = produce_brief(ROOT, market_read="Lane B proof run. No live market data.")
    check(
        brief.notes and "TRADEFLOOR" in brief.notes,
        "Kitt brief includes TRADEFLOOR section",
        "Kitt brief missing TRADEFLOOR section",
    )
    check(
        brief.notes and "Agreement tier" in brief.notes,
        "Kitt brief shows agreement tier from TradeFloor",
        "Kitt brief missing agreement tier",
    )

    # ----------------------------------------------------------------
    # MILESTONE 6: Health summaries from all Lane B agents
    # ----------------------------------------------------------------
    section("8. Health Summaries")

    atlas_h = atlas_health(
        ROOT, now, now, packets_produced=3,
        candidates_generated=2, rejections_ingested=1,
        usefulness_score=0.4, confidence_score=0.5,
    )
    check(validate_packet(atlas_h) == [], "Atlas health_summary validates", "Atlas health validation failed")
    check(atlas_h.governor_action_taken == "none", "Atlas governor field present", "Atlas governor field missing")

    fish_h = fish_health(
        ROOT, now, now, packets_produced=5,
        scenarios_emitted=1, forecasts_emitted=2, calibrations_done=2,
        usefulness_score=0.6, confidence_score=0.55,
    )
    check(validate_packet(fish_h) == [], "Fish health_summary validates", "Fish health validation failed")

    hermes_h = hermes_health(
        ROOT, now, now, packets_produced=3,
        research_emitted=2, requests_processed=1, dedup_skips=1,
        usefulness_score=0.5, confidence_score=0.5,
    )
    check(validate_packet(hermes_h) == [], "Hermes health_summary validates", "Hermes health validation failed")

    # ----------------------------------------------------------------
    # MILESTONE 7: Verify all outputs use frozen contracts
    # ----------------------------------------------------------------
    section("9. Contract Verification")

    all_latest_final = get_all_latest(ROOT)
    total_packets = len(all_latest_final)
    check(total_packets >= 8, f"Total latest packets: {total_packets}", f"Too few packets: {total_packets}")

    # Validate every packet in latest
    all_valid = True
    for key, pkt in all_latest_final.items():
        errors = validate_packet(pkt)
        if errors:
            fail(f"  {key}: {errors}")
            all_valid = False
    if all_valid:
        ok(f"All {total_packets} latest packets pass validation")

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    section("LANE B PROOF RESULTS")

    print(f"\n  PASS: {PASS}")
    print(f"  FAIL: {FAIL}")

    print(f"\n  STRATEGY REGISTRY:")
    for sid, s in load_all_strategies(ROOT).items():
        print(f"    {sid}: {s.lifecycle_state} (parent={s.parent_id or 'none'})")

    print(f"\n  LATEST PACKETS ({total_packets}):")
    for key, pkt in sorted(all_latest_final.items()):
        print(f"    {key}: {pkt.thesis[:60]}")

    print(f"\n  TRADEFLOOR SYNTHESIS:")
    print(f"    Tier: {tf_pkt.agreement_tier}")
    print(f"    Reasoning: {tf_pkt.agreement_tier_reasoning}")
    print(f"    Operator: {tf_pkt.operator_recommendation}")

    print(f"\n  CALIBRATION RESULTS:")
    print(f"    Good forecast: score={cal_result['calibration_score']:.3f}, direction correct, error={cal_result['value_error']}")
    print(f"    Bad forecast:  score={cal_result2['calibration_score']:.3f}, direction wrong, error={cal_result2['value_error']}")

    print()
    if FAIL == 0:
        print("  \U0001f3af LANE B PROOF: ALL CHECKS PASSED")
    else:
        print(f"  \u26a0\ufe0f  LANE B PROOF: {FAIL} FAILURES")
    print()
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
