#!/usr/bin/env python3
"""Kitt Paper Trading Cycle Runner.

Runs ONE bounded autonomous cycle:
    1. Fetch current NQ price + recent bars
    2. Check open positions for stop/TP hits
    3. Compute a simple signal from recent price action
    4. Decide: open / hold / close / no-trade
    5. Execute paper action if warranted
    6. Write decision record, packet, and brief

PAPER ONLY — no live trading capability exists in this module.

Usage:
    python3 workspace/quant_infra/kitt/run_kitt_cycle.py
    python3 workspace/quant_infra/kitt/run_kitt_cycle.py --dry-run
    python3 workspace/quant_infra/kitt/run_kitt_cycle.py --status
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

QUANT_INFRA = Path(__file__).resolve().parent.parent
REPO_ROOT = QUANT_INFRA.parent.parent
sys.path.insert(0, str(QUANT_INFRA))
sys.path.insert(0, str(REPO_ROOT))

from kitt.paper_trader import (
    check_stops,
    check_targets,
    get_status,
    mark_all_positions,
    open_position,
)
from packets.writer import write_packet, read_packet
from warehouse.loader import get_connection, insert_trade_decision
from events.emitter import emit_event

THIS_DIR = Path(__file__).resolve().parent
WAREHOUSE_PATH = QUANT_INFRA / "warehouse" / "quant.duckdb"
BRIEFS_DIR = QUANT_INFRA / "research" / "kitt_briefs"
THESIS_STATE_PATH = THIS_DIR / "thesis_state.json"

# -- Signal parameters (conservative mean-reversion) --
EMA_FAST = 8
EMA_SLOW = 21
ATR_PERIOD = 14
ENTRY_ATR_MULT = 1.8      # enter when deviation > 1.8 * ATR
STOP_ATR_MULT = 2.5        # stop at 2.5 * ATR from entry
TP_ATR_MULT = 1.5          # take-profit at 1.5 * ATR from entry
MIN_ATR_ABS = 20.0         # minimum absolute ATR to trade (NQ points)
DEFAULT_MAX_OPEN_POSITIONS = 3  # default max open paper positions (configurable via risk_limits.json)


def _get_max_open_positions() -> int:
    """Read max open positions from risk_limits.json, falling back to default.

    This enables multi-strategy support: operators can raise the limit as
    more strategies are promoted to paper trading.
    """
    risk_path = REPO_ROOT / "workspace" / "quant" / "shared" / "config" / "risk_limits.json"
    try:
        if risk_path.exists():
            limits = json.loads(risk_path.read_text())
            return limits.get("portfolio", {}).get("max_open_positions", DEFAULT_MAX_OPEN_POSITIONS)
    except (json.JSONDecodeError, OSError):
        pass
    return DEFAULT_MAX_OPEN_POSITIONS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid(prefix: str = "kpd") -> str:
    import uuid
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Thesis state — persisted snapshot for detecting meaningful changes
# ---------------------------------------------------------------------------

def _load_thesis_state() -> dict:
    """Load last cycle's thesis state from disk."""
    if THESIS_STATE_PATH.exists():
        try:
            return json.loads(THESIS_STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_thesis_state(state: dict) -> None:
    """Persist current thesis state for next cycle comparison."""
    THESIS_STATE_PATH.write_text(json.dumps(state, indent=2, default=str) + "\n")


def _classify_regime(signal: dict) -> str:
    """Classify the current market regime from signal data."""
    atr = signal.get("atr", 0)
    deviation = abs(signal.get("deviation", 0))
    if atr < MIN_ATR_ABS:
        return "low_vol"
    if deviation > atr * 2.5:
        return "trending"
    if deviation > atr * ENTRY_ATR_MULT:
        return "extended"
    return "normal"


def _detect_thesis_change(prev: dict, current: dict, position_open: bool) -> str | None:
    """Detect meaningful thesis change between cycles.

    Returns a reason string if a change is detected, None otherwise.
    Only emits when a position is open (otherwise changes are expected).
    """
    if not position_open or not prev:
        return None

    prev_regime = prev.get("regime", "")
    curr_regime = current.get("regime", "")
    if prev_regime and curr_regime and prev_regime != curr_regime:
        return f"Regime shift: {prev_regime} → {curr_regime}"

    prev_signal = prev.get("signal_direction", "")
    curr_signal = current.get("signal_direction", "")
    if prev_signal and curr_signal and prev_signal != curr_signal and curr_signal != "none":
        return f"Signal reversal: {prev_signal} → {curr_signal}"

    return None


# ---------------------------------------------------------------------------
# Market data fetch
# ---------------------------------------------------------------------------

def fetch_recent_bars(n_bars: int = 60) -> list[dict]:
    """Fetch recent 15-minute NQ bars from yfinance.

    Returns list of dicts with: open, high, low, close, volume, datetime.
    Most recent bar last.
    """
    try:
        import yfinance as yf
        df = yf.download("NQ=F", period="5d", interval="15m", progress=False)
        if df.empty:
            return []
        if df.columns.nlevels > 1:
            df.columns = df.columns.droplevel(1)
        df.columns = [c.lower() for c in df.columns]
        bars = []
        for idx, row in df.tail(n_bars).iterrows():
            bars.append({
                "datetime": str(idx),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
            })
        return bars
    except Exception as exc:
        print(f"[kitt] WARNING: fetch failed: {exc}")
        return []


def fetch_current_price() -> float | None:
    """Fetch the latest NQ price."""
    bars = fetch_recent_bars(n_bars=1)
    return bars[-1]["close"] if bars else None


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------

def compute_signal(bars: list[dict]) -> dict:
    """Compute a bounded mean-reversion signal from recent bars.

    Returns dict with:
        - ema_fast, ema_slow: current EMA values
        - atr: current ATR
        - deviation: close - ema_slow (signed)
        - signal: 'long', 'short', or 'none'
        - entry, stop, target: price levels if signal != 'none'
        - reason: human-readable explanation
    """
    if len(bars) < max(EMA_SLOW, ATR_PERIOD) + 5:
        return {"signal": "none", "reason": f"insufficient bars ({len(bars)})",
                "ema_fast": 0, "ema_slow": 0, "atr": 0, "deviation": 0}

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]

    # EMA computation
    def _ema(values, period):
        mult = 2.0 / (period + 1)
        result = values[0]
        for v in values[1:]:
            result = v * mult + result * (1 - mult)
        return result

    ema_f = _ema(closes, EMA_FAST)
    ema_s = _ema(closes, EMA_SLOW)

    # ATR computation
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[-ATR_PERIOD:]) / ATR_PERIOD if len(trs) >= ATR_PERIOD else 0

    current_price = closes[-1]
    deviation = current_price - ema_s
    threshold = atr * ENTRY_ATR_MULT

    result = {
        "ema_fast": round(ema_f, 2),
        "ema_slow": round(ema_s, 2),
        "atr": round(atr, 2),
        "deviation": round(deviation, 2),
        "current_price": current_price,
        "signal": "none",
        "entry": None,
        "stop": None,
        "target": None,
        "reason": "",
    }

    if atr < MIN_ATR_ABS:
        result["reason"] = f"ATR too low ({atr:.2f} < {MIN_ATR_ABS})"
        return result

    if deviation < -threshold:
        # Price below EMA — mean revert long
        entry = current_price
        stop = round(entry - atr * STOP_ATR_MULT, 2)
        target = round(entry + atr * TP_ATR_MULT, 2)
        result.update({
            "signal": "long",
            "entry": entry,
            "stop": stop,
            "target": target,
            "reason": (f"Mean reversion long: price {current_price:.2f} is "
                       f"{abs(deviation):.2f} below EMA({EMA_SLOW})={ema_s:.2f}, "
                       f"threshold={threshold:.2f}, ATR={atr:.2f}"),
        })
    elif deviation > threshold:
        # Price above EMA — mean revert short
        entry = current_price
        stop = round(entry + atr * STOP_ATR_MULT, 2)
        target = round(entry - atr * TP_ATR_MULT, 2)
        result.update({
            "signal": "short",
            "entry": entry,
            "stop": stop,
            "target": target,
            "reason": (f"Mean reversion short: price {current_price:.2f} is "
                       f"{deviation:.2f} above EMA({EMA_SLOW})={ema_s:.2f}, "
                       f"threshold={threshold:.2f}, ATR={atr:.2f}"),
        })
    else:
        result["reason"] = (f"No signal: deviation {deviation:.2f} within "
                            f"threshold ±{threshold:.2f}")

    return result


