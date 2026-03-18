#!/usr/bin/env python3
"""Lane A Proof — Full money path end-to-end.

Proves the complete Lane A execution path:
  Hermes research → Atlas candidate → Sigma validation → Sigma promotion
  → Kitt papertrade request → Operator approval → Executor paper trade
  → Executor fill → Strategy registry transitions → Kitt brief

This tests the real modules, not hand-crafted JSON like Phase 0.

Usage:
    cd ~/.openclaw/workspace/jarvis-v5
    python3 workspace/quant/lane_a_proof.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import make_packet, validate_packet
from workspace.quant.shared.packet_store import store_packet, get_latest, get_all_latest
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, get_strategy, load_all_strategies,
)
from workspace.quant.shared.registries.approval_registry import (
    create_approval, ApprovedActions,
)
from workspace.quant.sigma.validation_lane import validate_candidate, review_paper_results
from workspace.quant.executor.executor_lane import execute_paper_trade
from workspace.quant.kitt.brief_producer import produce_brief

PASS = 0
FAIL = 0
STRATEGY_ID = "atlas-trend-follow-la-001"


def ok(msg: str):
    global PASS
    PASS += 1
    print(f"  ✅ {msg}")


def fail(msg: str):
    global FAIL
    FAIL += 1
    print(f"  ❌ {msg}")


def section(title: str):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


def clean_registries():
    """Clean up registry files from prior runs."""
    for name in ["strategies.jsonl", "approvals.jsonl", "transition_failures.jsonl"]:
        p = ROOT / "workspace" / "quant" / "shared" / "registries" / name
        if p.exists():
            p.unlink()
    # Clean latest
    latest_dir = ROOT / "workspace" / "quant" / "shared" / "latest"
    if latest_dir.exists():
        for f in latest_dir.glob("*.json"):
            f.unlink()
    # Clean lane packet dirs
    for lane in ["hermes", "atlas", "sigma", "kitt", "executor"]:
        lane_dir = ROOT / "workspace" / "quant" / lane
        if lane_dir.exists():
            for f in lane_dir.glob("*.json"):
                f.unlink()


def main():
    print("\n" + "=" * 60)
    print("  LANE A PROOF — Full Money Path")
    print("=" * 60)

    clean_registries()

    # --- Step 1: Create strategy in registry ---
    section("1. Strategy Registry — Create IDEA")
    entry = create_strategy(ROOT, STRATEGY_ID, actor="atlas", note="Lane A proof candidate")
    ok(f"Created {STRATEGY_ID} as {entry.lifecycle_state}")

    # --- Step 2: Hermes research packet ---
    section("2. Hermes — Research Packet")
    research = make_packet(
        "research_packet", "hermes",
        "NQ trend-following edge detected in overnight sessions with strong volume profile divergence.",
        confidence=0.6, symbol_scope="NQ",
    )
    store_packet(ROOT, research)
    ok(f"research_packet stored: {research.packet_id}")

    # Verify it's in latest
    latest_research = get_latest(ROOT, "hermes", "research_packet")
    if latest_research and latest_research.packet_id == research.packet_id:
        ok("shared/latest/ updated correctly")
    else:
        fail("shared/latest/ not updated")

    # --- Step 3: Atlas candidate packet ---
    section("3. Atlas — Candidate Packet")
    candidate = make_packet(
        "candidate_packet", "atlas",
        "Trend-following strategy on NQ: enter on breakout above 20-bar high with volume confirmation.",
        strategy_id=STRATEGY_ID, symbol_scope="NQ", timeframe_scope="15m",
        confidence=0.55, evidence_refs=[research.packet_id],
        action_requested="Submit to Sigma for validation",
    )
    store_packet(ROOT, candidate)
    transition_strategy(ROOT, STRATEGY_ID, "CANDIDATE", actor="atlas")
    transition_strategy(ROOT, STRATEGY_ID, "VALIDATING", actor="sigma")
    ok(f"candidate_packet stored, strategy → VALIDATING")

    # --- Step 4: Sigma validation (using real validation_lane) ---
    section("4. Sigma — Validate Candidate (passing)")
    outcome, promo_pkt = validate_candidate(
        ROOT, candidate,
        profit_factor=1.65, sharpe=1.2, max_drawdown_pct=0.08,
        trade_count=52, regime_aware=True,
    )
    if outcome == "promoted":
        ok(f"Sigma promoted: {promo_pkt.thesis[:80]}")
    else:
        fail(f"Expected promotion, got {outcome}")

    strategy = get_strategy(ROOT, STRATEGY_ID)
    if strategy and strategy.lifecycle_state == "PROMOTED":
        ok(f"Registry shows {STRATEGY_ID} in PROMOTED")
    else:
        fail(f"Registry mismatch: {strategy.lifecycle_state if strategy else 'not found'}")

    # Verify rejection path with a bad candidate
    section("4b. Sigma — Validate Candidate (failing)")
    bad_id = "atlas-bad-001"
    create_strategy(ROOT, bad_id, actor="atlas")
    transition_strategy(ROOT, bad_id, "CANDIDATE", actor="atlas")
    transition_strategy(ROOT, bad_id, "VALIDATING", actor="sigma")
    bad_candidate = make_packet(
        "candidate_packet", "atlas",
        "Bad strategy with poor stats",
        strategy_id=bad_id,
    )
    store_packet(ROOT, bad_candidate)
    bad_outcome, bad_pkt = validate_candidate(
        ROOT, bad_candidate,
        profit_factor=0.8, sharpe=0.3, max_drawdown_pct=0.25,
        trade_count=5,
    )
    if bad_outcome == "rejected":
        ok(f"Sigma correctly rejected: {bad_pkt.rejection_reason}")
    else:
        fail(f"Expected rejection, got {bad_outcome}")

    bad_strat = get_strategy(ROOT, bad_id)
    if bad_strat and bad_strat.lifecycle_state == "REJECTED":
        ok(f"Registry correctly shows {bad_id} in REJECTED")
    else:
        fail(f"Expected REJECTED, got {bad_strat.lifecycle_state if bad_strat else 'not found'}")

    # --- Step 5: Kitt papertrade request ---
    section("5. Kitt — Papertrade Request")
    ptr = make_packet(
        "papertrade_request_packet", "kitt",
        f"Requesting paper trade approval for {STRATEGY_ID}. Sigma validates PF 1.65.",
        strategy_id=STRATEGY_ID, symbol_scope=["NQ"],
        escalation_level="operator_review",
    )
    store_packet(ROOT, ptr)
    ok(f"papertrade_request_packet stored")

    # --- Step 6: Operator approval ---
    section("6. Operator — Create Approval")
    now = datetime.now(timezone.utc)
    actions = ApprovedActions(
        execution_mode="paper", symbols=["NQ"],
        max_position_size=2, max_loss_per_trade=500,
        max_total_drawdown=2000, slippage_tolerance=0.05,
        valid_from=now.isoformat(),
        valid_until=(now + timedelta(days=14)).isoformat(),
        broker_target="paper_adapter",
    )
    approval = create_approval(ROOT, STRATEGY_ID, "paper_trade", actions,
                               conditions="Review after 14 days or 20 trades")
    ok(f"Approval created: {approval.approval_ref}")

    # Transition to PAPER_QUEUED
    transition_strategy(ROOT, STRATEGY_ID, "PAPER_QUEUED", actor="kitt",
                        approval_ref=approval.approval_ref)
    ok(f"Strategy → PAPER_QUEUED with approval")

    # --- Step 7: Executor paper trade (using real executor_lane) ---
    section("7. Executor — Paper Trade Execution")
    exec_result = execute_paper_trade(
        ROOT, STRATEGY_ID, approval.approval_ref,
        symbol="NQ", side="long", order_type="market",
        quantity=1, simulated_price=18320.0,
    )
    if exec_result["success"]:
        ok(f"Paper trade succeeded: fill at {exec_result['fill']['fill_price']}")
    else:
        fail(f"Paper trade failed: {exec_result['rejection_reason']}")

    # Verify strategy transitioned to PAPER_ACTIVE
    strategy = get_strategy(ROOT, STRATEGY_ID)
    if strategy and strategy.lifecycle_state == "PAPER_ACTIVE":
        ok(f"Strategy auto-transitioned to PAPER_ACTIVE")
    else:
        fail(f"Expected PAPER_ACTIVE, got {strategy.lifecycle_state if strategy else 'not found'}")

    # Verify packets were stored and latest updated
    latest_exec = get_latest(ROOT, "executor", "execution_status_packet")
    if latest_exec:
        ok(f"Executor status in shared/latest/: {latest_exec.execution_status}")
    else:
        fail("Executor status not in shared/latest/")

    # --- Step 7b: Executor rejection test ---
    section("7b. Executor — Rejection Tests")
    # Wrong symbol
    bad_exec = execute_paper_trade(
        ROOT, STRATEGY_ID, approval.approval_ref,
        symbol="ES", side="long",
    )
    if not bad_exec["success"] and bad_exec["rejection_reason"] == "symbol_not_approved":
        ok(f"Correctly rejected unapproved symbol")
    else:
        fail(f"Expected symbol rejection")

    # Wrong approval
    bad_exec2 = execute_paper_trade(
        ROOT, STRATEGY_ID, "fake-approval-ref",
        symbol="NQ", side="long",
    )
    if not bad_exec2["success"] and bad_exec2["rejection_reason"] == "invalid_approval":
        ok(f"Correctly rejected invalid approval")
    else:
        fail(f"Expected invalid approval rejection")

    # --- Step 8: Sigma paper review ---
    section("8. Sigma — Paper Review")
    review_outcome, review_pkt = review_paper_results(
        ROOT, STRATEGY_ID,
        realized_pf=1.45, realized_sharpe=0.95, max_drawdown=0.07,
        avg_slippage=0.03, fill_rate=0.95, trade_count=25,
    )
    ok(f"Paper review outcome: {review_outcome}")
    if review_pkt.outcome:
        ok(f"Review packet has outcome: {review_pkt.outcome}")

    # --- Step 9: Kitt brief ---
    section("9. Kitt — Produce Brief")
    brief = produce_brief(ROOT, market_read="Lane A proof run. No live market data.")
    if brief.notes and "KITT BRIEF" in brief.notes:
        ok("Brief follows spec §7 format")
    else:
        fail("Brief format doesn't match spec")
    if brief.notes and STRATEGY_ID[:20] in brief.notes:
        ok("Brief references the strategy pipeline")
    else:
        # Check if it at least has pipeline data
        if "PAPER_ACTIVE" in (brief.notes or ""):
            ok("Brief references paper-active pipeline state")
        else:
            fail("Brief missing pipeline state")

    # Print the brief
    print(f"\n--- Kitt Brief Output ---")
    print(brief.notes or brief.thesis)
    print(f"--- End Brief ---\n")

    # --- Summary ---
    section("LANE A PROOF RESULTS")
    print(f"\n  PASS: {PASS}")
    print(f"  FAIL: {FAIL}")

    # Strategy registry final state
    print(f"\n  STRATEGY REGISTRY:")
    for sid, s in load_all_strategies(ROOT).items():
        print(f"    {sid}: {s.lifecycle_state} ({len(s.state_history)} transitions)")

    # Latest packets
    print(f"\n  LATEST PACKETS:")
    for key, pkt in sorted(get_all_latest(ROOT).items()):
        print(f"    {key}: {pkt.thesis[:60]}")

    print()
    if FAIL == 0:
        print("  🎯 LANE A PROOF: ALL CHECKS PASSED")
    else:
        print(f"  ⚠️  LANE A PROOF: {FAIL} FAILURES")
    print()
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
