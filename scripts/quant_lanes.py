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
    python3 scripts/quant_lanes.py doctor                    — operator health check (phone-readable)
    python3 scripts/quant_lanes.py acceptance                — non-destructive acceptance test
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


# ---------------------------------------------------------------------------
# Proof/smoke artifact filter — keep operator surfaces clean
# ---------------------------------------------------------------------------

_PROOF_MARKERS = ("proof", "smoke", "phase0", "test-", "la-001", "bad-001")


def _is_proof_artifact(strategy_id: str) -> bool:
    """Return True if strategy_id looks like a proof/smoke run, not real work."""
    sid = strategy_id.lower()
    return any(m in sid for m in _PROOF_MARKERS)


# Human-readable stage descriptions for operator surfaces
_STAGE_LABELS = {
    "IDEA": ("discovery", "idea generated, not yet a candidate"),
    "CANDIDATE": ("discovery", "candidate awaiting validation"),
    "VALIDATING": ("validation", "Sigma is checking backtest gates"),
    "REJECTED": ("terminal", "failed validation — will not proceed"),
    "PROMOTED": ("pre-paper", "passed validation, needs paper-trade request"),
    "PAPER_QUEUED": ("paper", "paper-trade approved, awaiting execution"),
    "PAPER_ACTIVE": ("paper", "paper-trading — accumulating proof"),
    "PAPER_REVIEW": ("review", "paper proof complete — awaiting operator review"),
    "ITERATE": ("iterate", "review said rerun with changes — back to Atlas"),
    "PAPER_KILLED": ("terminal", "review rejected — permanently closed"),
    "LIVE_QUEUED": ("pre-live", "review approved for live — needs live approval"),
    "LIVE_ACTIVE": ("live", "live trading"),
    "LIVE_REVIEW": ("live-review", "live performance under review"),
    "LIVE_KILLED": ("terminal", "live terminated"),
    "RETIRED": ("terminal", "retired by operator"),
}

_REVIEW_OUTCOME_LABELS = {
    "advance_to_live": "approve_live_candidate — ready for live approval",
    "iterate": "rerun_with_changes — back to Atlas with guidance",
    "kill": "reject — permanently closed",
}


def _why_not_live(state: str, strategy_id: str, approvals) -> str:
    """Return a one-line explanation of why this strategy is not live."""
    if state == "PAPER_QUEUED":
        return "paper trades not yet placed"
    if state == "PAPER_ACTIVE":
        return "still accumulating paper proof (trades, time, stats)"
    if state == "PAPER_REVIEW":
        return "awaiting operator review decision"
    if state == "ITERATE":
        return "review said rerun with changes — back to Atlas"
    if state in ("PAPER_KILLED", "REJECTED"):
        return "permanently closed"
    if state == "LIVE_QUEUED":
        has_live = any(a.strategy_id == strategy_id and not a.revoked
                       and a.approved_actions.execution_mode == "live"
                       for a in approvals)
        if has_live:
            return "approved for live — execution not yet triggered"
        return "approved for live — needs live_trade approval"
    if state == "PROMOTED":
        return "needs paper-trade approval first"
    if state in ("LIVE_ACTIVE", "LIVE_REVIEW"):
        return ""  # Already live
    return ""