# ---------------------------------------------------------------------------
# Cycle decision logic
# ---------------------------------------------------------------------------

def _check_governor() -> bool:
    """Check if governor has paused the kitt lane. Returns True if OK to run."""
    try:
        from workspace.quant.shared.governor import get_lane_params
        params = get_lane_params(REPO_ROOT, "kitt")
        if params.get("paused"):
            print("[kitt] Governor: lane is PAUSED — skipping cycle")
            return False
    except Exception as exc:
        print(f"[kitt] Governor check failed (running anyway): {exc}")
    return True


def _report_governor(action: str) -> None:
    """Report cycle outcome to governor for next-cycle adaptation."""
    try:
        from workspace.quant.shared.governor import evaluate_cycle
        # Simple scoring: successful cycle = healthy, skip/error = lower
        health = 0.8 if action not in ("skip",) else 0.4
        usefulness = 0.6 if action in ("hold", "open_long", "open_short") else 0.3
        gov_action, gov_reason = evaluate_cycle(
            REPO_ROOT, "kitt",
            usefulness_score=usefulness,
            efficiency_score=0.7,
            health_score=health,
            confidence_score=0.5,
        )
        if gov_action != "hold":
            print(f"[kitt] Governor: {gov_action} — {gov_reason}")
    except Exception as exc:
        print(f"[kitt] Governor report failed: {exc}")


