#!/usr/bin/env python3
"""Quant Lanes — Operator CLI.

Commands:
    python3 scripts/quant_lanes.py status          — show strategy pipeline and lane health
    python3 scripts/quant_lanes.py strategies       — list all strategies with lifecycle state
    python3 scripts/quant_lanes.py strategy <id>    — show detailed strategy state
    python3 scripts/quant_lanes.py approvals        — list all approvals
    python3 scripts/quant_lanes.py latest           — show all latest packets
    python3 scripts/quant_lanes.py brief            — produce and display a Kitt brief
    python3 scripts/quant_lanes.py phase0           — run Phase 0 vertical slice proof
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
    """Show strategy pipeline overview."""
    strategies = load_all_strategies(ROOT)
    approvals = load_all_approvals(ROOT)
    latest = get_all_latest(ROOT)

    by_state: dict[str, list[str]] = {}
    for sid, s in strategies.items():
        by_state.setdefault(s.lifecycle_state, []).append(sid)

    print("QUANT LANES STATUS")
    print("=" * 50)
    print(f"\nStrategies: {len(strategies)} total")
    for state in ["IDEA", "CANDIDATE", "VALIDATING", "PROMOTED",
                   "PAPER_QUEUED", "PAPER_ACTIVE", "PAPER_REVIEW",
                   "LIVE_QUEUED", "LIVE_ACTIVE", "LIVE_REVIEW",
                   "REJECTED", "PAPER_KILLED", "LIVE_KILLED", "RETIRED", "ITERATE"]:
        ids = by_state.get(state, [])
        if ids:
            print(f"  {state:16s}: {len(ids)} ({', '.join(ids[:5])})")

    print(f"\nApprovals: {len(approvals)} total")
    active = [a for a in approvals if not a.revoked]
    revoked = [a for a in approvals if a.revoked]
    print(f"  Active: {len(active)}, Revoked: {len(revoked)}")

    print(f"\nLatest packets: {len(latest)}")
    for key, pkt in sorted(latest.items()):
        print(f"  {key}: {pkt.thesis[:80]}")


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


def cmd_phase0(args):
    """Run Phase 0 vertical slice proof."""
    import subprocess
    result = subprocess.run(
        [sys.executable, str(ROOT / "workspace" / "quant" / "phase0_vertical_slice.py")],
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

    sub.add_parser("phase0", help="Run Phase 0 proof")

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
        "phase0": cmd_phase0,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