def cmd_status(args):
    """Phone-scannable pipeline + action items + live-eligibility."""
    strategies = load_all_strategies(ROOT)
    approvals = load_all_approvals(ROOT)
    latest = get_all_latest(ROOT)
    by_state: dict[str, list[str]] = {}
    for sid, s in strategies.items():
        if _is_proof_artifact(sid):
            continue
        by_state.setdefault(s.lifecycle_state, []).append(sid)

    # Active positions
    paper = by_state.get("PAPER_ACTIVE", [])
    live = by_state.get("LIVE_ACTIVE", [])
    print(f"ACTIVE  paper={len(paper)} live={len(live)}")
    for sid in paper:
        print(f"  paper: {sid}  (accumulating proof — not live-eligible)")
    for sid in live:
        print(f"  live:  {sid}")

    # Action needed — expanded to cover full lifecycle
    actions = []
    for sid in by_state.get("PROMOTED", []):
        pending = [a for a in approvals if a.strategy_id == sid and not a.revoked]
        if pending:
            actions.append(f"  approve {pending[-1].approval_ref}  (paper trade {sid})")
        else:
            actions.append(f"  request-paper {sid}  (passed validation, needs paper request)")
    for sid in by_state.get("PAPER_QUEUED", []):
        actions.append(f"  execute {sid}  (paper-trade approved, ready to place)")
    for sid in by_state.get("PAPER_REVIEW", []):
        actions.append(f"  review: {sid}  (paper proof ready — decide: approve_live / reject / continue / rerun)")
    for sid in by_state.get("LIVE_QUEUED", []):
        has_live_appr = any(a.strategy_id == sid and not a.revoked
                            and a.approved_actions.execution_mode == "live"
                            for a in approvals)
        if has_live_appr:
            actions.append(f"  execute-live {sid}  (live-approved, ready to go)")
        else:
            actions.append(f"  request-live {sid}  (review approved — needs live_trade approval)")
    if actions:
        print(f"\nACTION NEEDED")
        for a in actions:
            print(a)

    # Pipeline depth
    ideas = len(by_state.get("IDEA", []))
    cands = len(by_state.get("CANDIDATE", []))
    val = len(by_state.get("VALIDATING", []))
    rej = len(by_state.get("REJECTED", []))
    iterate = len(by_state.get("ITERATE", []))
    killed = len(by_state.get("PAPER_KILLED", []))
    depth_parts = []
    if ideas: depth_parts.append(f"{ideas} idea")
    if cands: depth_parts.append(f"{cands} candidate")
    if val: depth_parts.append(f"{val} validating")
    if iterate: depth_parts.append(f"{iterate} iterating")
    if rej: depth_parts.append(f"{rej} rejected")
    if killed: depth_parts.append(f"{killed} paper-killed")
    if depth_parts:
        print(f"\nPIPELINE  {', '.join(depth_parts)}")

    # Not-live-eligible strategies (explain why)
    blocked = []
    for state in ("PAPER_ACTIVE", "PAPER_REVIEW", "PAPER_QUEUED", "PROMOTED", "LIVE_QUEUED", "ITERATE"):
        for sid in by_state.get(state, []):
            reason = _why_not_live(state, sid, approvals)
            if reason:
                blocked.append((sid, state, reason))
    if blocked:
        print(f"\nLIVE BLOCKED")
        for sid, state, reason in blocked:
            print(f"  {sid:30s} {state:16s} {reason}")

    # Last fill
    exec_pkt = None
    for key, pkt in latest.items():
        if pkt.packet_type == "execution_status_packet":
            if not (pkt.strategy_id and _is_proof_artifact(pkt.strategy_id)):
                exec_pkt = pkt
    if exec_pkt:
        fill = f"@ {exec_pkt.fill_price}" if exec_pkt.fill_price else ""
        print(f"\nLAST FILL  {exec_pkt.strategy_id} {exec_pkt.execution_mode} "
              f"{exec_pkt.execution_status} {fill}")

    # Approvals
    active_appr = [a for a in approvals if not a.revoked
                   and not _is_proof_artifact(a.strategy_id)]
    if active_appr:
        print(f"\nAPPROVALS  {len(active_appr)} active")
        for a in active_appr[-5:]:
            v, r = a.is_valid()
            mode = a.approved_actions.execution_mode
            print(f"  {a.approval_ref} {a.strategy_id} [{mode}] "
                  f"{'valid' if v else r}")

    # Delivery health
    from workspace.quant.shared.discord_bridge import check_delivery_health
    health = check_delivery_health()
    problems = [f"{k}={v}" for k, v in health.items() if v != "ok"]
    if problems:
        print(f"\nDELIVERY  issues: {', '.join(problems)}")
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
    """Show detailed strategy state with stage explanation and live-eligibility."""
    s = get_strategy(ROOT, args.strategy_id)
    if s is None:
        print(f"Strategy {args.strategy_id} not found.")
        return

    phase, explanation = _STAGE_LABELS.get(s.lifecycle_state, ("?", "unknown state"))
    approvals = load_all_approvals(ROOT)

    print(f"Strategy:  {s.strategy_id}")
    print(f"State:     {s.lifecycle_state}  ({phase})")
    print(f"Stage:     {explanation}")

    reason = _why_not_live(s.lifecycle_state, s.strategy_id, approvals)
    if reason:
        print(f"Not live:  {reason}")
    elif s.lifecycle_state in ("LIVE_ACTIVE", "LIVE_REVIEW"):
        print(f"Live:      yes")

    if s.parent_id:
        print(f"Parent:    {s.parent_id}")
    if s.lineage_note:
        print(f"Lineage:   {s.lineage_note}")

    # Show relevant approvals
    strat_approvals = [a for a in approvals if a.strategy_id == s.strategy_id and not a.revoked]
    if strat_approvals:
        print(f"\nApprovals:")
        for a in strat_approvals:
            v, r = a.is_valid()
            mode = a.approved_actions.execution_mode
            print(f"  {a.approval_ref} [{mode}] {'valid' if v else r}")

    # Show review outcome if in PAPER_REVIEW or post-review states
    if s.lifecycle_state in ("PAPER_REVIEW", "ITERATE", "PAPER_KILLED", "LIVE_QUEUED"):
        from workspace.quant.shared.packet_store import list_lane_packets
        reviews = list_lane_packets(ROOT, "sigma", "paper_review_packet")
        for r in reviews:
            if r.strategy_id == s.strategy_id:
                outcome = r.outcome or "?"
                label = _REVIEW_OUTCOME_LABELS.get(outcome, outcome)
                print(f"\nReview:    {label}")
                if r.outcome_reasoning:
                    print(f"  Reason:  {r.outcome_reasoning[:100]}")
                if r.iteration_guidance:
                    print(f"  Guidance: {r.iteration_guidance[:100]}")

    print(f"\nHistory ({len(s.state_history)} transitions):")
    for h in s.state_history:
        line = f"  {h.at[:19]} | {h.state:16s} | by {h.by}"
        if h.approval_ref:
            line += f" | approval={h.approval_ref}"
        if h.note:
            line += f" | {h.note}"
        if h.retirement_reason:
            line += f" | reason={h.retirement_reason}"
        if h.iteration_guidance:
            line += f" | guidance={h.iteration_guidance[:50]}"
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
    market_read = args.market
    if not market_read:
        try:
            from workspace.quant.shared.market_context import format_full_market_read
            market_read = format_full_market_read(ROOT)
        except Exception:
            market_read = "No market data available."
    brief = produce_brief(ROOT, market_read=market_read)
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