def run_cycle(dry_run: bool = False) -> dict:
    """Execute one bounded Kitt paper-trading cycle.

    Returns a decision record dict.
    """
    # Governor gate
    if not dry_run and not _check_governor():
        return {"decision_id": "", "action": "governor_paused",
                "reasoning": "Lane paused by governor"}

    now = datetime.now(timezone.utc)
    print(f"[kitt] Cycle start: {now.strftime('%Y-%m-%d %H:%M UTC')}")

    # 1. Fetch market data
    bars = fetch_recent_bars(n_bars=60)
    if not bars:
        return _record_decision("skip", "no_data",
                                "Could not fetch market data", dry_run=dry_run)

    current_price = bars[-1]["close"]
    print(f"[kitt] NQ price: {current_price:.2f} ({len(bars)} bars)")

    # 2. Check stops on existing positions
    status = get_status()
    open_positions = status["open_positions"]

    cycle_event = None  # Track what event was emitted this cycle

    if open_positions and not dry_run:
        # Snapshot positions before stop/target check
        pre_check_positions = list(open_positions)
        stopped = check_stops(current_price)
        if stopped:
            print(f"[kitt] Stopped out: {stopped}")
            for sid in stopped:
                stopped_pos = next((p for p in pre_check_positions if p["position_id"] == sid), None)
                if stopped_pos:
                    emit_event(
                        "kitt", "stop_triggered",
                        side=stopped_pos["direction"],
                        entry=stopped_pos["entry_price"],
                        stop=stopped_pos["stop_loss"],
                        target=stopped_pos["take_profit"],
                        current_mark=current_price,
                        position_id=sid,
                        reason=f"Stop loss triggered at {stopped_pos['stop_loss']}",
                        source_packet="kitt_cycle",
                    )
            cycle_event = "stop_triggered"

        # Check take-profit targets
        hit = check_targets(current_price)
        if hit:
            print(f"[kitt] Target hit: {hit}")
            cycle_event = "target_hit"

        mark_all_positions(current_price)

    # Refresh status after potential stop-outs
    if open_positions:
        status = get_status()
        open_positions = status["open_positions"]

    # 3. Compute signal — multi-strategy aware
    # Try the signal registry first (selects best signal across families for current regime),
    # falling back to the original compute_signal for backward compatibility.
    signal_family = None
    try:
        from kitt.signals import select_best_signal, load_strategy_config
        strategy_config = load_strategy_config()
        regime_preview = _classify_regime(compute_signal(bars))
        allowed = strategy_config.get("regime_assignments", {}).get(regime_preview)
        best = select_best_signal(bars, allowed_families=allowed)
        if best and best.signal != "none":
            signal = {
                "signal": best.signal, "entry": best.entry, "stop": best.stop,
                "target": best.target, "reason": best.reason,
                "atr": best.atr, "deviation": best.deviation,
                "ema_fast": best.indicators.get("ema_fast", 0),
                "ema_slow": best.indicators.get("ema_slow", 0),
                "current_price": best.current_price,
            }
            signal_family = best.family
            print(f"[kitt] Multi-strategy: selected {best.family} (confidence={best.confidence:.2f})")
        else:
            signal = compute_signal(bars)
    except Exception:
        signal = compute_signal(bars)
    regime = _classify_regime(signal)

    # 4. If already at max positions, decide hold or manage
    max_positions = _get_max_open_positions()
    if len(open_positions) >= max_positions:
        # Summarize all open positions (multi-strategy aware)
        total_unrealized = 0.0
        position_summaries = []
        for pos in open_positions:
            mult = 1 if pos["direction"] == "long" else -1
            unrealized = round((current_price - pos["entry_price"]) * mult, 2) if pos["entry_price"] else 0
            total_unrealized += unrealized
            strat = pos.get("strategy_id") or "kitt-default"
            position_summaries.append(
                f"{pos['direction']} NQ @ {pos['entry_price']} ({strat}, "
                f"unrealized={unrealized:+.2f} pts)"
            )

        # Thesis change detection (uses most recent position for primary tracking)
        primary_pos = open_positions[0]
        prev_state = _load_thesis_state()
        current_state = {
            "regime": regime,
            "signal_direction": signal["signal"],
            "atr": signal.get("atr"),
            "deviation": signal.get("deviation"),
            "position_id": primary_pos["position_id"],
            "open_position_count": len(open_positions),
            "total_unrealized_pts": round(total_unrealized, 2),
            "updated_at": _now(),
        }

        thesis_change = _detect_thesis_change(prev_state, current_state, True)
        if thesis_change and not dry_run:
            emit_event(
                "kitt", "thesis_changed",
                side=primary_pos["direction"],
                entry=primary_pos["entry_price"],
                stop=primary_pos["stop_loss"],
                target=primary_pos["take_profit"],
                current_mark=current_price,
                position_id=primary_pos["position_id"],
                reason=thesis_change,
                source_packet="kitt_cycle",
                extra={"regime": regime, "signal": signal["signal"],
                       "open_positions": len(open_positions)},
            )
            cycle_event = "thesis_changed"
            print(f"[kitt] Thesis change: {thesis_change}")

        _save_thesis_state(current_state)

        reason = (f"Holding {len(open_positions)} position(s) "
                  f"(max {max_positions}), total unrealized={total_unrealized:+.2f} pts: "
                  + "; ".join(position_summaries[:3]))
        return _record_decision("hold", reason, reason, dry_run=dry_run,
                                market_context=_market_context(bars),
                                position_id=primary_pos["position_id"],
                                signal=signal, regime=regime,
                                cycle_event=cycle_event)

    print(f"[kitt] Signal: {signal['signal']} — {signal['reason']}")

    if signal["signal"] == "none":
        _save_thesis_state({"regime": regime, "signal_direction": "none",
                            "atr": signal.get("atr"), "updated_at": _now()})
        return _record_decision("no_trade", signal["reason"], signal["reason"],
                                dry_run=dry_run,
                                market_context=_market_context(bars),
                                signal=signal, regime=regime,
                                cycle_event=cycle_event)

    # 5. Execute paper trade
    direction = signal["signal"]
    entry = signal["entry"]
    stop = signal["stop"]
    target = signal["target"]
    reason = signal["reason"]

    if dry_run:
        print(f"[kitt] DRY RUN: would open {direction} @ {entry}, SL={stop}, TP={target}")
        return _record_decision(f"open_{direction}", reason,
                                f"DRY RUN: {reason}", dry_run=True,
                                market_context=_market_context(bars),
                                signal=signal, regime=regime)

    pos_id = open_position(direction, entry, stop, target, reason,
                           strategy_id=signal_family)
    print(f"[kitt] Opened: {pos_id} (strategy: {signal_family or 'kitt-default'})")

    # Emit event for new position
    emit_event(
        "kitt", "position_opened",
        side=direction,
        entry=entry,
        stop=stop,
        target=target,
        current_mark=current_price,
        position_id=pos_id,
        reason=reason,
        source_packet="kitt_cycle",
    )
    cycle_event = "position_opened"

    _save_thesis_state({
        "regime": regime, "signal_direction": direction,
        "atr": signal.get("atr"), "position_id": pos_id,
        "updated_at": _now(),
    })

    return _record_decision(f"open_{direction}", reason, reason,
                            dry_run=False, position_id=pos_id,
                            market_context=_market_context(bars),
                            signal=signal, regime=regime,
                            cycle_event=cycle_event)


