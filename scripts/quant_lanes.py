#!/usr/bin/env python3
"""Quant Lanes — Operator CLI.

Commands:
    python3 scripts/quant_lanes.py status                  — show strategy pipeline and lane health
    python3 scripts/quant_lanes.py strategies               — list all strategies with lifecycle state
    python3 scripts/quant_lanes.py strategy <id>            — show detailed strategy state
    python3 scripts/quant_lanes.py approvals                — list all approvals
    python3 scripts/quant_lanes.py latest                   — show all latest packets
    python3 scripts/quant_lanes.py brief                    — produce and display a Kitt brief
    python3 scripts/quant_lanes.py request-paper <id>       — request paper trade approval (posts to #review)
    python3 scripts/quant_lanes.py approve-paper <id>       — approve paper trade for strategy
    python3 scripts/quant_lanes.py execute <id>             — execute paper trade for approved strategy
    python3 scripts/quant_lanes.py live-proof               — run end-to-end live runtime proof
    python3 scripts/quant_lanes.py phase0                   — run Phase 0 vertical slice proof
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.registries.strategy_registry import load_all_strategies, get_strategy
from workspace.quant.shared.registries.approval_registry import load_all_approvals
from workspace.quant.shared.packet_store import get_all_latest, list_lane_packets


def cmd_status(args):
    """Phone-scannable pipeline + action items."""
    strategies = load_all_strategies(ROOT)
    approvals = load_all_approvals(ROOT)
    latest = get_all_latest(ROOT)
    by_state: dict[str, list[str]] = {}
    for sid, s in strategies.items():
        by_state.setdefault(s.lifecycle_state, []).append(sid)

    paper = by_state.get("PAPER_ACTIVE", [])
    live = by_state.get("LIVE_ACTIVE", [])
    print(f"ACTIVE  paper={len(paper)} live={len(live)}")
    for sid in paper:
        print(f"  paper: {sid}")
    for sid in live:
        print(f"  live:  {sid}")

    promoted = by_state.get("PROMOTED", [])
    queued = by_state.get("PAPER_QUEUED", [])
    review = by_state.get("PAPER_REVIEW", [])
    if promoted or queued or review:
        print(f"\nACTION NEEDED")
        for sid in promoted:
            pending = [a for a in approvals if a.strategy_id == sid and not a.revoked]
            if pending:
                print(f"  approve {pending[-1].approval_ref}  (paper trade {sid})")
            else:
                print(f"  request-paper {sid}")
        for sid in queued:
            print(f"  execute {sid}")
        for sid in review:
            print(f"  review paper: {sid}")

    ideas = len(by_state.get("IDEA", []))
    cands = len(by_state.get("CANDIDATE", []))
    val = len(by_state.get("VALIDATING", []))
    rej = len(by_state.get("REJECTED", []))
    if ideas + cands + val + rej > 0:
        print(f"\nDEPTH  {ideas} idea, {cands} candidate, {val} validating, {rej} rejected")

    exec_pkt = None
    for key, pkt in latest.items():
        if pkt.packet_type == "execution_status_packet":
            exec_pkt = pkt
    if exec_pkt:
        fill = f"@ {exec_pkt.fill_price}" if exec_pkt.fill_price else ""
        print(f"\nLAST FILL  {exec_pkt.strategy_id} {exec_pkt.execution_mode} {exec_pkt.execution_status} {fill}")

    active_appr = [a for a in approvals if not a.revoked]
    if active_appr:
        print(f"\nAPPROVALS  {len(active_appr)} active")
        for a in active_appr[-3:]:
            v, r = a.is_valid()
            print(f"  {a.approval_ref} {a.strategy_id} [{'valid' if v else r}]")

    # Delivery health
    from workspace.quant.shared.discord_bridge import check_delivery_health
    health = check_delivery_health()
    problems = [f"{k}={v}" for k, v in health.items() if v != "ok"]
    if problems:
        print(f"\nDELIVERY  {' '.join(f'{k}=ok' for k, v in health.items() if v == 'ok')}")
        for p in problems:
            print(f"  {p}")
    else:
        print(f"\nDELIVERY  all ok")


def cmd_strategies(args):
    """List all strategies."""
    strategies = load_all_strategies(ROOT)
    if not strategies:
        print("No strategies in registry.")
        return
    print(f"{'ID':40s} {'State':16s} {'Transitions':>12s}")
    print("-" * 72)
    for sid, s in strategies.items():
        print(f"{sid:40s} {s.lifecycle_state:16s} {len(s.state_history):>12d}")


def cmd_strategy(args):
    """Show detailed strategy state."""
    s = get_strategy(ROOT, args.strategy_id)
    if s is None:
        print(f"Strategy {args.strategy_id} not found.")
        return
    print(f"Strategy: {s.strategy_id}")
    print(f"State:    {s.lifecycle_state}")
    if s.parent_id:
        print(f"Parent:   {s.parent_id}")
    if s.lineage_note:
        print(f"Lineage:  {s.lineage_note}")
    print(f"\nState History ({len(s.state_history)} entries):")
    for h in s.state_history:
        line = f"  {h.at[:19]} | {h.state:16s} | by {h.by}"
        if h.approval_ref:
            line += f" | approval={h.approval_ref}"
        if h.note:
            line += f" | {h.note}"
        if h.retirement_reason:
            line += f" | reason={h.retirement_reason}"
        print(line)


def cmd_approvals(args):
    """List all approvals."""
    approvals = load_all_approvals(ROOT)
    if not approvals:
        print("No approvals in registry.")
        return
    for a in approvals:
        status = "REVOKED" if a.revoked else "ACTIVE"
        valid, reason = a.is_valid()
        if not valid:
            status = f"INVALID ({reason})"
        print(f"  {a.approval_ref}: {a.approval_type} for {a.strategy_id} [{status}]")
        print(f"    symbols={a.approved_actions.symbols}, mode={a.approved_actions.execution_mode}")
        print(f"    valid {a.approved_actions.valid_from[:19]} → {a.approved_actions.valid_until[:19]}")


def cmd_latest(args):
    """Show all latest packets."""
    latest = get_all_latest(ROOT)
    if not latest:
        print("No latest packets.")
        return
    for key, pkt in sorted(latest.items()):
        print(f"\n{key}:")
        print(f"  ID:       {pkt.packet_id}")
        print(f"  Type:     {pkt.packet_type}")
        print(f"  Lane:     {pkt.lane}")
        print(f"  Created:  {pkt.created_at[:19]}")
        print(f"  Priority: {pkt.priority}")
        print(f"  Thesis:   {pkt.thesis[:120]}")
        if pkt.strategy_id:
            print(f"  Strategy: {pkt.strategy_id}")
        if pkt.confidence is not None:
            print(f"  Conf:     {pkt.confidence}")


def cmd_brief(args):
    """Produce and display a Kitt brief."""
    from workspace.quant.kitt.brief_producer import produce_brief
    brief = produce_brief(ROOT, market_read=args.market or "No live market data available.")
    print(brief.notes or brief.thesis)


def cmd_request_paper(args):
    """Request paper trade approval — posts to #review in Discord."""
    from workspace.quant.shared.approval_bridge import request_paper_trade_approval
    symbols = args.symbols.split(",") if args.symbols else ["NQ"]
    result = request_paper_trade_approval(
        ROOT, args.strategy_id, symbols=symbols,
        max_position_size=args.max_pos,
        valid_days=args.valid_days,
    )
    if result["error"]:
        print(f"ERROR: {result['error']}")
        return
    print(f"Approval requested: {result['approval_ref']}")
    print(f"Strategy: {result['strategy_id']}")
    if result["discord_event"]:
        evt = result["discord_event"]
        ch = evt.get("owner_channel_id", "unknown")
        print(f"Discord event: {evt.get('event_id', 'N/A')} -> channel {ch}")
        if evt.get("outbox_entries"):
            print(f"Outbox entries: {len(evt['outbox_entries'])} (pending delivery)")


