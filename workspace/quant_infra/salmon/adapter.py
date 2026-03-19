#!/usr/bin/env python3
"""Salmon Adapter — scenario/simulation feeder for the Fish lane.

Fish is the lane (the operator-facing identity). This module is the Salmon
Adapter: the quant_infra implementation that generates scenario data and
writes it into Fish's packet and research paths.

Consumes Kitt packet + DuckDB warehouse context.
Produces scenario artifacts answering:
- What invalidates Kitt's current paper position?
- What conditions improve or worsen expected outcome?
- What scenario risk should Sigma validate later?
- What should the operator watch next?

Usage:
    .venv/bin/python3 workspace/quant_infra/salmon/adapter.py
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

QUANT_INFRA = Path(__file__).resolve().parent.parent
REPO_ROOT = QUANT_INFRA.parent.parent
sys.path.insert(0, str(QUANT_INFRA))
sys.path.insert(0, str(REPO_ROOT))

import duckdb

from warehouse.loader import get_connection, insert_scenario
from packets.writer import write_packet, read_packet

THIS_DIR = Path(__file__).resolve().parent
WAREHOUSE_PATH = QUANT_INFRA / "warehouse" / "quant.duckdb"
SCENARIOS_DIR = QUANT_INFRA / "research" / "fish_scenarios"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return f"fsc-{uuid.uuid4().hex[:12]}"


def _get_market_context(con: duckdb.DuckDBPyConnection) -> dict:
    """Get latest market context from DuckDB."""
    try:
        row = con.execute("""
            SELECT bar_date, close, vix, high, low
            FROM ohlcv_daily WHERE symbol = 'NQ'
            ORDER BY bar_date DESC LIMIT 1
        """).fetchone()
        if row:
            return {
                "last_date": str(row[0]),
                "last_close": row[1],
                "vix": row[2],
                "last_high": row[3],
                "last_low": row[4],
            }
    except Exception:
        pass
    return {"last_close": None, "vix": None}


def _get_recent_range(con: duckdb.DuckDBPyConnection, days: int = 5) -> dict:
    """Get recent price range statistics."""
    try:
        row = con.execute(f"""
            SELECT MAX(high), MIN(low), AVG(close), STDDEV(close)
            FROM (SELECT high, low, close FROM ohlcv_daily
                  WHERE symbol = 'NQ' ORDER BY bar_date DESC LIMIT {days})
        """).fetchone()
        if row:
            return {
                "high_5d": row[0],
                "low_5d": row[1],
                "avg_close_5d": row[2],
                "stddev_5d": row[3],
            }
    except Exception:
        pass
    return {}


def _load_regime_guidance() -> dict:
    """Read rejection regime feedback for scenario probability weighting.

    Returns dict of {regime_tag: {rejection_count, dominant_reason, affected_families}}.
    Per consumption plan Step 3: Fish reads rejection_feedback.json to bias
    scenario generation toward regimes with high rejection rates.
    """
    path = REPO_ROOT / "workspace" / "quant" / "shared" / "latest" / "rejection_feedback.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data.get("fish", {}).get("regimes", {})
    except (json.JSONDecodeError, OSError):
        return {}


def _apply_regime_bias(scenarios: list[dict], regime_guidance: dict) -> list[dict]:
    """Adjust scenario probabilities based on rejection regime feedback.

    Regimes with higher rejection counts get probability boosts on negative
    scenarios (more risk awareness). This biases Fish toward modeling the
    failure modes that the system actually hits.
    """
    if not regime_guidance:
        return scenarios

    # Find regimes with significant rejection counts
    high_rejection_regimes = {
        tag for tag, info in regime_guidance.items()
        if info.get("rejection_count", 0) >= 3
    }
    if not high_rejection_regimes:
        return scenarios

    for scenario in scenarios:
        stype = scenario.get("scenario_type", "")
        # Boost probability of negative/risk scenarios when regime feedback
        # indicates high rejection rates (strategies keep failing here)
        if scenario.get("impact") == "negative" and stype in (
            "stop_out", "failed_breakout", "gap_risk", "vol_expansion", "invalidation"
        ):
            # Small probability boost: +0.05 per high-rejection regime
            boost = min(0.10, 0.05 * len(high_rejection_regimes))
            scenario["probability"] = min(0.60, scenario["probability"] + boost)

    return scenarios


def generate_scenarios_for_position(
    con: duckdb.DuckDBPyConnection,
    position: dict,
    market: dict,
    range_stats: dict,
) -> list[dict]:
    """Generate standard scenario set for a Kitt paper position."""
    scenarios = []
    entry = position["entry_price"]
    direction = position["direction"]
    stop = position.get("stop_loss")
    target = position.get("take_profit")
    last_close = market.get("last_close") or entry
    vix = market.get("vix") or 20
    stddev = range_stats.get("stddev_5d") or (entry * 0.01)

    # 1. Bull continuation
    if direction == "long":
        bull_target = entry + 2 * stddev
        scenarios.append({
            "scenario_id": _uid(),
            "created_at": _now(),
            "scenario_type": "bull_continuation",
            "symbol": "NQ",
            "description": (
                f"NQ continues higher through {bull_target:.0f}. "
                f"Momentum sustains above entry {entry:.0f}. "
                f"VIX compression below {vix:.1f} supports rally."
            ),
            "probability": 0.35 if vix < 25 else 0.25,
            "impact": "positive",
            "target_price": bull_target,
            "invalidation_price": stop or (entry - stddev),
            "timeframe": "1D",
            "kitt_position_id": position["position_id"],
        })
    else:
        bear_target = entry - 2 * stddev
        scenarios.append({
            "scenario_id": _uid(),
            "created_at": _now(),
            "scenario_type": "bear_continuation",
            "symbol": "NQ",
            "description": (
                f"NQ continues lower through {bear_target:.0f}. "
                f"Selling pressure sustains below entry {entry:.0f}."
            ),
            "probability": 0.35 if vix > 25 else 0.25,
            "impact": "positive",
            "target_price": bear_target,
            "invalidation_price": stop or (entry + stddev),
            "timeframe": "1D",
            "kitt_position_id": position["position_id"],
        })

    # 2. Failed breakout / snapback
    snapback_level = entry - stddev if direction == "long" else entry + stddev
    scenarios.append({
        "scenario_id": _uid(),
        "created_at": _now(),
        "scenario_type": "failed_breakout",
        "symbol": "NQ",
        "description": (
            f"NQ reverses from {last_close:.0f} back toward {snapback_level:.0f}. "
            f"Initial move fails, mean reversion dominates."
        ),
        "probability": 0.30,
        "impact": "negative",
        "target_price": snapback_level,
        "invalidation_price": target or (entry + 2 * stddev if direction == "long" else entry - 2 * stddev),
        "timeframe": "1D",
        "kitt_position_id": position["position_id"],
    })

    # 3. Volatility expansion
    vol_target = entry + 3 * stddev if direction == "long" else entry - 3 * stddev
    scenarios.append({
        "scenario_id": _uid(),
        "created_at": _now(),
        "scenario_type": "vol_expansion",
        "symbol": "NQ",
        "description": (
            f"VIX spikes from {vix:.1f} above 30. NQ sees expanded range. "
            f"Position at {entry:.0f} faces amplified moves in both directions."
        ),
        "probability": 0.15 if vix < 25 else 0.30,
        "impact": "negative" if direction == "long" else "neutral",
        "target_price": vol_target,
        "invalidation_price": None,
        "timeframe": "1W",
        "kitt_position_id": position["position_id"],
    })

    # 4. Overnight gap risk
    gap_size = stddev * 1.5
    gap_price = entry - gap_size if direction == "long" else entry + gap_size
    scenarios.append({
        "scenario_id": _uid(),
        "created_at": _now(),
        "scenario_type": "gap_risk",
        "symbol": "NQ",
        "description": (
            f"Overnight gap {'down' if direction == 'long' else 'up'} "
            f"to {gap_price:.0f} ({gap_size:.0f} pts). "
            f"Stop at {stop or 'none'} may be gapped through."
        ),
        "probability": 0.10,
        "impact": "negative",
        "target_price": gap_price,
        "invalidation_price": None,
        "timeframe": "1D",
        "kitt_position_id": position["position_id"],
    })

    # 5. Stop-out / downside case
    if stop:
        scenarios.append({
            "scenario_id": _uid(),
            "created_at": _now(),
            "scenario_type": "stop_out",
            "symbol": "NQ",
            "description": (
                f"NQ reaches stop at {stop:.0f}. "
                f"Position closed for loss of {abs(entry - stop) * 20:.0f} per contract."
            ),
            "probability": 0.25,
            "impact": "negative",
            "target_price": stop,
            "invalidation_price": target,
            "timeframe": "1D",
            "kitt_position_id": position["position_id"],
        })

    # 6. Invalidation case
    invalidation = stop or (entry - 1.5 * stddev if direction == "long" else entry + 1.5 * stddev)
    scenarios.append({
        "scenario_id": _uid(),
        "created_at": _now(),
        "scenario_type": "invalidation",
        "symbol": "NQ",
        "description": (
            f"Trade thesis invalidated if NQ breaches {invalidation:.0f}. "
            f"Original reasoning no longer holds. Exit recommended."
        ),
        "probability": 0.20,
        "impact": "negative",
        "target_price": invalidation,
        "invalidation_price": None,
        "timeframe": "1D",
        "kitt_position_id": position["position_id"],
    })

    return scenarios


def generate_baseline_scenarios(con: duckdb.DuckDBPyConnection, market: dict, range_stats: dict) -> list[dict]:
    """Generate baseline scenarios when no positions are open."""
    vix = market.get("vix") or 20
    last_close = market.get("last_close") or 24500
    stddev = range_stats.get("stddev_5d") or (last_close * 0.01)

    return [
        {
            "scenario_id": _uid(),
            "created_at": _now(),
            "scenario_type": "bull_continuation",
            "symbol": "NQ",
            "description": f"NQ pushes higher above {last_close + stddev:.0f}. Momentum regime.",
            "probability": 0.30,
            "impact": "neutral",
            "target_price": last_close + 2 * stddev,
            "invalidation_price": last_close - stddev,
            "timeframe": "1D",
            "kitt_position_id": None,
        },
        {
            "scenario_id": _uid(),
            "created_at": _now(),
            "scenario_type": "vol_expansion",
            "symbol": "NQ",
            "description": f"VIX rises above {vix + 5:.0f}, NQ range expands significantly.",
            "probability": 0.15 if vix < 25 else 0.30,
            "impact": "negative",
            "target_price": None,
            "invalidation_price": None,
            "timeframe": "1W",
            "kitt_position_id": None,
        },
        {
            "scenario_id": _uid(),
            "created_at": _now(),
            "scenario_type": "failed_breakout",
            "symbol": "NQ",
            "description": f"NQ rejects at {last_close + stddev:.0f}, mean-reverts to {last_close - stddev:.0f}.",
            "probability": 0.25,
            "impact": "neutral",
            "target_price": last_close - stddev,
            "invalidation_price": last_close + 2 * stddev,
            "timeframe": "1D",
            "kitt_position_id": None,
        },
    ]


def run_scenario_generation() -> list[dict]:
    """Main scenario generation entry point."""
    con = get_connection(WAREHOUSE_PATH)
    try:
        market = _get_market_context(con)
        range_stats = _get_recent_range(con)
        all_scenarios = []

        # Load rejection regime guidance for probability biasing
        regime_guidance = _load_regime_guidance()
        if regime_guidance:
            print(f"[salmon] Loaded regime guidance: {len(regime_guidance)} regime(s) with rejection data")

        # Get open Kitt positions
        positions = con.execute("""
            SELECT position_id, direction, entry_price, stop_loss, take_profit
            FROM kitt_paper_positions WHERE status = 'open'
        """).fetchall()

        if positions:
            for pos in positions:
                pos_dict = {
                    "position_id": pos[0],
                    "direction": pos[1],
                    "entry_price": pos[2],
                    "stop_loss": pos[3],
                    "take_profit": pos[4],
                }
                scenarios = generate_scenarios_for_position(con, pos_dict, market, range_stats)
                all_scenarios.extend(scenarios)
                print(f"[salmon] Generated {len(scenarios)} scenarios for position {pos[0]}")
        else:
            all_scenarios = generate_baseline_scenarios(con, market, range_stats)
            print(f"[salmon] Generated {len(all_scenarios)} baseline scenarios (no open positions)")

        # Apply regime-aware probability bias from rejection feedback
        all_scenarios = _apply_regime_bias(all_scenarios, regime_guidance)

        # Store in DuckDB
        for s in all_scenarios:
            try:
                insert_scenario(con, s)
            except Exception as e:
                print(f"[salmon] WARN: failed to store scenario {s['scenario_id']}: {e}")

        # Write Fish packet
        _write_fish_packet(all_scenarios, market)

        # Write research artifact
        _write_scenario_artifact(all_scenarios, market, positions)

        return all_scenarios

    finally:
        con.close()


def _write_fish_packet(scenarios: list[dict], market: dict) -> None:
    """Write the Fish scenario packet."""
    scenario_summaries = [
        {
            "type": s["scenario_type"],
            "probability": s["probability"],
            "impact": s["impact"],
            "target": s.get("target_price"),
            "invalidation": s.get("invalidation_price"),
            "position_id": s.get("kitt_position_id"),
        }
        for s in scenarios
    ]

    write_packet(
        lane="fish",
        packet_type="scenario",
        summary=f"Fish: {len(scenarios)} scenarios generated | NQ={market.get('last_close')} VIX={market.get('vix')}",
        data={
            "scenario_count": len(scenarios),
            "scenarios": scenario_summaries,
            "market_context": market,
        },
        upstream=["kitt_quant"],
        source_module="salmon_adapter",
        confidence=0.5,
    )


def _write_scenario_artifact(scenarios: list[dict], market: dict, positions: list) -> None:
    """Write human-readable scenario summary."""
    now = datetime.now(timezone.utc)

    md = f"""# Fish Scenario Report — {now.strftime('%Y-%m-%d %H:%M UTC')}