def _market_context(bars: list[dict]) -> str:
    """Build a compact market context string from recent bars."""
    if not bars:
        return "no data"
    last = bars[-1]
    high_5 = max(b["high"] for b in bars[-20:]) if len(bars) >= 20 else max(b["high"] for b in bars)
    low_5 = min(b["low"] for b in bars[-20:]) if len(bars) >= 20 else min(b["low"] for b in bars)
    return (f"NQ={last['close']:.2f} range=[{low_5:.2f},{high_5:.2f}] "
            f"bars={len(bars)} ts={last['datetime']}")


def _record_decision(
    action: str,
    reasoning: str,
    detail: str,
    dry_run: bool = False,
    position_id: str | None = None,
    market_context: str = "",
    signal: dict | None = None,
    regime: str | None = None,
    cycle_event: str | None = None,
) -> dict:
    """Record a cycle decision to DuckDB + packet + brief."""
    decision = {
        "decision_id": _uid("kpd"),
        "decided_at": _now(),
        "action": action,
        "symbol": "NQ",
        "reasoning": reasoning,
        "confidence": None,
        "market_context": market_context,
        "position_id": position_id or "",
        "upstream_packets": "",
    }

    if not dry_run:
        con = get_connection(WAREHOUSE_PATH)
        try:
            insert_trade_decision(con, decision)

            # Write enriched packet
            status = get_status()

            # Compute per-position enrichment for cycle packet
            now = datetime.now(timezone.utc)
            enriched_positions = []
            for p in status["open_positions"]:
                entry = p["entry_price"]
                mark = p.get("mark_price") or entry
                direction = p["direction"]
                mult = 1 if direction == "long" else -1
                unrealized = round((mark - entry) * mult, 2) if entry else 0
                stop = p.get("stop_loss")
                target = p.get("take_profit")
                risk = abs(entry - stop) if entry and stop else None
                reward = abs(target - entry) if entry and target else None
                rr = round(reward / risk, 2) if risk and reward and risk > 0 else None

                ep = dict(p)
                ep.update({
                    "unrealized_pnl_pts": unrealized,
                    "unrealized_pnl_usd": round(unrealized * 20, 2),
                    "reward_risk": rr,
                    "dist_to_stop_pts": round((mark - stop) * mult, 2) if mark and stop else None,
                    "dist_to_target_pts": round((target - mark) * mult, 2) if mark and target else None,
                })
                enriched_positions.append(ep)

            # Build invalidation note
            invalidation = None
            if enriched_positions:
                ep = enriched_positions[0]
                if ep.get("stop_loss"):
                    invalidation = f"Thesis invalidated if NQ reaches stop at {ep['stop_loss']}"

            write_packet(
                lane="kitt",
                packet_type="cycle",
                summary=f"Kitt cycle: {action} — {reasoning[:80]}",
                data={
                    "decision": decision,
                    "regime": regime,
                    "signal": {
                        "direction": signal.get("signal") if signal else None,
                        "atr": signal.get("atr") if signal else None,
                        "deviation": signal.get("deviation") if signal else None,
                        "ema_fast": signal.get("ema_fast") if signal else None,
                        "ema_slow": signal.get("ema_slow") if signal else None,
                    } if signal else None,
                    "open_positions": enriched_positions,
                    "performance": status["performance"],
                    "cycle_event": cycle_event,
                    "invalidation": invalidation,
                },
                upstream=[],
                source_module="kitt.run_kitt_cycle",
                confidence=0.5,
            )

            # Write brief
            _write_cycle_brief(action, reasoning, status, market_context,
                               signal=signal, regime=regime,
                               cycle_event=cycle_event)
        finally:
            con.close()

    print(f"[kitt] Decision: {action} — {reasoning[:100]}")
    return decision