def cmd_approve_paper(args):
    """Approve paper trade for a strategy."""
    from workspace.quant.shared.approval_bridge import approve_paper_trade
    result = approve_paper_trade(ROOT, args.strategy_id, approval_ref=args.approval_ref)
    if result["error"]:
        print(f"ERROR: {result['error']}")
        return
    print(f"Approved: {result['approval_ref']}")
    print(f"Strategy state: {result['strategy_state']}")


def cmd_execute(args):
    """Execute paper trade for an approved strategy."""
    from workspace.quant.shared.approval_bridge import execute_approved_paper_trade
    from workspace.quant.shared.registries.approval_registry import load_all_approvals
    from workspace.quant.shared.discord_bridge import emit_quant_event
    from workspace.quant.shared.schemas.packets import QuantPacket

    # Find approval
    approval_ref = args.approval_ref
    if not approval_ref:
        approvals = [a for a in load_all_approvals(ROOT)
                     if a.strategy_id == args.strategy_id and not a.revoked]
        if not approvals:
            print(f"ERROR: No approval found for {args.strategy_id}")
            return
        approval_ref = approvals[-1].approval_ref

    result = execute_approved_paper_trade(
        ROOT, args.strategy_id, approval_ref,
        symbol=args.symbol, side=args.side,
        quantity=args.quantity, simulated_price=args.price,
    )

    if result["success"]:
        print(f"Paper trade executed successfully")
        print(f"  Fill: {result['fill']['fill_price']} (slippage: {result['fill']['slippage']})")
        # Emit Discord event for the execution status
        for pkt_dict in result["packets"]:
            pkt = QuantPacket.from_dict(pkt_dict)
            emit_quant_event(pkt, root=ROOT)
    else:
        print(f"Execution rejected: {result['rejection_reason']}")
        for pkt_dict in result["packets"]:
            pkt = QuantPacket.from_dict(pkt_dict)
            emit_quant_event(pkt, root=ROOT)