## Market Context
- **NQ Close**: {market.get('last_close')}
- **VIX**: {market.get('vix')}
- **Open Positions**: {len(positions)}

## Scenarios

"""
    for s in scenarios:
        md += f"""### {s['scenario_type'].replace('_', ' ').title()}
- **Probability**: {s['probability']:.0%}
- **Impact**: {s['impact']}
- **Target**: {s.get('target_price', 'N/A')}
- **Invalidation**: {s.get('invalidation_price', 'N/A')}
- {s['description']}

"""

    md += """## Operator Watch List
"""
    high_prob = [s for s in scenarios if s["probability"] >= 0.25]
    for s in high_prob:
        md += f"- **{s['scenario_type']}** ({s['probability']:.0%}): watch for {s.get('target_price', 'N/A')}\n"

    negative = [s for s in scenarios if s["impact"] == "negative"]
    if negative:
        md += f"\n**Risk scenarios**: {len(negative)} scenarios with negative impact.\n"

    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    (SCENARIOS_DIR / "latest.md").write_text(md)
    ts = now.strftime("%Y%m%dT%H%M%S")
    (SCENARIOS_DIR / f"scenario_{ts}.md").write_text(md)
    print(f"[salmon] Wrote scenario artifact → {SCENARIOS_DIR / 'latest.md'}")


def _check_governor() -> bool:
    """Check if governor has paused the fish/salmon lane."""
    try:
        from workspace.quant.shared.governor import get_lane_params
        params = get_lane_params(REPO_ROOT, "fish")
        if params.get("paused"):
            print("[salmon] Governor: fish lane is PAUSED — skipping cycle")
            return False
    except Exception as exc:
        print(f"[salmon] Governor check failed (running anyway): {exc}")
    return True


def _report_governor(scenario_count: int) -> None:
    """Report cycle outcome to governor."""
    try:
        from workspace.quant.shared.governor import evaluate_cycle
        health = 0.8 if scenario_count > 0 else 0.3
        usefulness = 0.6 if scenario_count > 0 else 0.2
        gov_action, gov_reason = evaluate_cycle(
            REPO_ROOT, "fish",
            usefulness_score=usefulness,
            efficiency_score=0.7,
            health_score=health,
            confidence_score=0.5,
        )
        if gov_action != "hold":
            print(f"[salmon] Governor: {gov_action} — {gov_reason}")
    except Exception as exc:
        print(f"[salmon] Governor report failed: {exc}")


def main():
    # Governor gate
    if not _check_governor():
        return

    print("[salmon] Running scenario generation for Fish lane...")
    scenarios = run_scenario_generation()
    print(f"[salmon] Generated {len(scenarios)} scenarios total.")

    # Report to governor
    _report_governor(len(scenarios))


if __name__ == "__main__":
    main()