def _write_cycle_brief(action: str, reasoning: str, status: dict,
                       market_context: str, *, signal: dict | None = None,
                       regime: str | None = None,
                       cycle_event: str | None = None) -> None:
    """Write spec §7 compliant Kitt cycle brief with all 9 sections + thesis tracking."""
    now = datetime.now(timezone.utc)
    perf = status["performance"]

    md = f"""KITT BRIEF — {now.strftime('%Y-%m-%d %H:%M UTC')}
{'━' * 40}

MARKET READ
{market_context}
"""
    if regime:
        md += f"  Regime: {regime}\n"
    if signal:
        md += (f"  Signal: {signal.get('signal', 'n/a')} | "
               f"ATR={signal.get('atr', 'n/a')} | "
               f"Deviation={signal.get('deviation', 'n/a')}\n")
    if cycle_event:
        md += f"  Event: {cycle_event}\n"

    md += f"""
TOP SIGNAL
{action.upper()}: {reasoning}

PIPELINE
"""
    # Read strategy registry for pipeline snapshot
    pipeline = _get_pipeline_snapshot()
    md += f"  PAPER_ACTIVE: {pipeline['paper_active_count']} strategies"
    if pipeline["paper_active_ids"]:
        md += f" ({', '.join(pipeline['paper_active_ids'])})"
    md += f"\n  LIVE_ACTIVE:  {pipeline['live_active_count']} strategies"
    if pipeline["live_active_ids"]:
        md += f" ({', '.join(pipeline['live_active_ids'])})"
    md += "\n"
    if pipeline["near_promotion"]:
        md += f"  Near promotion: {', '.join(pipeline['near_promotion'])}\n"

    md += "\nPORTFOLIO SNAPSHOT\n"
    portfolio = _compute_portfolio_snapshot(status)
    md += f"  Total exposure: {portfolio['position_count']} position(s), {portfolio['strategy_count']} strategy(ies)\n"
    md += f"  PnL: ${perf['total_pnl']:.2f} ({perf['total_trades']} trades, {perf['wins']}W/{perf['losses']}L)\n"
    md += f"  Concentration: {portfolio['concentration_status']}\n"
    md += f"  Correlation: {portfolio['correlation_status']}\n"

    md += "\nLANE ACTIVITY\n"
    lane_activity = _get_lane_activity()
    for lane_name, summary in lane_activity.items():
        md += f"  {lane_name:8s} {summary}\n"

    # TradeFloor
    tf = _get_tradefloor_summary()
    if tf:
        md += f"\nTRADEFLOOR\n"
        md += f"  Agreement tier: {tf['tier']} ({tf['tier_name']})\n"
        if tf.get("reasoning"):
            md += f"  {tf['reasoning'][:80]}\n"

    md += f"\nEXECUTION ({len(status['open_positions'])} open, max {_get_max_open_positions()})\n"
    if status["open_positions"]:
        # Group by strategy for multi-strategy visibility
        by_strategy: dict[str, list] = {}
        for p in status["open_positions"]:
            strat = p.get("strategy_id") or "kitt-default"
            by_strategy.setdefault(strat, []).append(p)

        for strat_id, positions in by_strategy.items():
            if len(by_strategy) > 1:
                md += f"  --- Strategy: {strat_id} ({len(positions)} position(s)) ---\n"
            for p in positions:
                entry = p["entry_price"]
                mark = p.get("mark_price") or entry
                direction = p["direction"]
                mult = 1 if direction == "long" else -1
                unrealized = round((mark - entry) * mult, 2) if entry else 0
                stop = p.get("stop_loss")
                target = p.get("take_profit")
                dist_stop = round((mark - stop) * mult, 2) if mark and stop else None
                dist_target = round((target - mark) * mult, 2) if mark and target else None
                risk = abs(entry - stop) if entry and stop else None
                reward = abs(target - entry) if entry and target else None
                rr = round(reward / risk, 2) if risk and reward and risk > 0 else None

                md += (f"  {p['position_id']}: {direction} NQ "
                       f"@ {entry} -> mark {mark}\n")
                md += f"    SL={stop} | TP={target} | R:R={rr}\n"
                md += f"    Unrealized: {unrealized:+.2f} pts (${unrealized * 20:+.2f})\n"
                if dist_stop is not None:
                    md += f"    Distance to stop: {dist_stop:.2f} pts | to target: {dist_target:.2f} pts\n"
                if p.get("reasoning"):
                    md += f"    Thesis: {p['reasoning'][:120]}\n"
                if stop:
                    md += f"    Invalidation: thesis fails if NQ reaches {stop}\n"
    else:
        md += "  No active positions\n"

    # Rejection Intelligence section (consumption plan Step 2)
    rej_summary = _get_rejection_summary()
    if rej_summary.get("has_data"):
        md += "\nREJECTION INTELLIGENCE\n"
        if rej_summary["cooldown_families"]:
            md += f"  Cooldown families: {', '.join(rej_summary['cooldown_families'])}\n"
        if rej_summary["near_misses"]:
            md += f"  Near-miss families: {', '.join(rej_summary['near_misses'])}\n"
        if rej_summary["top_reasons"]:
            md += "  Top rejection reasons: "
            md += ", ".join(f"{r['reason']}({r['count']})" for r in rej_summary["top_reasons"])
            md += "\n"
        if rej_summary["exploration_shifts"]:
            for shift in rej_summary["exploration_shifts"]:
                md += f"  >> {shift}\n"

    # Slippage tracking section
    slip_summary = _get_slippage_summary()
    if slip_summary.get("has_data"):
        md += "\nSLIPPAGE TRACKING\n"
        md += f"  Trades with slippage data: {slip_summary['trade_count']}\n"
        md += f"  Mean slippage: {slip_summary['mean_slippage']:.2f} pts\n"
        md += f"  Max slippage: {slip_summary['max_slippage']:.2f} pts\n"
        md += f"  Total slippage cost: ${slip_summary['total_slippage_usd']:.2f}\n"

    md += "\nSYSTEM HEALTH\n"
    health = _get_system_health()
    md += f"  Active lanes: {', '.join(health['active_lanes']) or 'none'}\n"
    md += f"  Silent/errored: {', '.join(health['silent_lanes']) or 'all healthy'}\n"
    if health["circuit_breakers"]:
        for cb in health["circuit_breakers"]:
            md += f"  !! {cb['lane']}: {cb['detail']}\n"
    else:
        md += "  Circuit breakers: all clear\n"
    feedback = _get_feedback_loop_status()
    md += f"  Feedback loops: Atlas consuming rejections: {feedback['atlas_consuming']}, "
    md += f"Fish calibrating: {feedback['fish_calibrating']}\n"

    md += "\nOPERATOR ACTION NEEDED\n"
    actions = _get_operator_actions(pipeline, health)
    if actions:
        for a in actions:
            md += f"  - {a}\n"
    else:
        md += "  none\n"

    # What changed since last cycle
    prev_state = _load_thesis_state()
    if prev_state:
        md += "\n## Changes Since Last Cycle\n"
        prev_regime = prev_state.get("regime")
        if prev_regime and regime and prev_regime != regime:
            md += f"- Regime: {prev_regime} → {regime}\n"
        prev_signal = prev_state.get("signal_direction")
        sig_dir = signal.get("signal") if signal else None
        if prev_signal and sig_dir and prev_signal != sig_dir:
            md += f"- Signal: {prev_signal} → {sig_dir}\n"
        if not any([prev_regime != regime if prev_regime and regime else False,
                    prev_signal != sig_dir if prev_signal and sig_dir else False]):
            md += "- No material changes\n"

    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    (BRIEFS_DIR / "latest.md").write_text(md)
    ts = now.strftime("%Y%m%dT%H%M%S")
    (BRIEFS_DIR / f"cycle_{ts}.md").write_text(md)


