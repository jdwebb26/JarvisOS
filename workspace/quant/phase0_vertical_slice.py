#!/usr/bin/env python3
"""Phase 0 Vertical Slice — Prove the quant lanes core loop.

Per QUANT_LANES_OPERATING_SPEC v3.5.1 §21, Phase 0 scope:
  One candidate, one pass/reject, one paper approval, one Executor dry-run, one Kitt brief.

This script:
  1. Creates a research_packet (Hermes)
  2. Creates a candidate_packet (Atlas) referencing research
  3. Creates a validation_packet + promotion_packet (Sigma)
  4. Creates a papertrade_candidate_packet (Sigma → Kitt)
  5. Creates a papertrade_request_packet (Kitt → Executor)
  6. Creates an approval_object (operator)
  7. Validates approval via Executor pre-flight
  8. Creates execution_intent_packet + execution_status_packet (Executor dry-run)
  9. Creates a brief_packet (Kitt)
  10. Walks strategy registry through: IDEA → CANDIDATE → VALIDATING → PROMOTED → PAPER_QUEUED

Proves: packet contracts, registry transitions, approval validation, end-to-end flow.

Usage:
    cd ~/.openclaw/workspace/jarvis-v5
    python3 workspace/quant/phase0_vertical_slice.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import (
    make_packet, validate_packet, save_packet, QuantPacket,
)
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, get_strategy, load_all_strategies,
)
from workspace.quant.shared.registries.approval_registry import (
    create_approval, validate_approval_for_execution, ApprovedActions, get_approval,
)

QUANT_DIR = ROOT / "workspace" / "quant"
SHARED_DIR = QUANT_DIR / "shared"
STATE_DIR = ROOT / "state" / "quant"

# Ensure directories
for lane in ["hermes", "atlas", "sigma", "kitt", "executor"]:
    (QUANT_DIR / lane).mkdir(parents=True, exist_ok=True)

STRATEGY_ID = "atlas-mean-rev-p0-001"
PASS_COUNT = 0
FAIL_COUNT = 0
FRICTION_LOG: list[str] = []


def _ok(msg: str):
    global PASS_COUNT
    PASS_COUNT += 1
    print(f"  ✅ {msg}")


def _fail(msg: str):
    global FAIL_COUNT
    FAIL_COUNT += 1
    print(f"  ❌ {msg}")


def _friction(msg: str):
    FRICTION_LOG.append(msg)
    print(f"  ⚠️  FRICTION: {msg}")


def _section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Step 1: Research packet (Hermes)
# ---------------------------------------------------------------------------

def step1_research_packet() -> QuantPacket:
    _section("Step 1: Research Packet (Hermes)")

    p = make_packet(
        packet_type="research_packet",
        lane="hermes",
        thesis="NQ mean-reversion signals strengthen during low-VIX regimes below 15, particularly in the 4100-4200 range with overnight session convergence patterns.",
        priority="medium",
        symbol_scope="NQ",
        timeframe_scope="15m",
        confidence=0.65,
        notes="Source: CME historical analysis + academic paper on overnight convergence in equity index futures.",
    )

    errors = validate_packet(p)
    if errors:
        _fail(f"research_packet validation failed: {errors}")
    else:
        _ok("research_packet validates")

    path = save_packet(p, QUANT_DIR / "hermes")
    _ok(f"research_packet saved: {Path(path).name}")

    return p


# ---------------------------------------------------------------------------
# Step 2: Candidate packet (Atlas)
# ---------------------------------------------------------------------------

def step2_candidate_packet(research: QuantPacket) -> QuantPacket:
    _section("Step 2: Candidate Packet (Atlas)")

    p = make_packet(
        packet_type="candidate_packet",
        lane="atlas",
        thesis="Mean-reversion strategy on NQ 15m bars: enter long when RSI(14) < 30 and price within 1σ of VWAP during low-VIX regime. Exit at VWAP or +0.5σ.",
        priority="high",
        strategy_id=STRATEGY_ID,
        symbol_scope="NQ",
        timeframe_scope="15m",
        confidence=0.55,
        evidence_refs=[research.packet_id],
        action_requested="Submit to Sigma for validation",
        escalation_level="team_only",
    )

    errors = validate_packet(p)
    if errors:
        _fail(f"candidate_packet validation failed: {errors}")
    else:
        _ok("candidate_packet validates")

    path = save_packet(p, QUANT_DIR / "atlas")
    _ok(f"candidate_packet saved: {Path(path).name}")

    return p


# ---------------------------------------------------------------------------
# Step 3: Validation + Promotion (Sigma)
# ---------------------------------------------------------------------------

def step3_validation_and_promotion(candidate: QuantPacket) -> QuantPacket:
    _section("Step 3: Validation + Promotion (Sigma)")

    # Validation packet
    val = make_packet(
        packet_type="validation_packet",
        lane="sigma",
        thesis=f"Strategy {STRATEGY_ID} passes walk-forward validation: PF 1.62, Sharpe 1.1, max DD 8.3%, 47 trades, regime-aware.",
        priority="high",
        strategy_id=STRATEGY_ID,
        evidence_refs=[candidate.packet_id],
        confidence=0.72,
    )
    errors = validate_packet(val)
    if errors:
        _fail(f"validation_packet validation failed: {errors}")
    else:
        _ok("validation_packet validates")
    save_packet(val, QUANT_DIR / "sigma")

    # Promotion packet
    promo = make_packet(
        packet_type="promotion_packet",
        lane="sigma",
        thesis=f"Strategy {STRATEGY_ID} promoted: meets all validation gates. Recommend paper trade evaluation.",
        priority="high",
        strategy_id=STRATEGY_ID,
        evidence_refs=[val.packet_id, candidate.packet_id],
        confidence=0.72,
        action_requested="Kitt: evaluate for paper trade request",
        escalation_level="kitt_only",
    )
    errors = validate_packet(promo)
    if errors:
        _fail(f"promotion_packet validation failed: {errors}")
    else:
        _ok("promotion_packet validates")
    save_packet(promo, QUANT_DIR / "sigma")

    return promo


# ---------------------------------------------------------------------------
# Step 4: Papertrade candidate packet (Sigma → Kitt)
# ---------------------------------------------------------------------------

def step4_papertrade_candidate(promotion: QuantPacket) -> QuantPacket:
    _section("Step 4: Papertrade Candidate Packet (Sigma → Kitt)")

    p = make_packet(
        packet_type="papertrade_candidate_packet",
        lane="sigma",
        thesis=f"Strategy {STRATEGY_ID} fit for paper trading. PF 1.62, Sharpe 1.1, max DD 8.3%.",
        priority="high",
        strategy_id=STRATEGY_ID,
        evidence_refs=[promotion.packet_id],
        confidence=0.72,
        action_requested="Kitt: request operator approval for paper trade",
    )
    errors = validate_packet(p)
    if errors:
        _fail(f"papertrade_candidate_packet validation failed: {errors}")
    else:
        _ok("papertrade_candidate_packet validates")

    path = save_packet(p, QUANT_DIR / "sigma")
    _ok(f"papertrade_candidate_packet saved: {Path(path).name}")

    return p


# ---------------------------------------------------------------------------
# Step 5: Papertrade request packet (Kitt → Executor)
# ---------------------------------------------------------------------------

def step5_papertrade_request(candidate_pkt: QuantPacket) -> QuantPacket:
    _section("Step 5: Papertrade Request Packet (Kitt → Executor)")

    p = make_packet(
        packet_type="papertrade_request_packet",
        lane="kitt",
        thesis=f"Requesting operator approval for paper trading {STRATEGY_ID}. Sigma validates PF 1.62.",
        priority="high",
        strategy_id=STRATEGY_ID,
        symbol_scope=["NQ"],
        evidence_refs=[candidate_pkt.packet_id],
        escalation_level="operator_review",
        action_requested="Operator: approve paper trade for this strategy",
    )
    errors = validate_packet(p)
    if errors:
        _fail(f"papertrade_request_packet validation failed: {errors}")
    else:
        _ok("papertrade_request_packet validates")

    path = save_packet(p, QUANT_DIR / "kitt")
    _ok(f"papertrade_request_packet saved: {Path(path).name}")

    return p


# ---------------------------------------------------------------------------
# Step 6: Approval object (operator)
# ---------------------------------------------------------------------------

def step6_create_approval() -> str:
    _section("Step 6: Approval Object (Operator)")

    now = datetime.now(timezone.utc)
    actions = ApprovedActions(
        execution_mode="paper",
        symbols=["NQ"],
        max_position_size=2,
        max_loss_per_trade=500,
        max_total_drawdown=2000,
        slippage_tolerance=0.05,
        valid_from=now.isoformat(),
        valid_until=(now + timedelta(days=14)).isoformat(),
        broker_target="paper_adapter",
    )

    approval = create_approval(
        root=ROOT,
        strategy_id=STRATEGY_ID,
        approval_type="paper_trade",
        approved_actions=actions,
        conditions="Review after 14 days or 20 trades, whichever comes first.",
    )

    _ok(f"Approval created: {approval.approval_ref}")

    # Validate it
    valid, reason = approval.is_valid()
    if valid:
        _ok(f"Approval is valid: {reason}")
    else:
        _fail(f"Approval invalid: {reason}")

    return approval.approval_ref


# ---------------------------------------------------------------------------
# Step 7: Executor pre-flight validation
# ---------------------------------------------------------------------------

def step7_executor_preflight(approval_ref: str):
    _section("Step 7: Executor Pre-flight Validation")

    # Valid case
    valid, reason = validate_approval_for_execution(
        root=ROOT,
        approval_ref=approval_ref,
        strategy_id=STRATEGY_ID,
        execution_mode="paper",
        symbol="NQ",
    )
    if valid:
        _ok(f"Pre-flight PASS: {reason}")
    else:
        _fail(f"Pre-flight FAIL (should pass): {reason}")

    # Invalid case: wrong strategy
    valid2, reason2 = validate_approval_for_execution(
        root=ROOT,
        approval_ref=approval_ref,
        strategy_id="wrong-strategy-id",
        execution_mode="paper",
        symbol="NQ",
    )
    if not valid2:
        _ok(f"Pre-flight correctly rejects wrong strategy: {reason2}")
    else:
        _fail("Pre-flight should have rejected wrong strategy_id")

    # Invalid case: wrong symbol
    valid3, reason3 = validate_approval_for_execution(
        root=ROOT,
        approval_ref=approval_ref,
        strategy_id=STRATEGY_ID,
        execution_mode="paper",
        symbol="ES",
    )
    if not valid3:
        _ok(f"Pre-flight correctly rejects unapproved symbol: {reason3}")
    else:
        _fail("Pre-flight should have rejected unapproved symbol")

    # Invalid case: wrong mode
    valid4, reason4 = validate_approval_for_execution(
        root=ROOT,
        approval_ref=approval_ref,
        strategy_id=STRATEGY_ID,
        execution_mode="live",
        symbol="NQ",
    )
    if not valid4:
        _ok(f"Pre-flight correctly rejects mode mismatch: {reason4}")
    else:
        _fail("Pre-flight should have rejected live mode against paper approval")

    # Invalid case: nonexistent approval
    valid5, reason5 = validate_approval_for_execution(
        root=ROOT,
        approval_ref="approval-nonexistent-001",
        strategy_id=STRATEGY_ID,
        execution_mode="paper",
        symbol="NQ",
    )
    if not valid5:
        _ok(f"Pre-flight correctly rejects missing approval: {reason5}")
    else:
        _fail("Pre-flight should have rejected nonexistent approval")


# ---------------------------------------------------------------------------
# Step 8: Execution packets (Executor dry-run)
# ---------------------------------------------------------------------------

def step8_execution_packets(approval_ref: str) -> QuantPacket:
    _section("Step 8: Execution Packets (Executor Dry-Run)")

    # Execution intent
    intent = make_packet(
        packet_type="execution_intent_packet",
        lane="executor",
        thesis=f"Paper trade intent for {STRATEGY_ID}: long NQ, limit order near VWAP.",
        priority="high",
        strategy_id=STRATEGY_ID,
        execution_mode="paper",
        symbol="NQ",
        side="long",
        order_type="limit",
        approval_ref=approval_ref,
        sizing={"method": "fixed", "contracts": 1},
        risk_limits={"max_loss": 500, "max_position": 2},
    )
    errors = validate_packet(intent)
    if errors:
        _fail(f"execution_intent_packet validation failed: {errors}")
    else:
        _ok("execution_intent_packet validates")
    save_packet(intent, QUANT_DIR / "executor")

    # Execution status (simulated fill)
    status = make_packet(
        packet_type="execution_status_packet",
        lane="executor",
        thesis=f"Paper trade executed for {STRATEGY_ID}: filled 1 NQ at 18245.50 (simulated).",
        priority="medium",
        strategy_id=STRATEGY_ID,
        execution_mode="paper",
        symbol="NQ",
        approval_ref=approval_ref,
        execution_status="filled",
        fill_price=18245.50,
        slippage=0.02,
    )
    errors = validate_packet(status)
    if errors:
        _fail(f"execution_status_packet validation failed: {errors}")
    else:
        _ok("execution_status_packet validates")
    save_packet(status, QUANT_DIR / "executor")

    return status


# ---------------------------------------------------------------------------
# Step 9: Brief packet (Kitt)
# ---------------------------------------------------------------------------

def step9_brief_packet(exec_status: QuantPacket) -> QuantPacket:
    _section("Step 9: Brief Packet (Kitt)")

    brief = make_packet(
        packet_type="brief_packet",
        lane="kitt",
        thesis="Phase 0 vertical slice complete. Strategy atlas-mean-rev-p0-001 walked through full lifecycle: research → candidate → validation → promotion → paper approval → executor dry-run.",
        priority="medium",
        evidence_refs=[exec_status.packet_id],
        escalation_level="none",
        notes="""KITT BRIEF — Phase 0 Proof