def cmd_lane_b_cycle(args):
    """Run one Lane B cycle (Hermes → Atlas → Fish → TradeFloor → Brief)."""
    from workspace.quant.run_lane_b_cycle import run_cycle
    s = run_cycle(ROOT, verbose=args.verbose)
    parts = []
    if s["hermes"]["emitted"]:
        parts.append(f"hermes={s['hermes']['emitted']}")
    if s["atlas"]["generated"]:
        parts.append(f"atlas={s['atlas']['generated']}")
    if s["fish"]["emitted"]:
        parts.append(f"fish={s['fish']['emitted']}")
    if s["tradefloor"]["ran"]:
        parts.append(f"tradefloor=tier{s['tradefloor']['tier']}")
    elif s["tradefloor"]["cadence_refused"]:
        parts.append("tradefloor=cadence_wait")
    if s["brief"]:
        parts.append("brief=ok")
    print(f"Cycle: {' '.join(parts) or 'nothing produced'}")
    if s["errors"]:
        for e in s["errors"]:
            print(f"  ERROR: {e}")


def cmd_tradefloor(args):
    """Run TradeFloor synthesis (respects 6h cadence unless --override)."""
    from workspace.quant.tradefloor.synthesis_lane import synthesize, check_cadence, CadenceRefused
    can_run, remaining = check_cadence(ROOT)
    if not can_run and not args.override:
        print(f"Cadence: {remaining:.0f}s remaining. Use --override 'reason' to bypass.")
        return
    try:
        pkt = synthesize(ROOT, override_reason=args.override)
        tier = pkt.agreement_tier
        print(f"TradeFloor tier {tier}: {pkt.thesis[:120]}")
    except CadenceRefused as e:
        print(f"Cadence refused: {e}")


def cmd_atlas_batch(args):
    """Run Atlas candidate batch."""
    from workspace.quant.atlas.exploration_lane import generate_candidate_batch
    import hashlib
    from datetime import datetime, timezone
    bid = hashlib.sha256(datetime.now(timezone.utc).isoformat().encode()).hexdigest()[:8]
    stubs = [{"strategy_id": f"atlas-cli-{bid}", "thesis": args.thesis or "NQ mean-reversion (CLI)"}]
    batch_pkt, candidates, info = generate_candidate_batch(ROOT, stubs)
    print(f"Atlas: {info.get('generated', 0)} generated, host={info.get('host', '?')}")