# ---------------------------------------------------------------------------
# Brief data helpers — read shared state for spec §7 sections
# ---------------------------------------------------------------------------

def _compute_portfolio_snapshot(status: dict) -> dict:
    """Compute portfolio concentration and correlation per spec §15.

    Concentration: flags if any single strategy holds > threshold of total exposure.
    Correlation: flags if multiple strategies trade the same symbol/direction.
    """
    positions = status["open_positions"]
    risk_path = REPO_ROOT / "workspace" / "quant" / "shared" / "config" / "risk_limits.json"
    try:
        limits = json.loads(risk_path.read_text()) if risk_path.exists() else {}
    except (json.JSONDecodeError, OSError):
        limits = {}

    portfolio_limits = limits.get("portfolio", {})
    max_exposure = portfolio_limits.get("max_total_exposure", 4)
    concentration_threshold = portfolio_limits.get("concentration_threshold", 0.6)

    # Count active strategies from registry
    registry = REPO_ROOT / "workspace" / "quant" / "shared" / "registries" / "strategies.jsonl"
    active_strategies = []
    try:
        if registry.exists():
            for line in registry.read_text().strip().splitlines():
                entry = json.loads(line)
                if entry.get("lifecycle_state") in ("PAPER_ACTIVE", "LIVE_ACTIVE"):
                    active_strategies.append(entry.get("strategy_id", ""))
    except (json.JSONDecodeError, OSError):
        pass

    strategy_count = len(active_strategies)

    # Concentration check: is any one symbol > threshold of total positions?
    concentration_status = "clean"
    if positions:
        symbol_counts: dict[str, int] = {}
        for p in positions:
            sym = p.get("symbol", "NQ")
            symbol_counts[sym] = symbol_counts.get(sym, 0) + 1
        total = sum(symbol_counts.values())
        for sym, count in symbol_counts.items():
            if total > 0 and count / total > concentration_threshold:
                concentration_status = f"WARNING: {sym} is {count}/{total} ({count/total:.0%}) of exposure"

    # Exposure check
    if strategy_count >= max_exposure:
        concentration_status = (f"LIMIT: {strategy_count} active strategies "
                                f"(max {max_exposure})")

    # Correlation check: multiple positions in same direction on same symbol
    correlation_status = "clean"
    if len(positions) >= 2:
        direction_groups: dict[str, list] = {}
        for p in positions:
            key = f"{p.get('symbol', 'NQ')}_{p.get('direction', '?')}"
            direction_groups.setdefault(key, []).append(p.get("position_id", ""))
        correlated = {k: v for k, v in direction_groups.items() if len(v) > 1}
        if correlated:
            pairs = ", ".join(f"{k} ({len(v)} positions)" for k, v in correlated.items())
            correlation_status = f"WARNING: correlated positions: {pairs}"

    return {
        "position_count": len(positions),
        "strategy_count": strategy_count,
        "concentration_status": concentration_status,
        "correlation_status": correlation_status,
    }