━━━━━━━━━━━━━━━━━━━━━━━━━

MARKET READ
Phase 0 proof run — no live market data consumed.

TOP SIGNAL
Vertical slice proves packet contracts, registry transitions, and approval validation work end-to-end.

PIPELINE
  PAPER_QUEUED: 1 strategy (atlas-mean-rev-p0-001)
  LIVE_ACTIVE:  0 strategies

LANE ACTIVITY
  Hermes: 1 research_packet (NQ mean-reversion)
  Atlas:  1 candidate_packet (mean-rev RSI/VWAP)
  Sigma:  validation → promotion → papertrade_candidate
  Executor: dry-run fill (paper, simulated)

SYSTEM HEALTH
  Active lanes: hermes, atlas, sigma, kitt, executor (Phase 0 proof only)
  Silent/errored: none
  Governor: not yet active

OPERATOR ACTION NEEDED
  none (Phase 0 proof — no real trades)""",
    )
    errors = validate_packet(brief)
    if errors:
        _fail(f"brief_packet validation failed: {errors}")
    else:
        _ok("brief_packet validates")

    path = save_packet(brief, QUANT_DIR / "kitt")
    _ok(f"brief_packet saved: {Path(path).name}")

    return brief


# ---------------------------------------------------------------------------
# Step 10: Strategy registry lifecycle walk
# ---------------------------------------------------------------------------

def step10_registry_lifecycle(approval_ref: str):
    _section("Step 10: Strategy Registry Lifecycle Walk")

    # Create strategy
    entry = create_strategy(ROOT, STRATEGY_ID, actor="atlas", note="Phase 0 proof candidate")
    _ok(f"Created strategy {STRATEGY_ID} in state {entry.lifecycle_state}")

    # IDEA → CANDIDATE
    entry = transition_strategy(ROOT, STRATEGY_ID, "CANDIDATE", actor="atlas", note="Packaged with thesis + evidence")
    _ok(f"Transitioned to {entry.lifecycle_state}")

    # CANDIDATE → VALIDATING
    entry = transition_strategy(ROOT, STRATEGY_ID, "VALIDATING", actor="sigma", note="Sigma accepts for review")
    _ok(f"Transitioned to {entry.lifecycle_state}")

    # VALIDATING → PROMOTED
    entry = transition_strategy(ROOT, STRATEGY_ID, "PROMOTED", actor="sigma", note="Passes validation: PF 1.62, Sharpe 1.1")
    _ok(f"Transitioned to {entry.lifecycle_state}")

    # PROMOTED → PAPER_QUEUED (requires approval_ref)
    entry = transition_strategy(ROOT, STRATEGY_ID, "PAPER_QUEUED", actor="kitt", approval_ref=approval_ref, note="Operator approved paper trade")
    _ok(f"Transitioned to {entry.lifecycle_state} with approval_ref={approval_ref}")

    # Verify final state
    final = get_strategy(ROOT, STRATEGY_ID)
    if final and final.lifecycle_state == "PAPER_QUEUED":
        _ok(f"Registry shows {STRATEGY_ID} in {final.lifecycle_state}")
        _ok(f"State history has {len(final.state_history)} entries")
    else:
        _fail("Registry state mismatch")

    # Test unauthorized transition
    try:
        transition_strategy(ROOT, STRATEGY_ID, "LIVE_ACTIVE", actor="atlas")
        _fail("Should have rejected unauthorized transition")
    except ValueError as e:
        _ok(f"Correctly rejected unauthorized transition: {e}")

    # Test transition from terminal state (create a separate test strategy)
    test_id = "atlas-test-terminal-001"
    create_strategy(ROOT, test_id, actor="atlas")
    transition_strategy(ROOT, test_id, "CANDIDATE", actor="atlas")
    transition_strategy(ROOT, test_id, "VALIDATING", actor="sigma")
    transition_strategy(ROOT, test_id, "REJECTED", actor="sigma", note="Test rejection")
    try:
        transition_strategy(ROOT, test_id, "CANDIDATE", actor="atlas")
        _fail("Should have rejected transition from terminal state")
    except ValueError as e:
        _ok(f"Correctly rejected transition from terminal: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 60)
    print("  PHASE 0 VERTICAL SLICE — Quant Lanes Proof")
    print("  Spec: QUANT_LANES_OPERATING_SPEC v3.5.1")
    print("=" * 60)

    # Clean up any prior run artifacts
    reg_path = ROOT / "workspace" / "quant" / "shared" / "registries" / "strategies.jsonl"
    if reg_path.exists():
        reg_path.unlink()
    appr_path = ROOT / "workspace" / "quant" / "shared" / "registries" / "approvals.jsonl"
    if appr_path.exists():
        appr_path.unlink()

    # Run all steps
    research = step1_research_packet()
    candidate = step2_candidate_packet(research)
    promotion = step3_validation_and_promotion(candidate)
    ptc = step4_papertrade_candidate(promotion)
    ptr = step5_papertrade_request(ptc)
    approval_ref = step6_create_approval()
    step7_executor_preflight(approval_ref)
    exec_status = step8_execution_packets(approval_ref)
    step9_brief_packet(exec_status)
    step10_registry_lifecycle(approval_ref)

    # Summary
    _section("RESULTS")
    print(f"\n  PASS: {PASS_COUNT}")
    print(f"  FAIL: {FAIL_COUNT}")

    if FRICTION_LOG:
        print(f"\n  FRICTION POINTS ({len(FRICTION_LOG)}):")
        for f in FRICTION_LOG:
            print(f"    - {f}")
    else:
        print("\n  FRICTION POINTS: none detected")

    # List generated artifacts
    print(f"\n  ARTIFACTS GENERATED:")
    for lane in ["hermes", "atlas", "sigma", "kitt", "executor"]:
        lane_dir = QUANT_DIR / lane
        files = sorted(lane_dir.glob("*.json"))
        for f in files:
            print(f"    {lane}/{f.name}")

    registries = QUANT_DIR / "shared" / "registries"
    for f in sorted(registries.glob("*.jsonl")):
        print(f"    shared/registries/{f.name}")

    # Final strategies
    print(f"\n  STRATEGY REGISTRY:")
    for sid, s in load_all_strategies(ROOT).items():
        print(f"    {sid}: {s.lifecycle_state} ({len(s.state_history)} transitions)")

    print()
    if FAIL_COUNT == 0:
        print("  🎯 PHASE 0 VERTICAL SLICE: ALL CHECKS PASSED")
    else:
        print(f"  ⚠️  PHASE 0 VERTICAL SLICE: {FAIL_COUNT} FAILURES")
    print()

    return FAIL_COUNT


if __name__ == "__main__":
    sys.exit(main())