# ---------------------------------------------------------------------------
# doctor — operator health surface
# ---------------------------------------------------------------------------

def cmd_doctor(args):
    """Concise, phone-readable health check of load-bearing quant infrastructure."""
    import subprocess
    from workspace.quant.shared.discord_bridge import check_delivery_health
    from workspace.quant.shared.restart import check_latest_coherence
    from workspace.quant.shared.governor import load_governor_state

    checks: list[tuple[str, str, str]] = []  # (name, status, detail)

    # 1. Lane-B timer
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", "quant-lane-b-cycle.timer"],
            capture_output=True, text=True, timeout=5,
        )
        active = r.stdout.strip() == "active"
        checks.append(("lane-b timer", "PASS" if active else "FAIL", r.stdout.strip()))
    except Exception as e:
        checks.append(("lane-b timer", "FAIL", str(e)))

    # 2. Review poller
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", "openclaw-review-poller.timer"],
            capture_output=True, text=True, timeout=5,
        )
        active = r.stdout.strip() == "active"
        checks.append(("review poller", "PASS" if active else "WARN", r.stdout.strip()))
    except Exception as e:
        checks.append(("review poller", "WARN", str(e)))

    # 3. Webhook/delivery health
    dh = check_delivery_health()
    missing = [k for k, v in dh.items() if v != "ok"]
    if missing:
        checks.append(("delivery", "FAIL", f"missing: {', '.join(missing)}"))
    else:
        checks.append(("delivery", "PASS", f"{len(dh)} channels ok"))

    # 4. Latest state coherence
    coherent, issues = check_latest_coherence(ROOT)
    if coherent:
        checks.append(("latest state", "PASS", "coherent"))
    else:
        checks.append(("latest state", "FAIL", "; ".join(issues[:3])))

    # 5. Governor state readable
    try:
        gov = load_governor_state(ROOT)
        paused = [k for k, v in gov.items() if v.get("paused")]
        if paused:
            checks.append(("governor", "WARN", f"paused: {', '.join(paused)}"))
        else:
            checks.append(("governor", "PASS", f"{len(gov)} lanes configured"))
    except Exception as e:
        checks.append(("governor", "FAIL", str(e)))

    # 6. Kill switch
    ks_path = ROOT / "workspace" / "quant" / "shared" / "config" / "kill_switch.json"
    try:
        if ks_path.exists():
            import json as _json
            ks = _json.loads(ks_path.read_text(encoding="utf-8"))
            if ks.get("engaged"):
                checks.append(("kill switch", "FAIL", f"ENGAGED by {ks.get('engaged_by', '?')}"))
            else:
                checks.append(("kill switch", "PASS", "disengaged"))
        else:
            checks.append(("kill switch", "PASS", "not present (default off)"))
    except Exception as e:
        checks.append(("kill switch", "WARN", str(e)))

    # Print results
    worst = "OK"
    reasons = []
    for name, status, detail in checks:
        tag = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL"}[status]
        print(f"  {tag:4s}  {name:16s}  {detail}")
        if status == "FAIL":
            worst = "FAIL"
            reasons.append(name)
        elif status == "WARN" and worst != "FAIL":
            worst = "WARN"
            reasons.append(name)

    summary = f"OVERALL  {worst}"
    if reasons:
        summary += f"  {', '.join(reasons)}"
    print(f"\n{summary}")