def _get_pipeline_snapshot() -> dict:
    """Read strategy registry for PIPELINE section."""
    registry = REPO_ROOT / "workspace" / "quant" / "shared" / "registries" / "strategies.jsonl"
    paper_active = []
    live_active = []
    near_promotion = []
    try:
        if registry.exists():
            for line in registry.read_text().strip().splitlines():
                entry = json.loads(line)
                state = entry.get("lifecycle_state", "")
                sid = entry.get("strategy_id", "")
                if state == "PAPER_ACTIVE":
                    paper_active.append(sid)
                elif state == "LIVE_ACTIVE":
                    live_active.append(sid)
                elif state in ("PROMOTED", "PAPER_REVIEW"):
                    near_promotion.append(sid)
    except (json.JSONDecodeError, OSError):
        pass
    return {
        "paper_active_count": len(paper_active),
        "paper_active_ids": paper_active,
        "live_active_count": len(live_active),
        "live_active_ids": live_active,
        "near_promotion": near_promotion,
    }


def _get_lane_activity() -> dict[str, str]:
    """Read latest health summaries for LANE ACTIVITY section."""
    latest_dir = REPO_ROOT / "workspace" / "quant" / "shared" / "latest"
    activity = {}
    lane_packets = {
        "Atlas": "atlas_health_summary.json",
        "Fish": "fish_health_summary.json",
        "Sigma": "sigma_validation_packet.json",
        "Hermes": "hermes_health_summary.json",
    }
    for name, filename in lane_packets.items():
        path = latest_dir / filename
        if path.exists():
            try:
                data = json.loads(path.read_text())
                thesis = data.get("thesis", data.get("summary", ""))
                if thesis:
                    activity[name] = thesis[:70]
                else:
                    activity[name] = f"packet at {data.get('created_at', '?')[:19]}"
            except (json.JSONDecodeError, OSError):
                activity[name] = "(read error)"
        else:
            activity[name] = "(no recent packet)"
    return activity


def _get_tradefloor_summary() -> dict | None:
    """Read latest tradefloor packet for TRADEFLOOR section."""
    path = REPO_ROOT / "workspace" / "quant" / "shared" / "latest" / "tradefloor_tradefloor_packet.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        tier = data.get("agreement_tier", 0)
        tier_names = {0: "none", 1: "weak", 2: "strong", 3: "high_conviction", 4: "actionable"}
        return {
            "tier": tier,
            "tier_name": tier_names.get(tier, "unknown"),
            "reasoning": data.get("agreement_tier_reasoning", ""),
        }
    except (json.JSONDecodeError, OSError):
        return None