def cmd_fish_batch(args):
    """Run Fish scenario batch."""
    from workspace.quant.fish.scenario_lane import run_scenario_batch
    stubs = [{"thesis": args.thesis or "NQ consolidation scenario (CLI)"}]
    emitted, info = run_scenario_batch(ROOT, stubs)
    print(f"Fish: {len(emitted)} scenarios, host={info.get('host', '?')}")


def cmd_hermes_batch(args):
    """Run Hermes research batch."""
    from workspace.quant.hermes.research_lane import run_research_batch
    stubs = [{"thesis": args.thesis or "NQ volume analysis (CLI)", "source": f"cli-{args.source or 'manual'}"}]
    emitted, info = run_research_batch(ROOT, stubs)
    print(f"Hermes: {len(emitted)} emitted, {info.get('deduped', 0)} deduped")


def cmd_live_proof(args):
    """Run end-to-end live runtime proof."""
    import subprocess
    result = subprocess.run(
        [sys.executable, str(ROOT / "workspace" / "quant" / "live_runtime_proof.py")],
        cwd=str(ROOT),
    )
    sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="Quant Lanes — Operator CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show pipeline status")
    sub.add_parser("strategies", help="List strategies")

    p_strat = sub.add_parser("strategy", help="Show strategy detail")
    p_strat.add_argument("strategy_id")

    sub.add_parser("approvals", help="List approvals")
    sub.add_parser("latest", help="Show latest packets")

    p_brief = sub.add_parser("brief", help="Produce Kitt brief")
    p_brief.add_argument("--market", help="Market read text", default=None)

    p_req = sub.add_parser("request-paper", help="Request paper trade approval")
    p_req.add_argument("strategy_id")
    p_req.add_argument("--symbols", default="NQ", help="Comma-separated symbols")
    p_req.add_argument("--max-pos", type=int, default=2)
    p_req.add_argument("--valid-days", type=int, default=14)

    p_appr = sub.add_parser("approve-paper", help="Approve paper trade")
    p_appr.add_argument("strategy_id")
    p_appr.add_argument("--approval-ref", default=None)

    p_exec = sub.add_parser("execute", help="Execute paper trade")
    p_exec.add_argument("strategy_id")
    p_exec.add_argument("--approval-ref", default=None)
    p_exec.add_argument("--symbol", default="NQ")
    p_exec.add_argument("--side", default="long")
    p_exec.add_argument("--quantity", type=int, default=1)
    p_exec.add_argument("--price", type=float, default=18250.0)

    s_lbc = sub.add_parser("lane-b-cycle", help="Run one Lane B cycle")
    s_lbc.add_argument("-v", "--verbose", action="store_true")

    s_tf = sub.add_parser("tradefloor", help="Run TradeFloor synthesis")
    s_tf.add_argument("--override", default=None, help="Override cadence with reason")

    s_ab = sub.add_parser("atlas-batch", help="Run Atlas candidate batch")
    s_ab.add_argument("--thesis", default=None)

    s_fb = sub.add_parser("fish-batch", help="Run Fish scenario batch")
    s_fb.add_argument("--thesis", default=None)

    s_hb = sub.add_parser("hermes-batch", help="Run Hermes research batch")
    s_hb.add_argument("--thesis", default=None)
    s_hb.add_argument("--source", default=None)

    sub.add_parser("live-proof", help="Run live runtime proof")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    commands = {
        "status": cmd_status,
        "strategies": cmd_strategies,
        "strategy": cmd_strategy,
        "approvals": cmd_approvals,
        "latest": cmd_latest,
        "brief": cmd_brief,
        "request-paper": cmd_request_paper,
        "approve-paper": cmd_approve_paper,
        "execute": cmd_execute,
        "lane-b-cycle": cmd_lane_b_cycle,
        "tradefloor": cmd_tradefloor,
        "atlas-batch": cmd_atlas_batch,
        "fish-batch": cmd_fish_batch,
        "hermes-batch": cmd_hermes_batch,
        "live-proof": cmd_live_proof,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