# ---------------------------------------------------------------------------
# acceptance — non-destructive verification pass
# ---------------------------------------------------------------------------

def cmd_acceptance(args):
    """Non-destructive acceptance test of quant system readiness."""
    results: list[tuple[str, bool, str]] = []  # (name, passed, detail)

    # 1. Delivery health readable
    try:
        from workspace.quant.shared.discord_bridge import check_delivery_health
        dh = check_delivery_health()
        ok = all(v == "ok" for v in dh.values())
        results.append(("delivery health", ok, f"{sum(v == 'ok' for v in dh.values())}/{len(dh)} ok"))
    except Exception as e:
        results.append(("delivery health", False, str(e)))

    # 2. lane-b-cycle importable and callable
    try:
        from workspace.quant.run_lane_b_cycle import run_cycle  # noqa: F401
        results.append(("lane-b-cycle import", True, "module loads"))
    except Exception as e:
        results.append(("lane-b-cycle import", False, str(e)))

    # 3. Review approval path callable (dry import)
    try:
        from workspace.quant.shared.approval_bridge import (
            request_paper_trade_approval, approve_paper_trade,  # noqa: F401
        )
        results.append(("approval path", True, "imports ok"))
    except Exception as e:
        results.append(("approval path", False, str(e)))

    # 4. Brief generation works
    try:
        from workspace.quant.kitt.brief_producer import produce_brief
        brief = produce_brief(ROOT, market_read="Acceptance test — no market data.")
        has_sections = all(s in (brief.notes or "") for s in ["PIPELINE", "HEALTH", "OPERATOR ACTION"])
        results.append(("brief generation", has_sections, f"{len(brief.notes or '')} chars"))
    except Exception as e:
        results.append(("brief generation", False, str(e)))

    # 5. Registries readable
    try:
        strats = load_all_strategies(ROOT)
        appr = load_all_approvals(ROOT)
        results.append(("registries", True, f"{len(strats)} strategies, {len(appr)} approvals"))
    except Exception as e:
        results.append(("registries", False, str(e)))

    # 6. Latest state coherent
    try:
        from workspace.quant.shared.restart import check_latest_coherence
        coherent, issues = check_latest_coherence(ROOT)
        results.append(("latest coherence", coherent, "; ".join(issues[:2]) if issues else "ok"))
    except Exception as e:
        results.append(("latest coherence", False, str(e)))

    # 7. Outbox directory exists
    outbox = ROOT / "state" / "discord_outbox"
    results.append(("outbox dir", outbox.is_dir(), str(outbox)))

    # Print
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    for name, ok, detail in results:
        tag = "PASS" if ok else "FAIL"
        print(f"  {tag}  {name:24s}  {detail}")

    print(f"\nACCEPTANCE  {passed}/{total} pass")


# ---------------------------------------------------------------------------
# Pulse stub handlers — real logic lives in Pulse worker; these prevent CLI crash
# ---------------------------------------------------------------------------

def cmd_pulse_status(args):
    """Pulse lane status — phone-readable, full lifecycle visibility."""
    from workspace.quant.shared.packet_store import list_lane_packets
    from workspace.quant.shared.discord_bridge import check_delivery_health
    from workspace.quant.pulse.alert_lane import list_all_proposals

    alerts = list_lane_packets(ROOT, "pulse", "pulse_alert_packet")
    clusters = list_lane_packets(ROOT, "pulse", "pulse_cluster_packet")
    outcomes = list_lane_packets(ROOT, "pulse", "pulse_outcome_packet")

    # Use authoritative proposal state files, not packet notes
    all_proposals = list_all_proposals(ROOT)
    pending = [p for p in all_proposals if p["status"] == "pending"]
    approved = [p for p in all_proposals if p["status"] == "approved"]
    rejected = [p for p in all_proposals if p["status"] == "rejected"]

    dh = check_delivery_health()

    print("PULSE STATUS")
    print("━" * 40)
    print(f"  Alerts:     {len(alerts)}")
    print(f"  Clusters:   {len(clusters)}")
    print(f"  Outcomes:   {len(outcomes)}")
    if outcomes:
        hits = sum(1 for o in outcomes if "hit=true" in (o.notes or ""))
        print(f"  Hit rate:   {hits}/{len(outcomes)}")
    print(f"  Delivery:   {dh.get('pulse', '?')}")
    print(f"  Proposals:  {len(all_proposals)} total "
          f"({len(pending)} pending, {len(approved)} approved, {len(rejected)} rejected)")

    if pending:
        print("\n  PENDING REVIEW:")
        for p in pending:
            print(f"    {p['approval_ref']}  → {p['target']}")
            print(f"      {p['thesis'][:70]}")
            print(f"      #review: approve {p['approval_ref']}")
    if approved:
        print("\n  APPROVED (released):")
        for p in approved[-3:]:
            ds = p.get("downstream_packet_id") or "?"
            print(f"    {p['approval_ref']}  → {p['target']}  downstream={ds[:40]}")
            if p.get("approved_at"):
                print(f"      approved at {p['approved_at'][:19]}")
    if rejected:
        print("\n  REJECTED:")
        for p in rejected[-3:]:
            print(f"    {p['approval_ref']}  → {p['target']}")
            if p.get("rejected_at"):
                print(f"      rejected at {p['rejected_at'][:19]}")

    if alerts:
        print("\n  Recent alerts:")
        for a in alerts[-3:]:
            print(f"    {a.created_at[:19]}  {a.thesis[:60]}")