def _get_system_health() -> dict:
    """Read lane health + circuit breakers for SYSTEM HEALTH section."""
    latest_dir = REPO_ROOT / "workspace" / "quant" / "shared" / "latest"
    active = []
    silent = []
    expected = ["atlas", "fish", "hermes"]
    for lane in expected:
        path = latest_dir / f"{lane}_health_summary.json"
        if path.exists():
            active.append(lane)
        else:
            silent.append(lane)

    # Always-active services
    active.extend(["kitt", "salmon", "sigma"])

    # Circuit breakers
    cb_trips = []
    try:
        from workspace.quant.shared.circuit_breakers import check_circuit_breakers
        cb_trips = check_circuit_breakers(REPO_ROOT)
    except Exception:
        pass

    return {
        "active_lanes": sorted(active),
        "silent_lanes": silent,
        "circuit_breakers": cb_trips,
    }


def _get_rejection_summary() -> dict:
    """Read rejection scoreboards for brief enrichment (consumption plan Step 2)."""
    result: dict = {"has_data": False, "top_reasons": [], "cooldown_families": [],
                    "near_misses": [], "exploration_shifts": []}

    scoreboard_dir = REPO_ROOT / "state" / "quant" / "rejections"

    learning_path = scoreboard_dir / "learning_summary.json"
    if learning_path.exists():
        try:
            data = json.loads(learning_path.read_text())
            result["has_data"] = True
            result["top_reasons"] = data.get("top_rejection_reasons", [])[:3]
            result["near_misses"] = [
                f["family"] for f in data.get("top_near_miss_families", [])[:3]
            ]
            result["exploration_shifts"] = data.get("recommended_exploration_shifts", [])[:3]
        except (json.JSONDecodeError, OSError):
            pass

    family_path = scoreboard_dir / "family_scoreboard.json"
    if family_path.exists():
        try:
            data = json.loads(family_path.read_text())
            result["has_data"] = True
            result["cooldown_families"] = [
                f for f, info in data.get("families", {}).items()
                if info.get("cooldown")
            ]
        except (json.JSONDecodeError, OSError):
            pass

    return result


def _get_slippage_summary() -> dict:
    """Compute aggregate slippage stats from paper positions."""
    result: dict = {"has_data": False, "trade_count": 0, "mean_slippage": 0.0,
                    "max_slippage": 0.0, "total_slippage_usd": 0.0}
    try:
        con = get_connection(WAREHOUSE_PATH)
        try:
            row = con.execute("""
                SELECT COUNT(*) as n,
                       COALESCE(AVG(ABS(entry_price - requested_price)), 0) as mean_slip,
                       COALESCE(MAX(ABS(entry_price - requested_price)), 0) as max_slip,
                       COALESCE(SUM(ABS(entry_price - requested_price) * quantity * 20), 0) as total_slip_usd
                FROM kitt_paper_positions
                WHERE requested_price IS NOT NULL
            """).fetchone()
            if row and row[0] > 0:
                result["has_data"] = True
                result["trade_count"] = row[0]
                result["mean_slippage"] = round(row[1], 2)
                result["max_slippage"] = round(row[2], 2)
                result["total_slippage_usd"] = round(row[3], 2)
        finally:
            con.close()
    except Exception:
        pass
    return result


def _get_feedback_loop_status() -> dict:
    """Check if rejection feedback and calibration are flowing."""
    feedback_path = REPO_ROOT / "workspace" / "quant" / "shared" / "latest" / "rejection_feedback.json"
    atlas_consuming = feedback_path.exists()

    cal_path = REPO_ROOT / "workspace" / "quant" / "shared" / "latest" / "fish_calibration_packet.json"
    fish_calibrating = cal_path.exists()

    return {"atlas_consuming": "yes" if atlas_consuming else "no",
            "fish_calibrating": "yes" if fish_calibrating else "no"}


def _get_operator_actions(pipeline: dict, health: dict) -> list[str]:
    """Determine what needs operator attention."""
    actions = []
    if pipeline["near_promotion"]:
        actions.append(f"Review near-promotion: {', '.join(pipeline['near_promotion'])}")
    critical = [t for t in health["circuit_breakers"] if t.get("severity") == "critical"]
    for t in critical:
        actions.append(f"CRITICAL: {t['lane']} — {t['detail']}")
    return actions


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Kitt Paper Trading Cycle")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute signal but don't execute")
    parser.add_argument("--status", action="store_true",
                        help="Show current status and exit")
    args = parser.parse_args()

    if args.status:
        from kitt.paper_trader import print_status
        print_status()
        return

    decision = run_cycle(dry_run=args.dry_run)
    print(f"\n[kitt] Cycle complete: {decision['action']}")

    # Report to governor
    if not args.dry_run:
        _report_governor(decision.get("action", "unknown"))


if __name__ == "__main__":
    main()
