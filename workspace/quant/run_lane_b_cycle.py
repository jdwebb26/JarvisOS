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


# ---------------------------------------------------------------------------
# Config-driven cycle input builders
# ---------------------------------------------------------------------------

def _build_atlas_cycle_input(root: Path, market: dict | None = None) -> list[dict]:
    """Build Atlas candidate batch input from config + upstream evidence + market context.

    Sources (in priority order):
      1. atlas_sources.json seed_themes (rotating through them across cycles)
      2. Recent Hermes research packets as evidence_refs
      3. Market snapshot (OHLCV+VIX from cron data pull) for thesis enrichment

    Returns a list of candidate dicts for generate_candidate_batch(),
    or [] if no config-driven input is available.
    """
    import hashlib
    import json

    config_path = root / "workspace" / "quant" / "shared" / "config" / "atlas_sources.json"
    if not config_path.exists():
        return []
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return []

    themes = config.get("seed_themes", [])
    if not themes:
        return []

    # Gather Hermes evidence for linkage
    from workspace.quant.shared.packet_store import list_lane_packets
    hermes_pkts = list_lane_packets(root, "hermes", "research_packet")
    hermes_refs = [p.packet_id for p in hermes_pkts[-5:]]

    # If config requires Hermes evidence and none exists, skip
    if config.get("require_hermes_evidence", False) and not hermes_refs:
        return []

    # Pick one theme per cycle by rotating based on the current date-hour
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    theme_idx = (now.timetuple().tm_yday * 24 + now.hour) % len(themes)
    theme = themes[theme_idx]

    prefix = theme.get("strategy_prefix", "atlas-cycle")
    ts = now.strftime("%Y%m%dT%H%M%S")
    short = hashlib.sha256(f"{prefix}-{ts}".encode()).hexdigest()[:8]

    # Enrich thesis with market context if available
    thesis = theme["thesis"]
    confidence = theme.get("confidence", 0.4)
    if market:
        ctx_parts = []
        if market.get("vix") is not None:
            ctx_parts.append(f"VIX={market['vix']:.0f}")
        if market.get("trend_5d"):
            ctx_parts.append(f"5d-trend={market['trend_5d']}")
        if market.get("daily_change_pct") is not None:
            ctx_parts.append(f"chg={market['daily_change_pct']:+.1f}%")
        if ctx_parts:
            thesis = f"{thesis} [mkt: {', '.join(ctx_parts)}]"
        # Adjust confidence: high VIX → lower confidence for new candidates
        vix = market.get("vix", 0)
        if vix > 30:
            confidence = max(0.15, confidence - 0.1)
        elif vix < 15:
            confidence = min(0.7, confidence + 0.05)

    return [{
        "strategy_id": f"{prefix}-{short}",
        "thesis": thesis,
        "symbol_scope": theme.get("symbol_scope", "NQ"),
        "timeframe_scope": theme.get("timeframe_scope", "15m"),
        "confidence": confidence,
        "evidence_refs": hermes_refs[:3] if hermes_refs else None,
    }]