def cmd_pulse_ingest(args):
    """Ingest a Pulse alert."""
    from workspace.quant.pulse.alert_lane import ingest_alert
    pkt, parsed = ingest_alert(
        ROOT, text=args.text, level=args.level,
        direction=args.direction, symbol=args.symbol, source="cli",
    )
    print(f"  Ingested: {pkt.packet_id}")
    print(f"  Thesis:   {pkt.thesis}")
    if parsed["level"] is not None:
        print(f"  Level:    {parsed['level']}")
    if parsed["tags"]:
        print(f"  Tags:     {', '.join(parsed['tags'])}")


def cmd_pulse_proposals(args):
    """Show Pulse proposals — full lifecycle audit view."""
    from workspace.quant.pulse.alert_lane import list_all_proposals

    all_proposals = list_all_proposals(ROOT)
    if not all_proposals:
        print("No Pulse proposals.")
        return

    pending = [p for p in all_proposals if p["status"] == "pending"]
    approved = [p for p in all_proposals if p["status"] == "approved"]
    rejected = [p for p in all_proposals if p["status"] == "rejected"]

    print(f"PULSE PROPOSALS  {len(all_proposals)} total: "
          f"{len(pending)} pending, {len(approved)} approved, {len(rejected)} rejected")
    print("━" * 60)

    for p in all_proposals:
        status_tag = {
            "pending": "PENDING",
            "approved": "APPROVED",
            "rejected": "REJECTED",
        }.get(p["status"], p["status"])

        print(f"\n  [{status_tag}]  {p['approval_ref']}")
        print(f"    Target:   {p['target']}")
        print(f"    Thesis:   {p['thesis'][:70]}")
        print(f"    Created:  {(p.get('created_at') or '?')[:19]}")

        if p["status"] == "pending":
            print(f"    Action:   approve {p['approval_ref']}  (in #review)")
        elif p["status"] == "approved":
            print(f"    Approved: {(p.get('approved_at') or '?')[:19]}")
            ds = p.get("downstream_packet_id")
            if ds:
                print(f"    Released: {ds}")
        elif p["status"] == "rejected":
            print(f"    Rejected: {(p.get('rejected_at') or '?')[:19]}")


def cmd_pulse_approve(args):
    """Inspect a Pulse proposal by approval_ref. Approval/rejection goes through #review only."""
    from workspace.quant.pulse.alert_lane import get_proposal_by_ref
    state = get_proposal_by_ref(ROOT, args.proposal_id)
    if state is None:
        print(f"  Proposal {args.proposal_id} not found.")
        return

    status_tag = state["status"].upper()
    print(f"  PULSE PROPOSAL  [{status_tag}]")
    print(f"  ────────────────────────────────────────")
    print(f"  Ref:       {state['approval_ref']}")
    print(f"  Target:    {state['target']}")
    print(f"  Symbol:    {state.get('symbol', '?')}")
    print(f"  Thesis:    {state['thesis'][:80]}")
    print(f"  Conf:      {state.get('confidence', '?')}")
    print(f"  Created:   {(state.get('created_at') or '?')[:19]}")
    print(f"  Packet:    {state.get('proposal_packet_id', '?')}")

    if state["status"] == "pending":
        print(f"\n  Governance: approval/rejection must go through #review")
        print(f"    approve {state['approval_ref']}")
        print(f"    reject {state['approval_ref']}")
    elif state["status"] == "approved":
        print(f"\n  Approved:   {(state.get('approved_at') or '?')[:19]}")
        ds = state.get("downstream_packet_id")
        if ds:
            print(f"  Downstream: {ds}")
        else:
            print(f"  Downstream: (not yet released)")
    elif state["status"] == "rejected":
        print(f"\n  Rejected:   {(state.get('rejected_at') or '?')[:19]}")
        print(f"  Downstream: none (blocked by review)")


