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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
QUANT_INFRA = THIS_DIR.parent
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
MAX_OPEN_POSITIONS = 1     # never more than 1 open paper position


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

def run_cycle(dry_run: bool = False) -> dict:
    """Execute one bounded Kitt paper-trading cycle.

    Returns a decision record dict.
    """
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

    # 3. Compute signal (needed for thesis tracking even during hold)
    signal = compute_signal(bars)
    regime = _classify_regime(signal)

    # 4. If already at max positions, decide hold or manage
    if len(open_positions) >= MAX_OPEN_POSITIONS:
        pos = open_positions[0]
        mult = 1 if pos["direction"] == "long" else -1
        unrealized = round((current_price - pos["entry_price"]) * mult, 2) if pos["entry_price"] else 0
        dist_stop = round((current_price - pos["stop_loss"]) * mult, 2) if pos["stop_loss"] else None
        dist_target = round((pos["take_profit"] - current_price) * mult, 2) if pos["take_profit"] else None
        risk = abs(pos["entry_price"] - pos["stop_loss"]) if pos["entry_price"] and pos["stop_loss"] else None
        reward = abs(pos["take_profit"] - pos["entry_price"]) if pos["take_profit"] and pos["entry_price"] else None
        rr = round(reward / risk, 2) if risk and reward and risk > 0 else None

        # Thesis change detection
        prev_state = _load_thesis_state()
        current_state = {
            "regime": regime,
            "signal_direction": signal["signal"],
            "atr": signal.get("atr"),
            "deviation": signal.get("deviation"),
            "position_id": pos["position_id"],
            "unrealized_pts": unrealized,
            "updated_at": _now(),
        }

        thesis_change = _detect_thesis_change(prev_state, current_state, True)
        if thesis_change and not dry_run:
            emit_event(
                "kitt", "thesis_changed",
                side=pos["direction"],
                entry=pos["entry_price"],
                stop=pos["stop_loss"],
                target=pos["take_profit"],
                current_mark=current_price,
                position_id=pos["position_id"],
                reason=thesis_change,
                source_packet="kitt_cycle",
                extra={"regime": regime, "signal": signal["signal"]},
            )
            cycle_event = "thesis_changed"
            print(f"[kitt] Thesis change: {thesis_change}")

        _save_thesis_state(current_state)

        reason = (f"Holding {pos['direction']} NQ @ {pos['entry_price']}, "
                  f"mark={current_price:.2f}, unrealized={unrealized:.2f} pts")
        return _record_decision("hold", reason, reason, dry_run=dry_run,
                                market_context=_market_context(bars),
                                position_id=pos["position_id"],
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

    pos_id = open_position(direction, entry, stop, target, reason)
    print(f"[kitt] Opened: {pos_id}")

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
    """Write human-readable Kitt cycle brief with thesis and change tracking."""
    now = datetime.now(timezone.utc)
    perf = status["performance"]

    md = f"""# Kitt Cycle Brief — {now.strftime('%Y-%m-%d %H:%M UTC')}

## Decision
**{action}** — {reasoning}

## Market Context
{market_context}
"""
    if regime:
        md += f"- **Regime**: {regime}\n"
    if signal:
        md += (f"- **Signal**: {signal.get('signal', 'n/a')} | "
               f"ATR={signal.get('atr', 'n/a')} | "
               f"Deviation={signal.get('deviation', 'n/a')}\n")

    if cycle_event:
        md += f"\n> **Event emitted this cycle**: `{cycle_event}`\n"

    md += "\n## Open Positions\n"
    if status["open_positions"]:
        for p in status["open_positions"]:
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

            md += (f"- **{p['position_id']}**: {direction} NQ "
                   f"@ {entry} → mark {mark}\n")
            md += f"  - SL={stop} | TP={target} | R:R={rr}\n"
            md += f"  - Unrealized: {unrealized:+.2f} pts (${unrealized * 20:+.2f})\n"
            if dist_stop is not None:
                md += f"  - Distance to stop: {dist_stop:.2f} pts | to target: {dist_target:.2f} pts\n"
            if p.get("reasoning"):
                md += f"  - **Thesis**: {p['reasoning'][:120]}\n"
            if stop:
                md += f"  - **Invalidation**: thesis fails if NQ reaches {stop}\n"
    else:
        md += "- None\n"

    md += f"""
## Paper Track Record
- Trades: {perf['total_trades']} | Wins: {perf['wins']} | Losses: {perf['losses']}
- Total PnL: ${perf['total_pnl']:.2f} | Avg: ${perf['avg_pnl']:.2f}

## Recent Decisions
"""
    for d in status["recent_decisions"][:3]:
        md += f"- [{d['at'][:19]}] **{d['action']}**: {d['reasoning'][:80]}\n"

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


if __name__ == "__main__":
    main()
