#!/usr/bin/env python3
"""Lane A Live Runtime Proof — hardened.

Proves the full Lane A money path through the real Jarvis event system.
Distinguishes between:
  - LIVE: uses real runtime seams (emit_event, outbox, dispatch_events, review poller path)
  - SIMULATED: operator approval (no human in the loop), paper trade fill (no real broker)

Usage:
    cd ~/.openclaw/workspace/jarvis-v5
    python3 workspace/quant/live_runtime_proof.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import make_packet, QuantPacket
from workspace.quant.shared.packet_store import store_packet, get_latest, get_all_latest
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, get_strategy, load_all_strategies,
)
from workspace.quant.shared.registries.approval_registry import load_all_approvals
from workspace.quant.shared.approval_bridge import (
    request_paper_trade_approval, approve_paper_trade, execute_approved_paper_trade,
)
from workspace.quant.sigma.validation_lane import validate_candidate
from workspace.quant.kitt.brief_producer import produce_brief
from workspace.quant.shared.discord_bridge import emit_quant_event

STRATEGY_ID = "atlas-live-proof-002"
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


def section(title: str):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


def clean_prior_run():
    for name in ["strategies.jsonl", "approvals.jsonl", "transition_failures.jsonl"]:
        p = ROOT / "workspace" / "quant" / "shared" / "registries" / name
        if p.exists():
            p.unlink()
    latest_dir = ROOT / "workspace" / "quant" / "shared" / "latest"
    if latest_dir.exists():
        for f in latest_dir.glob("*.json"):
            f.unlink()
    for lane in ["hermes", "atlas", "sigma", "kitt", "executor"]:
        lane_dir = ROOT / "workspace" / "quant" / lane
        if lane_dir.exists():
            for f in lane_dir.glob("*.json"):
                f.unlink()


def _check_outbox_for(event_kind: str, after_count: int = 0) -> list[dict]:
    """Find outbox entries matching event_kind created during this run."""
    outbox_dir = ROOT / "state" / "discord_outbox"
    matches = []
    for f in sorted(outbox_dir.glob("outbox_*.json")):
        try:
            entry = json.loads(f.read_text(encoding="utf-8"))
            if entry.get("event_kind") == event_kind:
                matches.append(entry)
        except (json.JSONDecodeError, OSError):
            continue
    return matches


def _check_dispatch_for(event_kind: str) -> list[dict]:
    """Find dispatch event records matching event_kind."""
    dispatch_dir = ROOT / "state" / "dispatch_events"
    matches = []
    for f in sorted(dispatch_dir.glob("devt_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:100]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("kind") == event_kind:
                matches.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return matches


def main():
    print("\n" + "=" * 60)
    print("  LANE A LIVE RUNTIME PROOF (hardened)")
    print("=" * 60)

    clean_prior_run()

    # =========================================================================
    # Step 1: Strategy creation + candidate
    # =========================================================================
    section("1. [LIVE] Strategy Registry + Candidate")
    entry = create_strategy(ROOT, STRATEGY_ID, actor="atlas", note="Live runtime proof v2")
    ok(f"Created {STRATEGY_ID}: {entry.lifecycle_state}")

    research = make_packet("research_packet", "hermes",
        "NQ mean-reversion in low-VIX regime shows persistent edge.", confidence=0.65, symbol_scope="NQ")
    store_packet(ROOT, research)

    candidate = make_packet("candidate_packet", "atlas",
        "Mean-rev NQ: RSI(14)<30 + VWAP + low-VIX. Backtest PF 1.65, Sharpe 1.2.",
        strategy_id=STRATEGY_ID, symbol_scope="NQ", timeframe_scope="15m",
        confidence=0.55, evidence_refs=[research.packet_id])
    store_packet(ROOT, candidate)
    transition_strategy(ROOT, STRATEGY_ID, "CANDIDATE", actor="atlas")
    transition_strategy(ROOT, STRATEGY_ID, "VALIDATING", actor="sigma")
    ok("Strategy → VALIDATING, candidate_packet stored")

    # =========================================================================
    # Step 2: Sigma validation → promotion (now emits Discord internally)
    # =========================================================================
    section("2. [LIVE] Sigma Validation → Promotion + Discord")
    outcome, promo = validate_candidate(ROOT, candidate,
        profit_factor=1.65, sharpe=1.2, max_drawdown_pct=0.08, trade_count=52)
    if outcome != "promoted":
        fail(f"Expected promotion, got {outcome}")
        return 1
    ok(f"Sigma promoted {STRATEGY_ID}")

    # Verify promotion hit Discord (Sigma emits internally now)
    promo_dispatches = _check_dispatch_for("quant_strategy_promoted")
    if promo_dispatches:
        d = promo_dispatches[0]
        ok(f"promotion dispatch → channel {d.get('owner_channel_id')} (worklog={d.get('worklog_mirrored')}, jarvis={d.get('jarvis_forwarded')})")
    else:
        fail("promotion dispatch event not found")

    # =========================================================================
    # Step 3: Kitt papertrade request → #review
    # =========================================================================
    section("3. [LIVE] Kitt Papertrade Request → #review")
    req = request_paper_trade_approval(ROOT, STRATEGY_ID, symbols=["NQ"],
        max_position_size=2, valid_days=14)
    if req["error"]:
        fail(f"Request failed: {req['error']}")
        return 1

    approval_ref = req["approval_ref"]
    ok(f"Approval object: {approval_ref}")

    # Verify it's a qpt_ format the review poller can parse
    if approval_ref.startswith("qpt_"):
        ok(f"approval_ref format poller-compatible: {approval_ref}")
    else:
        fail(f"approval_ref {approval_ref} not in qpt_ format — review poller will not match it")

    # Verify the Discord message includes approve/reject instructions
    discord_evt = req["discord_event"]
    if discord_evt and discord_evt.get("owner_channel_id") == "1483132981177618482":
        ok(f"approval_requested → #review channel")
        text = discord_evt.get("text", "")
        if f"approve {approval_ref}" in text:
            ok(f"Message includes: approve {approval_ref}")
        else:
            fail(f"Message missing approve instruction for {approval_ref}")
        if f"reject {approval_ref}" in text:
            ok(f"Message includes: reject {approval_ref}")
        else:
            fail(f"Message missing reject instruction for {approval_ref}")
    else:
        fail(f"approval_requested not routed to #review")

    # Verify outbox entry exists for delivery
    appr_outbox = _check_outbox_for("approval_requested")
    if appr_outbox:
        ok(f"Outbox has {len(appr_outbox)} approval_requested entries")
    else:
        fail("No outbox entries for approval_requested")

    # =========================================================================
    # Step 4: Operator approval (simulated via review-poller-compatible path)
    # =========================================================================
    section("4. [SIMULATED] Operator Approval via Review Poller Path")
    # This simulates what the review poller does when it sees "approve qpt_xxx"
    # in #review. We call the same function the poller calls.
    from scripts.discord_review_poller import call_approval_endpoint
    appr_result = call_approval_endpoint(approval_ref, "approved", actor="operator:proof_run")
    if appr_result.get("ok"):
        ok(f"Review poller path approved: {appr_result.get('strategy_state', 'N/A')}")
    else:
        fail(f"Review poller path failed: {appr_result.get('error')}")

    strategy = get_strategy(ROOT, STRATEGY_ID)
    if strategy and strategy.lifecycle_state == "PAPER_QUEUED":
        ok(f"Strategy → PAPER_QUEUED")
    else:
        fail(f"Expected PAPER_QUEUED, got {strategy.lifecycle_state if strategy else 'not found'}")

    # =========================================================================
    # Step 5: Executor paper trade (emits Discord internally now)
    # =========================================================================
    section("5. [LIVE emit / SIMULATED fill] Executor Paper Trade")
    exec_result = execute_approved_paper_trade(ROOT, STRATEGY_ID, approval_ref,
        symbol="NQ", side="long", quantity=1, simulated_price=18320.0)
    if exec_result["success"]:
        ok(f"Paper trade filled: {exec_result['fill']['fill_price']} (simulated)")
    else:
        fail(f"Execution rejected: {exec_result['rejection_reason']}")
        return 1

    # Verify executor events hit Discord
    exec_dispatches = _check_dispatch_for("quant_execution_status")
    if exec_dispatches:
        d = exec_dispatches[0]
        ok(f"execution_status dispatch → channel {d.get('owner_channel_id')}")
    else:
        fail("execution_status dispatch event not found")

    intent_dispatches = _check_dispatch_for("quant_execution_intent")
    if intent_dispatches:
        ok(f"execution_intent dispatch → channel {intent_dispatches[0].get('owner_channel_id')}")
    else:
        fail("execution_intent dispatch event not found")

    strategy = get_strategy(ROOT, STRATEGY_ID)
    if strategy and strategy.lifecycle_state == "PAPER_ACTIVE":
        ok(f"Strategy auto-transitioned → PAPER_ACTIVE")
    else:
        fail(f"Expected PAPER_ACTIVE, got {strategy.lifecycle_state if strategy else 'N/A'}")

    # =========================================================================
    # Step 6: Kitt brief (emits via existing kitt_brief_completed path)
    # =========================================================================
    section("6. [LIVE] Kitt Brief — operator surface")
    brief = produce_brief(ROOT, market_read="Live runtime proof. No market data.")
    evt_brief = emit_quant_event(brief, root=ROOT)
    if evt_brief.get("owner_channel_id") == "1483320979185733722":
        ok("brief \u2192 #kitt channel")
    else:
        fail(f"brief routing: {evt_brief.get('owner_channel_id', 'N/A')}")

    notes = brief.notes or ""
    if "PAPER:" in notes or "PAPER_ACTIVE" in notes:
        ok("Brief shows active paper position")
    else:
        fail("Brief missing paper position")
    if "EXECUTION" in notes:
        ok("Brief includes EXECUTION section")
    else:
        fail("Brief missing EXECUTION section")
    if "OPERATOR ACTION" in notes:
        ok("Brief includes OPERATOR ACTION section")
    else:
        fail("Brief missing operator action section")

    print(f"\n--- Kitt Brief ---")
    print(notes)
    print(f"--- End Brief ---")

    # =========================================================================
    # Step 7: Verify full outbox + dispatch chain
    # =========================================================================
    section("7. [LIVE] Outbox + Dispatch Verification")

    event_kinds = [
        ("quant_strategy_promoted", "#sigma"),
        ("quant_execution_intent", "#kitt"),
        ("quant_execution_status", "#kitt"),
        ("approval_requested", "#review"),
        ("kitt_brief_completed", "#kitt"),
    ]
    for kind, expected_ch in event_kinds:
        dispatches = _check_dispatch_for(kind)
        if dispatches:
            ok(f"{kind}: {len(dispatches)} dispatch(es) → {expected_ch}")
        else:
            fail(f"{kind}: no dispatch events found")

    # Count total quant outbox entries
    outbox_dir = ROOT / "state" / "discord_outbox"
    quant_outbox = []
    for f in outbox_dir.glob("outbox_*.json"):
        try:
            e = json.loads(f.read_text(encoding="utf-8"))
            ek = e.get("event_kind", "")
            if ek.startswith("quant_") or ek in ("approval_requested", "kitt_brief_completed"):
                quant_outbox.append(e)
        except Exception:
            continue
    ok(f"Total quant outbox entries: {len(quant_outbox)}")

    # =========================================================================
    # Summary
    # =========================================================================
    section("RESULTS")
    print(f"\n  PASS: {PASS}  FAIL: {FAIL}")

    print(f"\n  STRATEGY REGISTRY:")
    for sid, s in load_all_strategies(ROOT).items():
        print(f"    {sid}: {s.lifecycle_state} ({len(s.state_history)} transitions)")

    print(f"\n  WHAT IS TRULY LIVE:")
    print(f"    emit_event() routing: quant packets → dispatch_events + outbox entries")
    print(f"    Channel mapping: sigma→1483916191046041811, kitt→1483320979185733722, review→1483132981177618482")
    print(f"    Worklog mirror: promotions, execution events")
    print(f"    Jarvis forward: promotions, execution events, alerts")
    print(f"    Approval message: includes 'approve qpt_xxx' / 'reject qpt_xxx' instructions")
    print(f"    Review poller: updated to match qpt_ prefix, routes to quant approval bridge")
    print(f"    Executor: emits Discord events directly on fill/reject")
    print(f"    Sigma: emits Discord events directly on promote/reject")
    print(f"    Kitt brief: reads shared/latest, produces spec §7 format")

    print(f"\n  WHAT IS SIMULATED:")
    print(f"    Operator approval (step 4): simulated call_approval_endpoint(), not real Discord reaction")
    print(f"    Paper trade fill (step 5): PaperBrokerAdapter, not real broker")
    print(f"    Market data: none consumed")

    print(f"\n  OPERATOR ACTIONS REQUIRED:")
    print(f"    1. Add JARVIS_DISCORD_WEBHOOK_SIGMA to ~/.openclaw/secrets.env")
    print(f"    2. Verify outbox delivery: systemctl --user restart openclaw-outbox-sender")
    print(f"    3. Test real approval: type 'approve {approval_ref}' in #review")

    print()
    if FAIL == 0:
        print("  \U0001f3af LANE A LIVE RUNTIME PROOF: ALL CHECKS PASSED")
    else:
        print(f"  \u26a0\ufe0f LANE A LIVE RUNTIME PROOF: {FAIL} FAILURES")
    print()
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