def cmd_pulse_health(args):
    """Pulse health summary — phone-readable, includes governance audit."""
    from workspace.quant.shared.packet_store import list_lane_packets
    from workspace.quant.shared.discord_bridge import check_delivery_health
    from workspace.quant.pulse.alert_lane import list_all_proposals

    alerts = list_lane_packets(ROOT, "pulse", "pulse_alert_packet")
    outcomes = list_lane_packets(ROOT, "pulse", "pulse_outcome_packet")

    all_proposals = list_all_proposals(ROOT)
    pending = [p for p in all_proposals if p["status"] == "pending"]
    approved = [p for p in all_proposals if p["status"] == "approved"]
    rejected = [p for p in all_proposals if p["status"] == "rejected"]

    dh = check_delivery_health()

    print("PULSE HEALTH")
    print("━" * 40)
    print(f"  Alerts:      {len(alerts)}")
    print(f"  Outcomes:    {len(outcomes)}")
    if outcomes:
        hits = sum(1 for o in outcomes if "hit=true" in (o.notes or ""))
        total = len(outcomes)
        print(f"  Hit rate:    {hits}/{total} ({hits/total:.0%})")
    print(f"  Delivery:    {dh.get('pulse', '?')}")

    noise = len(alerts) - len(set(ref for o in outcomes for ref in o.evidence_refs))
    if noise > 0:
        print(f"  Noise:       {noise} alerts without outcomes")

    print(f"\n  GOVERNANCE")
    print(f"  Proposals:   {len(all_proposals)} total")
    print(f"    Pending:   {len(pending)}")
    print(f"    Approved:  {len(approved)}")
    print(f"    Rejected:  {len(rejected)}")
    released = [p for p in approved if p.get("downstream_packet_id")]
    print(f"    Released:  {len(released)} downstream packets")

    if pending:
        print(f"\n  ACTION: {len(pending)} proposal(s) await #review")


# ---------------------------------------------------------------------------
# Cold-start proof
# ---------------------------------------------------------------------------

def cmd_cold_start_proof(args):
    """Run deterministic cold-start/bootstrap proof."""
    from workspace.quant.cold_start_proof import main as proof_main
    sys.exit(proof_main())


# ---------------------------------------------------------------------------
# Bootstrap commands
# ---------------------------------------------------------------------------

def cmd_bootstrap_hermes(args):
    """Bootstrap Hermes from its configured watchlist."""
    from workspace.quant.bootstrap import bootstrap_hermes
    result = bootstrap_hermes(ROOT)
    if result.get("already_bootstrapped"):
        print("Hermes: already bootstrapped (dedup caught all sources)")
    elif result.get("skipped_reason"):
        print(f"Hermes: skipped ({result['skipped_reason']})")
    else:
        print(f"Hermes: {result['emitted']} research packets emitted, "
              f"{result['deduped']} deduped, {result['watchlist_entries']} watchlist entries")


def cmd_bootstrap_fish(args):
    """Bootstrap Fish from its seed config."""
    from workspace.quant.bootstrap import bootstrap_fish
    result = bootstrap_fish(ROOT)
    if result.get("already_bootstrapped"):
        print("Fish: already bootstrapped (scenarios/regimes exist)")
    elif result.get("skipped_reason"):
        print(f"Fish: skipped ({result['skipped_reason']})")
    else:
        print(f"Fish: {result['regimes_emitted']} regimes, "
              f"{result['scenarios_emitted']} scenarios, "
              f"{result['risk_maps_emitted']} risk maps emitted")
        cal = result.get("calibration_state", {})
        print(f"  Calibration: {cal.get('total_calibrations', 0)} calibrations, "
              f"trend={cal.get('trend', 'N/A')}")


def cmd_bootstrap_atlas(args):
    """Bootstrap Atlas from seed themes + Hermes evidence."""
    from workspace.quant.bootstrap import bootstrap_atlas
    result = bootstrap_atlas(ROOT)
    if result.get("already_bootstrapped"):
        print("Atlas: already bootstrapped (real strategies exist)")
    elif result.get("skipped_reason"):
        print(f"Atlas: skipped ({result['skipped_reason']})")
    else:
        print(f"Atlas: {result['candidates_generated']} candidates generated, "
              f"{result['dedup_blocked']} dedup-blocked")
        if result.get("errors"):
            for e in result["errors"]:
                print(f"  ERROR: {e}")


def cmd_bootstrap_all(args):
    """Bootstrap all quant lanes in dependency order."""
    from workspace.quant.bootstrap import bootstrap_all
    results = bootstrap_all(ROOT)
    for lane, result in results.items():
        if result.get("already_bootstrapped"):
            print(f"  {lane:12s} already bootstrapped")
        elif result.get("skipped_reason"):
            print(f"  {lane:12s} skipped: {result['skipped_reason']}")
        else:
            # Summarize what was produced
            parts = []
            for key, val in result.items():
                if key.endswith("_emitted") and isinstance(val, int) and val > 0:
                    parts.append(f"{key.replace('_emitted', '')}={val}")
                elif key == "candidates_generated" and val > 0:
                    parts.append(f"candidates={val}")
                elif key == "synthesized" and val:
                    parts.append(f"tier={result.get('tier', '?')}")
            print(f"  {lane:12s} {' '.join(parts) if parts else 'no output'}")