def _build_fish_cycle_input(root: Path, market: dict | None = None) -> list[dict]:
    """Build Fish scenario batch input from config + lane state + market context.

    Sources (in priority order):
      1. fish_bootstrap.json seed_scenarios (rotating across cycles)
      2. Current regime context from Fish's own regime packets
      3. Market snapshot (OHLCV+VIX from cron data pull) for scenario enrichment

    Returns a list of scenario dicts for run_scenario_batch(),
    or [] if no config-driven input is available.
    """
    import json

    config_path = root / "workspace" / "quant" / "shared" / "config" / "fish_bootstrap.json"
    if not config_path.exists():
        return []
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return []

    scenarios = config.get("seed_scenarios", [])
    if not scenarios:
        return []

    # Pick one scenario per cycle by rotating based on current date-hour
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    scenario_idx = (now.timetuple().tm_yday * 24 + now.hour) % len(scenarios)
    scenario = scenarios[scenario_idx]

    thesis = scenario["thesis"]
    confidence = scenario.get("confidence", 0.4)

    # Enrich with regime context from Fish's own state
    try:
        from workspace.quant.shared.packet_store import list_lane_packets
        regimes = list_lane_packets(root, "fish", "regime_packet")
        if regimes:
            latest_regime = regimes[-1]
            regime_label = ""
            for part in (latest_regime.notes or "").split(";"):
                if part.strip().startswith("regime="):
                    regime_label = part.strip().split("=", 1)[1]
            if regime_label:
                thesis = f"{thesis} [regime: {regime_label}]"
    except Exception:
        pass

    # Enrich with market context if available
    if market:
        ctx_parts = []
        if market.get("last_close") is not None:
            ctx_parts.append(f"NQ={market['last_close']:.0f}")
        if market.get("vix") is not None:
            ctx_parts.append(f"VIX={market['vix']:.0f}")
        if market.get("range_5d_pct") is not None:
            ctx_parts.append(f"5d-range={market['range_5d_pct']:.1f}%")
        if ctx_parts:
            thesis = f"{thesis} [mkt: {', '.join(ctx_parts)}]"
        # Adjust confidence: wide range → more volatile → lower base confidence
        range_pct = market.get("range_5d_pct", 0)
        if range_pct > 5.0:
            confidence = max(0.2, confidence - 0.1)

    return [{
        "thesis": thesis,
        "symbol_scope": scenario.get("symbol_scope", "NQ"),
        "timeframe_scope": scenario.get("timeframe_scope", "1D"),
        "confidence": confidence,
    }]


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

    # --- 1a. Read market context (cron-ingested OHLCV+VIX — daily + intraday) ---
    market = None
    intraday = None
    try:
        from workspace.quant.shared.market_context import read_market_snapshot, read_intraday_snapshot
        market = read_market_snapshot(root)
        intraday = read_intraday_snapshot(root)
        if market and verbose:
            _log(f"Market daily: NQ={market['last_close']:.0f} "
                 f"({market['daily_change_pct']:+.1f}%) VIX={market['vix']:.1f} "
                 f"trend={market['trend_5d']} "
                 f"freshness={market.get('data_freshness_hours', '?')}h")
        if intraday and verbose:
            _log(f"Market hourly: NQ={intraday['last_close']:.0f} "
                 f"({intraday['intraday_change_pct']:+.1f}%) "
                 f"trend={intraday['hourly_trend']} "
                 f"range={intraday['intraday_range_pct']:.1f}%")
        if not market and not intraday and verbose:
            _log("Market context: not available (no cron data)")
        summary["market_context"] = bool(market)
        summary["intraday_context"] = bool(intraday)
    except Exception as e:
        if verbose:
            _log(f"Market context error: {e}")
        summary["market_context"] = False
        summary["intraday_context"] = False

    # --- 1b. Bootstrap cold-start assistance ---
    # If lanes have never produced packets, bootstrap them (bounded, dedup-safe).
    try:
        from workspace.quant.bootstrap import get_all_bootstrap_status, bootstrap_hermes, bootstrap_fish
        bs = get_all_bootstrap_status(root)
        needs_bootstrap = [l for l, s in bs.items() if s == "not_started"]
        if needs_bootstrap:
            if verbose:
                _log(f"Bootstrap needed for: {', '.join(needs_bootstrap)}")
            if "hermes" in needs_bootstrap:
                try:
                    br = bootstrap_hermes(root)
                    if verbose:
                        _log(f"  Hermes bootstrap: {br.get('emitted', 0)} emitted")
                except Exception as e:
                    if verbose:
                        _log(f"  Hermes bootstrap error: {e}")
            if "fish" in needs_bootstrap:
                try:
                    br = bootstrap_fish(root)
                    if verbose:
                        _log(f"  Fish bootstrap: {br.get('scenarios_emitted', 0)} scenarios")
                except Exception as e:
                    if verbose:
                        _log(f"  Fish bootstrap error: {e}")
    except Exception:
        pass  # Bootstrap is best-effort, never blocks the cycle

    # --- 2. Hermes ---
    if verbose:
        _log("Hermes: research batch + market context ingestion")
    try:
        from workspace.quant.hermes.research_lane import run_watchlist_batch, emit_dataset, emit_health_summary
        params = get_lane_params(root, "hermes")
        if not params.get("paused"):
            # Ingest market context as a dataset_packet (dedup-safe on source key)
            dataset_emitted = 0
            if market:
                ds_source = f"cron-ohlcv-{market.get('data_updated_at', 'unknown')[:10]}"
                ds_pkt = emit_dataset(
                    root,
                    thesis=(f"NQ daily OHLCV+VIX: close={market['last_close']:.0f} "
                            f"({market['daily_change_pct']:+.1f}%), "
                            f"VIX={market['vix']:.1f}, "
                            f"5d-trend={market['trend_5d']}, "
                            f"5d-range={market['range_5d_pct']:.1f}%"),
                    dataset_name="NQ_daily_ohlcv_vix",
                    source=ds_source,
                    source_type="api",
                    symbol_scope="NQ",
                    confidence=0.8,
                )
                if ds_pkt:
                    dataset_emitted = 1
                    if verbose:
                        _log(f"  Market context ingested as dataset: {ds_pkt.packet_id}")

            # Watchlist-driven research
            emitted, info = run_watchlist_batch(root)
            total_emitted = info.get("emitted", 0) + dataset_emitted
            summary["hermes"]["emitted"] = total_emitted
            summary["hermes"]["deduped"] = info.get("deduped", 0)
            emit_health_summary(root, summary["started_at"], _ts(),
                                packets_produced=total_emitted,
                                research_emitted=info.get("emitted", 0),
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
            candidates_input = _build_atlas_cycle_input(root, market=market)
            if candidates_input:
                batch_pkt, candidates, info = generate_candidate_batch(root, candidates_input)
                summary["atlas"]["generated"] = info.get("generated", 0)
                summary["atlas"]["skipped"] = not info.get("acquired", True)
                atlas_health(root, summary["started_at"], _ts(),
                             packets_produced=len(candidates) + 1,
                             candidates_generated=len(candidates),
                             host_used=info.get("host", "NIMO"))
            elif verbose:
                _log("  Atlas: no config-driven input available this cycle")
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
            scenarios_input = _build_fish_cycle_input(root, market=market)
            if scenarios_input:
                emitted, info = run_scenario_batch(root, scenarios_input)
                summary["fish"]["emitted"] = len(emitted)
                summary["fish"]["skipped"] = not info.get("acquired", True)
                fish_health(root, summary["started_at"], _ts(),
                            packets_produced=len(emitted),
                            scenarios_emitted=len(emitted),
                            host_used=info.get("host", "SonLM"))
            elif verbose:
                _log("  Fish: no config-driven input available this cycle")
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
        if market or intraday:
            from workspace.quant.shared.market_context import format_full_market_read
            mkt_read = format_full_market_read(root)
        else:
            mkt_read = "No market data available (cron data pull may not have run yet)."
        produce_brief(root, market_read=mkt_read)
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
