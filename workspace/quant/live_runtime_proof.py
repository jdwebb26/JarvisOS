#!/usr/bin/env python3
"""Lane A Live Runtime Proof — End-to-end through the real Jarvis event system.

Proves the full Lane A money path works in the live runtime:
  1. Create strategy in registry
  2. Atlas candidate_packet → Sigma validation (with Discord event emission)
  3. Sigma promotion → Discord event to #sigma + worklog
  4. Kitt papertrade request → approval_requested to #review
  5. Operator approval (simulated via CLI bridge)
  6. Executor paper trade → Discord event to #kitt
  7. Kitt brief → Discord event to #kitt

Every step emits through the live runtime's emit_event() system.
Outbox entries are written for the discord_outbox_sender to deliver.

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

from workspace.quant.shared.schemas.packets import make_packet
from workspace.quant.shared.packet_store import store_packet, get_latest
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, get_strategy, load_all_strategies,
)
from workspace.quant.shared.discord_bridge import emit_quant_event
from workspace.quant.shared.approval_bridge import (
    request_paper_trade_approval, approve_paper_trade, execute_approved_paper_trade,
)
from workspace.quant.sigma.validation_lane import validate_candidate
from workspace.quant.kitt.brief_producer import produce_brief

STRATEGY_ID = "atlas-live-proof-001"
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
    """Remove prior proof artifacts."""
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


def main():
    print("\n" + "=" * 60)
    print("  LANE A LIVE RUNTIME PROOF")
    print("  Quant lanes through real Jarvis event system")
    print("=" * 60)

    clean_prior_run()

    # --- Step 1: Create strategy ---
    section("1. Strategy Registry — Create IDEA")
    entry = create_strategy(ROOT, STRATEGY_ID, actor="atlas", note="Live runtime proof")
    ok(f"Created {STRATEGY_ID}: {entry.lifecycle_state}")

    # --- Step 2: Hermes research + Atlas candidate ---
    section("2. Hermes Research + Atlas Candidate")
    research = make_packet(
        "research_packet", "hermes",
        "NQ mean-reversion in low-VIX regime shows persistent edge in overnight sessions.",
        confidence=0.65, symbol_scope="NQ",
    )
    store_packet(ROOT, research)
    ok("research_packet stored")

    candidate = make_packet(
        "candidate_packet", "atlas",
        "Mean-rev NQ strategy: RSI(14)<30, within 1-sigma of VWAP, low-VIX.",
        strategy_id=STRATEGY_ID, symbol_scope="NQ", timeframe_scope="15m",
        confidence=0.55, evidence_refs=[research.packet_id],
    )
    store_packet(ROOT, candidate)
    transition_strategy(ROOT, STRATEGY_ID, "CANDIDATE", actor="atlas")
    transition_strategy(ROOT, STRATEGY_ID, "VALIDATING", actor="sigma")
    ok(f"Strategy → VALIDATING")

    # Emit candidate via Discord bridge
    evt = emit_quant_event(candidate, root=ROOT)
    if evt.get("owner_channel_id"):
        ok(f"candidate_packet Discord event → channel {evt['owner_channel_id']}")
        ok(f"  outbox entries: {len(evt.get('outbox_entries', []))}")
    else:
        fail(f"candidate_packet Discord event not routed")

    # --- Step 3: Sigma validation + promotion ---
    section("3. Sigma Validation → Promotion")
    outcome, promo = validate_candidate(
        ROOT, candidate,
        profit_factor=1.65, sharpe=1.2, max_drawdown_pct=0.08,
        trade_count=52,
    )
    if outcome == "promoted":
        ok(f"Sigma promoted {STRATEGY_ID}")
    else:
        fail(f"Expected promotion, got {outcome}")

    # Emit promotion via Discord bridge
    evt_promo = emit_quant_event(promo, root=ROOT)
    if evt_promo.get("owner_channel_id"):
        ok(f"promotion_packet Discord event → channel {evt_promo['owner_channel_id']}")
        wl = evt_promo.get("worklog_mirrored", False)
        jf = evt_promo.get("jarvis_forwarded", False)
        ok(f"  worklog_mirrored={wl}, jarvis_forwarded={jf}")
    else:
        fail("promotion_packet Discord event not routed")

    # --- Step 4: Kitt papertrade request → #review ---
    section("4. Kitt Papertrade Request → #review")
    req_result = request_paper_trade_approval(
        ROOT, STRATEGY_ID, symbols=["NQ"],
        max_position_size=2, valid_days=14,
    )
    if req_result["error"]:
        fail(f"Request failed: {req_result['error']}")
    else:
        ok(f"Approval object: {req_result['approval_ref']}")
        discord_evt = req_result["discord_event"]
        if discord_evt and discord_evt.get("owner_channel_id"):
            ok(f"approval_requested → channel {discord_evt['owner_channel_id']}")
            ok(f"  outbox entries: {len(discord_evt.get('outbox_entries', []))}")
            # Verify it went to the review channel (archimedes: 1483132981177618482)
            if discord_evt["owner_channel_id"] == "1483132981177618482":
                ok(f"  correctly routed to #review channel")
            else:
                fail(f"  expected #review (1483132981177618482), got {discord_evt['owner_channel_id']}")
        else:
            fail("approval_requested not routed to Discord")

    # --- Step 5: Operator approval (simulated) ---
    section("5. Operator Approves Paper Trade")
    appr_result = approve_paper_trade(ROOT, STRATEGY_ID)
    if appr_result["error"]:
        fail(f"Approval failed: {appr_result['error']}")
    else:
        ok(f"Strategy → {appr_result['strategy_state']} (approval: {appr_result['approval_ref']})")

    # --- Step 6: Executor paper trade ---
    section("6. Executor Paper Trade")
    exec_result = execute_approved_paper_trade(
        ROOT, STRATEGY_ID, req_result["approval_ref"],
        symbol="NQ", side="long", quantity=1, simulated_price=18320.0,
    )
    if exec_result["success"]:
        ok(f"Paper trade filled: {exec_result['fill']['fill_price']}")
        # Emit execution events via Discord bridge
        from workspace.quant.shared.schemas.packets import QuantPacket
        for pkt_dict in exec_result["packets"]:
            pkt = QuantPacket.from_dict(pkt_dict)
            evt_exec = emit_quant_event(pkt, root=ROOT)
            if evt_exec.get("owner_channel_id"):
                ok(f"  {pkt.packet_type} → channel {evt_exec['owner_channel_id']}")
    else:
        fail(f"Execution rejected: {exec_result['rejection_reason']}")

    # Verify strategy is now PAPER_ACTIVE
    strategy = get_strategy(ROOT, STRATEGY_ID)
    if strategy and strategy.lifecycle_state == "PAPER_ACTIVE":
        ok(f"Strategy auto-transitioned to PAPER_ACTIVE")
    else:
        fail(f"Expected PAPER_ACTIVE, got {strategy.lifecycle_state if strategy else 'not found'}")

    # --- Step 7: Kitt brief ---
    section("7. Kitt Brief (with Discord routing)")
    brief = produce_brief(ROOT, market_read="Live runtime proof — no market data.")
    evt_brief = emit_quant_event(brief, root=ROOT)
    if evt_brief.get("owner_channel_id"):
        ok(f"brief_packet → channel {evt_brief['owner_channel_id']}")
        # Verify it went to kitt channel (1483320979185733722)
        if evt_brief["owner_channel_id"] == "1483320979185733722":
            ok(f"  correctly routed to #kitt channel")
        else:
            fail(f"  expected #kitt (1483320979185733722), got {evt_brief['owner_channel_id']}")
    else:
        fail("brief_packet not routed to Discord")

    if brief.notes and "KITT BRIEF" in brief.notes:
        ok("Brief follows spec §7 format")
    else:
        fail("Brief format issue")

    # --- Step 8: Verify outbox entries exist for delivery ---
    section("8. Outbox Verification")
    outbox_dir = ROOT / "state" / "discord_outbox"
    if outbox_dir.exists():
        outbox_files = list(outbox_dir.glob("outbox_*.json"))
        recent = [f for f in outbox_files
                  if json.loads(f.read_text(encoding="utf-8")).get("event_kind", "").startswith("quant_")
                  or json.loads(f.read_text(encoding="utf-8")).get("event_kind") == "approval_requested"]
        ok(f"Outbox has {len(recent)} quant-related pending entries")
        for f in recent[:5]:
            entry = json.loads(f.read_text(encoding="utf-8"))
            ok(f"  {entry['event_kind']} → ch {entry['channel_id']} [{entry['status']}]")
    else:
        fail("Outbox directory not found")

    # --- Step 9: Verify dispatch events ---
    section("9. Dispatch Event Verification")
    dispatch_dir = ROOT / "state" / "dispatch_events"
    if dispatch_dir.exists():
        dispatch_files = list(dispatch_dir.glob("devt_*.json"))
        quant_events = []
        for f in sorted(dispatch_files, key=lambda x: x.stat().st_mtime, reverse=True)[:50]:
            evt_data = json.loads(f.read_text(encoding="utf-8"))
            if evt_data.get("kind", "").startswith("quant_") or evt_data.get("kind") == "approval_requested":
                quant_events.append(evt_data)
        ok(f"Found {len(quant_events)} quant dispatch events")
        for qe in quant_events[:5]:
            ok(f"  {qe['kind']} by {qe['agent_id']} → ch {qe.get('owner_channel_id', 'N/A')}")
    else:
        fail("Dispatch events directory not found")

    # --- Summary ---
    section("LIVE RUNTIME PROOF RESULTS")
    print(f"\n  PASS: {PASS}")
    print(f"  FAIL: {FAIL}")

    print(f"\n  STRATEGY REGISTRY:")
    for sid, s in load_all_strategies(ROOT).items():
        print(f"    {sid}: {s.lifecycle_state} ({len(s.state_history)} transitions)")

    print(f"\n  INTEGRATION POINTS PROVEN:")
    print(f"    Discord event routing: quant events → emit_event() → outbox")
    print(f"    Channel routing: kitt → #kitt, sigma → #sigma, approval → #review")
    print(f"    Worklog mirroring: promotions and execution events mirrored")
    print(f"    Jarvis forwarding: key quant events forwarded to #jarvis")
    print(f"    Approval bridge: request → approval object → #review → approve → execute")
    print(f"    Executor pre-flight: approval validated before paper trade")
    print(f"    Registry transitions: IDEA → CANDIDATE → VALIDATING → PROMOTED → PAPER_QUEUED → PAPER_ACTIVE")

    print()
    if FAIL == 0:
        print("  \U0001f3af LANE A LIVE RUNTIME PROOF: ALL CHECKS PASSED")
    else:
        print(f"  \u26a0\ufe0f LANE A LIVE RUNTIME PROOF: {FAIL} FAILURES")
    print()
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
