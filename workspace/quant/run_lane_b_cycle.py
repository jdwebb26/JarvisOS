#!/usr/bin/env python3
"""Quant Lanes — Lane B Cycle Runner.

One-shot, restart-safe, repeatable runner for a single Lane B cycle.
Safe for cron/systemd invocation.

Cycle order (spec §2 priority):
  1. Restart recovery (stale cleanup, coherence check)
  2. Hermes research batch (if requests exist or watchlist items due)
  3. Atlas candidate batch (if governor/scheduler permit)
  4. Fish scenario batch (if governor/scheduler permit)
  5. TradeFloor synthesis (only if cadence allows)
  6. Kitt brief update

Never touches live trading.
Never requires manual approval for routine Lane B work.
Never floods Discord — only TradeFloor tier 3+ emits a kitt-facing event.
"""
from __future__ import annotations

import fcntl
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import QuantPacket
from workspace.quant.shared.packet_store import get_all_latest
from workspace.quant.shared.restart import recover_lane_state, clear_stale_scheduler_jobs, check_latest_coherence
from workspace.quant.shared.governor import get_lane_params
from workspace.quant.shared.discord_bridge import emit_quant_event

_ts = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731

LOCK_PATH = ROOT / "workspace" / "quant" / "shared" / "scheduler" / "lane_b_cycle.lock"


def _log(msg: str):
    print(f"  {msg}")


def acquire_cycle_lock():
    """Try to acquire exclusive file lock. Returns open file or None if already locked."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fp = open(LOCK_PATH, "w")
    try:
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fp
    except BlockingIOError:
        fp.close()
        return None


def run_cycle(root: Path, verbose: bool = False) -> dict:
    """Run one Lane B cycle. Returns a summary dict."""
    summary = {
        "started_at": _ts(),
        "hermes": {"emitted": 0, "deduped": 0},
        "atlas": {"generated": 0, "skipped": False},
        "fish": {"emitted": 0, "skipped": False},
        "tradefloor": {"ran": False, "tier": None, "cadence_refused": False},
        "brief": False,
        "errors": [],
    }

    # --- 1. Recovery ---
    if verbose:
        _log("Recovery: stale cleanup + coherence check")
    try:
        clear_stale_scheduler_jobs(root)
        coherent, issues = check_latest_coherence(root)
        if not coherent and verbose:
            _log(f"  Coherence issues: {issues}")
    except Exception as e:
        summary["errors"].append(f"recovery: {e}")

    # --- 2. Hermes ---
    if verbose:
        _log("Hermes: research batch")
    try:
        from workspace.quant.hermes.research_lane import run_research_batch, emit_health_summary
        params = get_lane_params(root, "hermes")
        if not params.get("paused"):
            # Use stub requests — in real use these come from research_request_packets or watchlist
            stubs = [
                {"thesis": "NQ overnight volume profile analysis", "source": f"cycle-{_ts()[:10]}", "source_type": "web"},
            ]
            emitted, info = run_research_batch(root, stubs)
            summary["hermes"]["emitted"] = len(emitted)
            summary["hermes"]["deduped"] = info.get("deduped", 0)
            emit_health_summary(root, summary["started_at"], _ts(),
                                packets_produced=len(emitted), research_emitted=len(emitted),
                                dedup_skips=info.get("deduped", 0),
                                host_used=info.get("host", "mixed"))
        elif verbose:
            _log("  Hermes paused by governor")
    except Exception as e:
        summary["errors"].append(f"hermes: {e}")

    # --- 3. Atlas ---
    if verbose:
        _log("Atlas: candidate batch")
    try:
        from workspace.quant.atlas.exploration_lane import generate_candidate_batch, emit_health_summary as atlas_health
        params = get_lane_params(root, "atlas")
        if params.get("paused"):
            summary["atlas"]["skipped"] = True
            if verbose:
                _log("  Atlas paused by governor")
        else:
            import hashlib
            batch_id = hashlib.sha256(_ts().encode()).hexdigest()[:8]
            stubs = [
                {"strategy_id": f"atlas-cycle-{batch_id}",
                 "thesis": "NQ mean-reversion with volume confirmation (cycle-generated)"},
            ]
            batch_pkt, candidates, info = generate_candidate_batch(root, stubs)
            summary["atlas"]["generated"] = info.get("generated", 0)
            summary["atlas"]["skipped"] = not info.get("acquired", True)
            atlas_health(root, summary["started_at"], _ts(),
                         packets_produced=len(candidates) + 1,
                         candidates_generated=len(candidates),
                         host_used=info.get("host", "NIMO"))
    except Exception as e:
        summary["errors"].append(f"atlas: {e}")

    # --- 4. Fish ---
    if verbose:
        _log("Fish: scenario batch")
    try:
        from workspace.quant.fish.scenario_lane import run_scenario_batch, emit_health_summary as fish_health
        params = get_lane_params(root, "fish")
        if params.get("paused"):
            summary["fish"]["skipped"] = True
            if verbose:
                _log("  Fish paused by governor")
        else:
            stubs = [
                {"thesis": "NQ consolidation before next FOMC (cycle scenario)"},
            ]
            emitted, info = run_scenario_batch(root, stubs)
            summary["fish"]["emitted"] = len(emitted)
            summary["fish"]["skipped"] = not info.get("acquired", True)
            fish_health(root, summary["started_at"], _ts(),
                        packets_produced=len(emitted),
                        scenarios_emitted=len(emitted),
                        host_used=info.get("host", "SonLM"))
    except Exception as e:
        summary["errors"].append(f"fish: {e}")

    # --- 5. TradeFloor ---
    if verbose:
        _log("TradeFloor: synthesis (if cadence allows)")
    try:
        from workspace.quant.tradefloor.synthesis_lane import synthesize, check_cadence, CadenceRefused
        can_run, remaining = check_cadence(root)
        if can_run:
            tf_pkt = synthesize(root)
            summary["tradefloor"]["ran"] = True
            summary["tradefloor"]["tier"] = tf_pkt.agreement_tier
            # Only emit to Discord if tier >= 3 (sparse behavior)
            if tf_pkt.agreement_tier is not None and tf_pkt.agreement_tier >= 3:
                emit_quant_event(tf_pkt, root=root)
        else:
            summary["tradefloor"]["cadence_refused"] = True
            if verbose:
                _log(f"  Cadence: {remaining:.0f}s remaining")
    except CadenceRefused:
        summary["tradefloor"]["cadence_refused"] = True
    except Exception as e:
        summary["errors"].append(f"tradefloor: {e}")

    # --- 6. Kitt brief ---
    if verbose:
        _log("Kitt: producing brief")
    try:
        from workspace.quant.kitt.brief_producer import produce_brief
        produce_brief(root, market_read="Automated Lane B cycle. No live market data.")
        summary["brief"] = True
    except Exception as e:
        summary["errors"].append(f"brief: {e}")

    summary["finished_at"] = _ts()
    return summary


def main():
    import argparse
    p = argparse.ArgumentParser(description="Run one Lane B cycle")
    p.add_argument("-v", "--verbose", action="store_true", help="Print progress")
    args = p.parse_args()

    lock = acquire_cycle_lock()
    if lock is None:
        print("Lane B cycle: another run is active, skipping")
        return 0

    try:
        print("Lane B cycle starting")
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
        if s["errors"]:
            parts.append(f"errors={len(s['errors'])}")

        print(f"Lane B cycle done: {' '.join(parts) or 'nothing produced'}")
        if s["errors"]:
            for e in s["errors"]:
                print(f"  ERROR: {e}")
            return 1
        return 0
    finally:
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