def cmd_bootstrap_status(args):
    """Show bootstrap status for each quant lane."""
    from workspace.quant.bootstrap import get_all_bootstrap_status
    status = get_all_bootstrap_status(ROOT)
    print("BOOTSTRAP STATUS")
    print("━" * 40)
    for lane, state in status.items():
        tag = {
            "not_started": "NOT STARTED",
            "bootstrapped": "BOOTSTRAPPED",
            "active": "ACTIVE",
            "stale": "STALE",
        }.get(state, state)
        print(f"  {lane:12s} {tag}")


def cmd_observe(args):
    """Concise operator observability surface. Phone-readable truth."""
    from workspace.quant.shared.governor import load_governor_state
    from workspace.quant.shared.restart import check_stale_lanes, check_kill_switch
    from workspace.quant.shared.discord_bridge import check_delivery_health
    from workspace.quant.sigma.validation_lane import load_thresholds
    from workspace.quant.hermes.research_lane import get_watchlist_status
    from workspace.quant.shared.packet_store import list_lane_packets

    print("QUANT OBSERVE")
    print("━" * 40)

    # Bootstrap status
    try:
        from workspace.quant.bootstrap import get_all_bootstrap_status
        bs = get_all_bootstrap_status(ROOT)
        tags = []
        for lane, state in bs.items():
            if state == "not_started":
                tags.append(f"{lane}=NOT_STARTED")
            elif state == "stale":
                tags.append(f"{lane}=STALE")
        if tags:
            print(f"  Bootstrap: {', '.join(tags)}")
        else:
            print(f"  Bootstrap: all lanes active or bootstrapped")
    except Exception:
        pass

    # Market context — daily + intraday
    try:
        from workspace.quant.shared.market_context import read_market_snapshot, read_intraday_snapshot
        mkt = read_market_snapshot(ROOT)
        intra = read_intraday_snapshot(ROOT)
        if mkt:
            fresh = mkt.get("data_freshness_hours")
            age = f"{fresh:.0f}h" if fresh is not None and fresh < 48 else "stale" if fresh else "?"
            print(f"  Daily:  NQ={mkt['last_close']:.0f} ({mkt['daily_change_pct']:+.1f}%) "
                  f"VIX={mkt['vix']:.1f} trend={mkt['trend_5d']} [{age} old]")
        else:
            print("  Daily:  no data")
        if intra:
            fresh_h = intra.get("data_freshness_hours")
            age_h = f"{fresh_h:.0f}h" if fresh_h is not None and fresh_h < 48 else "stale" if fresh_h else "?"
            print(f"  Hourly: NQ={intra['last_close']:.0f} ({intra['intraday_change_pct']:+.1f}%) "
                  f"trend={intra['hourly_trend']} range={intra['intraday_range_pct']:.1f}% [{age_h} old]")
        else:
            print("  Hourly: no data")
    except Exception:
        pass
    print()

    # Governor
    gov = load_governor_state(ROOT)
    paused = [k for k, v in gov.items() if v.get("paused")]
    if paused:
        print(f"  Governor: {len(gov)} lanes, PAUSED: {', '.join(paused)}")
    else:
        print(f"  Governor: {len(gov)} lanes, all running")
    for lane in sorted(gov):
        p = gov[lane]
        batch = p.get("batch_size", 1)
        cadence = p.get("cadence_multiplier", 1.0)
        backoffs = p.get("consecutive_backoff_cycles", 0)
        status = "PAUSED" if p.get("paused") else "ok"
        print(f"    {lane:12s} batch={batch} cadence={cadence} backoffs={backoffs} {status}")

    # Stale lanes
    print()
    stale = check_stale_lanes(ROOT)
    stale_names = [l for l, i in stale.items() if i["stale"]]
    if stale_names:
        print(f"  Stale lanes: {', '.join(stale_names)}")
    else:
        print(f"  Stale lanes: none (all {len(stale)} active)")
    for lane in sorted(stale):
        info = stale[lane]
        age = f"{info['last_packet_age_hours']:.1f}h" if info['last_packet_age_hours'] is not None else "never"
        tag = "STALE" if info["stale"] else "ok"
        print(f"    {lane:12s} {age:>8s}  {tag}")

    # Delivery
    print()
    dh = check_delivery_health()
    missing = [k for k, v in dh.items() if v != "ok"]
    if missing:
        print(f"  Delivery: MISSING {', '.join(missing)}")
    else:
        print(f"  Delivery: {len(dh)} channels ok")

    # Kill switch
    ks = check_kill_switch(ROOT)
    print(f"  Kill switch: {'ENGAGED — ' + (ks['reason'] or '?') if ks['engaged'] else 'off'}")

    # Sigma thresholds
    print()
    t = load_thresholds(ROOT)
    src = t.get("_source", "?")
    v = t.get("validation", {})
    print(f"  Sigma thresholds: {src}")
    print(f"    validation: PF≥{v.get('min_profit_factor', '?')}, Sharpe≥{v.get('min_sharpe', '?')}, "
          f"DD≤{v.get('max_drawdown_pct', '?')}, trades≥{v.get('min_trades', '?')}")

    # Hermes watchlist
    wl = get_watchlist_status(ROOT)
    print(f"  Hermes watchlist: {wl['active']} active / {wl['total']} total")
    for topic in wl.get("topics", [])[:5]:
        print(f"    • {topic}")

    # Pipeline summary
    print()
    strats = load_all_strategies(ROOT)
    by_state: dict[str, int] = {}
    for s in strats.values():
        by_state[s.lifecycle_state] = by_state.get(s.lifecycle_state, 0) + 1
    if by_state:
        parts = [f"{state}={count}" for state, count in sorted(by_state.items())]
        print(f"  Pipeline: {', '.join(parts)}")
    else:
        print("  Pipeline: empty")

    # Pending approvals
    approvals = load_all_approvals(ROOT)
    active_approvals = [a for a in approvals if not a.revoked]
    if active_approvals:
        print(f"  Pending approvals: {len(active_approvals)}")
        for a in active_approvals[-3:]:
            print(f"    {a.approval_ref} → {a.strategy_id}")
    else:
        print("  Pending approvals: none")

    # Fish pending forecasts
    try:
        from workspace.quant.fish.scenario_lane import get_pending_forecasts, build_calibration_state
        pending = get_pending_forecasts(ROOT)
        cal = build_calibration_state(ROOT)
        if cal["total_calibrations"] > 0:
            hr = f"{cal['direction_hit_rate']:.0%}" if cal["direction_hit_rate"] is not None else "?"
            print(f"  Fish: {cal['total_calibrations']} calibrations, hit_rate={hr}, {len(pending)} pending")
        elif pending:
            print(f"  Fish: {len(pending)} pending forecasts, no calibrations yet")
    except Exception:
        pass

    print()


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

    sub.add_parser("pulse-status", help="Pulse lane status")
    p_pi = sub.add_parser("pulse-ingest", help="Ingest a Pulse alert")
    p_pi.add_argument("text", nargs="?", default="", help="Alert text")
    p_pi.add_argument("--level", type=float, default=None)
    p_pi.add_argument("--direction", default=None)
    p_pi.add_argument("--symbol", default="NQ")
    sub.add_parser("pulse-proposals", help="Show pending Pulse proposals")
    p_pa = sub.add_parser("pulse-approve", help="Approve a Pulse proposal")
    p_pa.add_argument("proposal_id")
    sub.add_parser("pulse-health", help="Pulse health summary")

    sub.add_parser("observe", help="Operator observability surface")
    sub.add_parser("doctor", help="Operator health check")
    sub.add_parser("acceptance", help="Non-destructive acceptance test")
    sub.add_parser("cold-start-proof", help="Prove bootstrap/cold-start behavior")

    # Bootstrap commands
    sub.add_parser("bootstrap-hermes", help="Cold-start Hermes from watchlist")
    sub.add_parser("bootstrap-fish", help="Cold-start Fish from seed config")
    sub.add_parser("bootstrap-atlas", help="Cold-start Atlas from seed themes")
    sub.add_parser("bootstrap-all", help="Bootstrap all quant lanes")
    sub.add_parser("bootstrap-status", help="Show bootstrap status per lane")

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
        "pulse-status": cmd_pulse_status,
        "pulse-ingest": cmd_pulse_ingest,
        "pulse-proposals": cmd_pulse_proposals,
        "pulse-approve": cmd_pulse_approve,
        "pulse-health": cmd_pulse_health,
        "observe": cmd_observe,
        "doctor": cmd_doctor,
        "acceptance": cmd_acceptance,
        "cold-start-proof": cmd_cold_start_proof,
        "bootstrap-hermes": cmd_bootstrap_hermes,
        "bootstrap-fish": cmd_bootstrap_fish,
        "bootstrap-atlas": cmd_bootstrap_atlas,
        "bootstrap-all": cmd_bootstrap_all,
        "bootstrap-status": cmd_bootstrap_status,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
