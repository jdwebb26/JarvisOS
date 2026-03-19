#!/usr/bin/env python3
"""Operator Truth Pack — unified runtime state surface.

Combines all operational data into a single view:
  1. POSITIONS — open positions with enriched metrics
  2. EXPOSURE — total exposure, concentration, correlation
  3. APPROVALS — pending paper/live approvals, LIVE_QUEUED strategies
  4. REJECTION INTELLIGENCE — scoreboards, cooldown, near-misses, learning
  5. SYSTEM HEALTH — lane status, circuit breakers, handshake chain
  6. SLIPPAGE — aggregate fill quality stats
  7. FEEDBACK LOOPS — Sigma→Atlas, Fish calibration, regime guidance
  8. FISH SCENARIOS — active scenario summary

Outputs:
  - JSON truth pack (machine-readable)
  - Markdown operator surface (human-readable)

Usage:
    python3 workspace/quant_infra/jarvis/truth_pack.py
    python3 workspace/quant_infra/jarvis/truth_pack.py --json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

QUANT_INFRA = Path(__file__).resolve().parent.parent
REPO_ROOT = QUANT_INFRA.parent.parent
sys.path.insert(0, str(QUANT_INFRA))
sys.path.insert(0, str(REPO_ROOT))

WAREHOUSE_PATH = QUANT_INFRA / "warehouse" / "quant.duckdb"
HANDSHAKE_LOG = QUANT_INFRA / "logs" / "handshake"
TRUTH_PACK_DIR = QUANT_INFRA / "research" / "truth_pack"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_positions() -> dict:
    """Open positions with enriched metrics."""
    try:
        import duckdb
        con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
        try:
            rows = con.execute("""
                SELECT position_id, opened_at, symbol, direction, quantity,
                       entry_price, stop_loss, take_profit, mark_price,
                       marked_at, reasoning, requested_price, status
                FROM kitt_paper_positions WHERE status = 'open'
                ORDER BY opened_at DESC
            """).fetchall()

            positions = []
            for r in rows:
                pos_id, opened_at, symbol, direction, qty, entry, stop, target, mark, marked_at, reasoning, req_price, status = r
                mark = mark or entry
                mult = 1 if direction == "long" else -1
                unrealized = round((mark - entry) * mult, 2) if entry else 0
                risk = abs(entry - stop) if entry and stop else None
                reward = abs(target - entry) if entry and target else None
                rr = round(reward / risk, 2) if risk and reward and risk > 0 else None
                dist_stop = round((mark - stop) * mult, 2) if mark and stop else None
                dist_target = round((target - mark) * mult, 2) if mark and target else None
                slippage = round(abs(entry - req_price), 2) if req_price else None

                positions.append({
                    "position_id": pos_id,
                    "opened_at": str(opened_at),
                    "symbol": symbol,
                    "direction": direction,
                    "quantity": qty,
                    "entry_price": entry,
                    "requested_price": req_price,
                    "slippage_pts": slippage,
                    "stop_loss": stop,
                    "take_profit": target,
                    "mark_price": mark,
                    "unrealized_pnl_pts": unrealized,
                    "unrealized_pnl_usd": round(unrealized * 20, 2),
                    "reward_risk": rr,
                    "dist_to_stop_pts": dist_stop,
                    "dist_to_target_pts": dist_target,
                    "reasoning": reasoning or "",
                })

            # Performance
            perf = con.execute("""
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE status = 'open') as open_count,
                       COUNT(*) FILTER (WHERE pnl > 0) as wins,
                       COUNT(*) FILTER (WHERE pnl < 0) as losses,
                       COUNT(*) FILTER (WHERE pnl = 0 AND status != 'open') as scratches,
                       COALESCE(ROUND(SUM(pnl), 2), 0) as total_pnl,
                       COALESCE(ROUND(AVG(pnl) FILTER (WHERE pnl IS NOT NULL), 2), 0) as avg_pnl,
                       COALESCE(ROUND(MAX(pnl) FILTER (WHERE pnl IS NOT NULL), 2), 0) as best_trade,
                       COALESCE(ROUND(MIN(pnl) FILTER (WHERE pnl IS NOT NULL), 2), 0) as worst_trade
                FROM kitt_paper_positions
            """).fetchone()

            return {
                "open_positions": positions,
                "performance": {
                    "total_trades": perf[0], "open": perf[1],
                    "wins": perf[2], "losses": perf[3], "scratches": perf[4],
                    "total_pnl": perf[5], "avg_pnl": perf[6],
                    "best_trade": perf[7], "worst_trade": perf[8],
                    "win_rate": round(perf[2] / max(perf[2] + perf[3], 1) * 100, 1),
                },
            }
        finally:
            con.close()
    except Exception as exc:
        return {"open_positions": [], "performance": {}, "error": str(exc)}


def _build_exposure() -> dict:
    """Total exposure, concentration, and correlation analysis."""
    try:
        import duckdb
        con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
        try:
            positions = con.execute("""
                SELECT position_id, symbol, direction, quantity, entry_price, mark_price
                FROM kitt_paper_positions WHERE status = 'open'
            """).fetchall()

            # Strategy registry
            registry = REPO_ROOT / "workspace" / "quant" / "shared" / "registries" / "strategies.jsonl"
            active_strategies = []
            all_strategies = []
            try:
                if registry.exists():
                    for line in registry.read_text().strip().splitlines():
                        entry = json.loads(line)
                        all_strategies.append(entry)
                        if entry.get("lifecycle_state") in ("PAPER_ACTIVE", "LIVE_ACTIVE"):
                            active_strategies.append(entry)
            except (json.JSONDecodeError, OSError):
                pass

            # Risk limits
            risk_path = REPO_ROOT / "workspace" / "quant" / "shared" / "config" / "risk_limits.json"
            try:
                limits = json.loads(risk_path.read_text()) if risk_path.exists() else {}
            except (json.JSONDecodeError, OSError):
                limits = {}

            portfolio_limits = limits.get("portfolio", {})
            max_exposure = portfolio_limits.get("max_total_exposure", 4)

            # Compute exposure metrics
            total_notional = 0
            symbol_exposure: dict[str, float] = {}
            direction_exposure: dict[str, int] = {"long": 0, "short": 0}
            for pos_id, symbol, direction, qty, entry, mark in positions:
                mark = mark or entry
                notional = abs(mark * qty * 20)  # NQ $20/point
                total_notional += notional
                symbol_exposure[symbol] = symbol_exposure.get(symbol, 0) + notional
                direction_exposure[direction] = direction_exposure.get(direction, 0) + qty

            # Concentration
            concentration_warnings = []
            if symbol_exposure:
                for sym, notional in symbol_exposure.items():
                    pct = notional / total_notional if total_notional > 0 else 0
                    if pct > 0.6:
                        concentration_warnings.append(
                            f"{sym}: {pct:.0%} of total exposure"
                        )

            # Correlation: same symbol + same direction
            correlation_warnings = []
            if len(positions) >= 2:
                groups: dict[str, list[str]] = {}
                for pos_id, symbol, direction, *_ in positions:
                    key = f"{symbol}_{direction}"
                    groups.setdefault(key, []).append(pos_id)
                for key, pids in groups.items():
                    if len(pids) > 1:
                        correlation_warnings.append(
                            f"{key}: {len(pids)} positions ({', '.join(pids[:3])})"
                        )

            return {
                "open_position_count": len(positions),
                "active_strategy_count": len(active_strategies),
                "max_exposure_limit": max_exposure,
                "total_notional_usd": round(total_notional, 2),
                "net_direction": direction_exposure,
                "symbol_exposure": {
                    sym: round(n, 2) for sym, n in symbol_exposure.items()
                },
                "concentration_warnings": concentration_warnings,
                "correlation_warnings": correlation_warnings,
                "exposure_status": (
                    "LIMIT" if len(active_strategies) >= max_exposure
                    else "WARNING" if concentration_warnings or correlation_warnings
                    else "CLEAN"
                ),
            }
        finally:
            con.close()
    except Exception as exc:
        return {"error": str(exc)}


def _build_approvals() -> dict:
    """Pending approvals and LIVE_QUEUED strategies."""
    result: dict = {
        "pending_paper": [],
        "pending_live": [],
        "live_queued_strategies": [],
        "total_pending": 0,
    }
    try:
        from workspace.quant.shared.registries.approval_registry import load_all_approvals
        from workspace.quant.shared.registries.strategy_registry import get_strategies_by_state
        from workspace.quant.shared.live_approval_state import resolve_live_approval_state

        approvals = load_all_approvals(REPO_ROOT)

        # Pending paper approvals (not revoked)
        paper = [a for a in approvals
                 if a.approval_type == "paper_trade" and not a.revoked]
        for a in paper:
            result["pending_paper"].append({
                "approval_ref": a.approval_ref,
                "strategy_id": a.strategy_id,
                "created_at": str(a.created_at),
            })

        # Pending live approvals
        live = [a for a in approvals
                if a.approval_type == "live_trade" and not a.revoked]
        for a in live:
            result["pending_live"].append({
                "approval_ref": a.approval_ref,
                "strategy_id": a.strategy_id,
                "created_at": str(a.created_at),
            })

        # LIVE_QUEUED strategies
        try:
            lq_strategies = get_strategies_by_state(REPO_ROOT, "LIVE_QUEUED")
            for s in lq_strategies:
                sid = s.strategy_id if hasattr(s, "strategy_id") else s.get("strategy_id", "")
                la_state = resolve_live_approval_state(sid, approvals)
                result["live_queued_strategies"].append({
                    "strategy_id": sid,
                    "approval_state": la_state.get("state", "unknown"),
                    "label": la_state.get("label", ""),
                    "action": la_state.get("action", ""),
                })
        except Exception:
            pass

        result["total_pending"] = len(paper) + len(live)

    except Exception as exc:
        result["error"] = str(exc)

    return result


def _build_rejection_intelligence() -> dict:
    """Rejection scoreboards, cooldown families, near-misses, learning."""
    result: dict = {
        "has_data": False,
        "total_rejections": 0,
        "cooldown_families": [],
        "near_miss_families": [],
        "top_reasons": [],
        "exploration_shifts": [],
        "regime_blind_spots": [],
        "families": {},
    }

    scoreboard_dir = REPO_ROOT / "state" / "quant" / "rejections"

    # Learning summary
    learning_path = scoreboard_dir / "learning_summary.json"
    if learning_path.exists():
        try:
            data = json.loads(learning_path.read_text())
            result["has_data"] = True
            result["total_rejections"] = data.get("total_rejections", 0)
            result["top_reasons"] = data.get("top_rejection_reasons", [])[:5]
            result["near_miss_families"] = [
                f["family"] for f in data.get("top_near_miss_families", [])[:5]
            ]
            result["exploration_shifts"] = data.get("recommended_exploration_shifts", [])[:5]
            result["regime_blind_spots"] = data.get("top_regime_blind_spots", [])[:5]
        except (json.JSONDecodeError, OSError):
            pass

    # Family scoreboard
    family_path = scoreboard_dir / "family_scoreboard.json"
    if family_path.exists():
        try:
            data = json.loads(family_path.read_text())
            result["has_data"] = True
            families = data.get("families", {})
            result["families"] = families
            result["cooldown_families"] = [
                f for f, info in families.items() if info.get("cooldown")
            ]
        except (json.JSONDecodeError, OSError):
            pass

    # Regime scoreboard
    regime_path = scoreboard_dir / "regime_scoreboard.json"
    if regime_path.exists():
        try:
            data = json.loads(regime_path.read_text())
            result["regimes"] = data.get("regimes", {})
        except (json.JSONDecodeError, OSError):
            pass

    return result


def _build_system_health() -> dict:
    """Lane status, circuit breakers, handshake chain."""
    health: dict = {
        "active_lanes": [],
        "silent_lanes": [],
        "circuit_breakers": [],
        "handshake": None,
        "governor_paused_lanes": [],
    }

    # Lane health
    latest_dir = REPO_ROOT / "workspace" / "quant" / "shared" / "latest"
    for lane in ["atlas", "fish", "hermes"]:
        path = latest_dir / f"{lane}_health_summary.json"
        if path.exists():
            health["active_lanes"].append(lane)
        else:
            health["silent_lanes"].append(lane)
    health["active_lanes"].extend(["kitt", "salmon", "sigma"])

    # Circuit breakers
    try:
        from workspace.quant.shared.circuit_breakers import check_circuit_breakers
        health["circuit_breakers"] = check_circuit_breakers(REPO_ROOT)
    except Exception:
        pass

    # Handshake chain
    latest_path = HANDSHAKE_LOG / "latest.json"
    if latest_path.exists():
        try:
            data = json.loads(latest_path.read_text())
            health["handshake"] = {
                "started_at": data.get("started_at", "?")[:19],
                "completed_at": data.get("completed_at", "?")[:19],
                "steps": {
                    k: v.get("status", "?")
                    for k, v in data.get("steps", {}).items()
                },
            }
        except (json.JSONDecodeError, OSError):
            pass

    # Governor paused lanes
    try:
        from workspace.quant.shared.governor import get_lane_params
        for lane in ["kitt", "fish", "atlas", "sigma"]:
            params = get_lane_params(REPO_ROOT, lane)
            if params.get("paused"):
                health["governor_paused_lanes"].append(lane)
    except Exception:
        pass

    return health


def _build_slippage() -> dict:
    """Aggregate fill quality stats."""
    result: dict = {
        "has_data": False,
        "trade_count": 0,
        "mean_slippage_pts": 0.0,
        "max_slippage_pts": 0.0,
        "total_slippage_usd": 0.0,
        "zero_slippage_pct": 0.0,
    }
    try:
        import duckdb
        con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
        try:
            row = con.execute("""
                SELECT COUNT(*) as n,
                       COALESCE(AVG(ABS(entry_price - requested_price)), 0),
                       COALESCE(MAX(ABS(entry_price - requested_price)), 0),
                       COALESCE(SUM(ABS(entry_price - requested_price) * quantity * 20), 0),
                       COALESCE(COUNT(*) FILTER (WHERE entry_price = requested_price), 0)
                FROM kitt_paper_positions
                WHERE requested_price IS NOT NULL
            """).fetchone()
            if row and row[0] > 0:
                result["has_data"] = True
                result["trade_count"] = row[0]
                result["mean_slippage_pts"] = round(row[1], 2)
                result["max_slippage_pts"] = round(row[2], 2)
                result["total_slippage_usd"] = round(row[3], 2)
                result["zero_slippage_pct"] = round(row[4] / row[0] * 100, 1)
        finally:
            con.close()
    except Exception:
        pass
    return result


def _build_feedback_loops() -> dict:
    """Feedback loop status: Sigma→Atlas, Fish calibration, regime guidance."""
    result: dict = {
        "sigma_atlas_loop": "unknown",
        "fish_calibration": "unknown",
        "regime_guidance_active": False,
        "rejection_feedback_exported": False,
    }

    # Sigma→Atlas: check for recent feedback and proposal packets
    from packets.writer import read_packet
    sigma_pkt = read_packet("sigma")
    atlas_pkt = read_packet("atlas")
    result["sigma_atlas_loop"] = (
        "active" if sigma_pkt and atlas_pkt else
        "sigma_only" if sigma_pkt else
        "inactive"
    )

    # Fish calibration
    try:
        from workspace.quant.fish.scenario_lane import build_calibration_state
        cal = build_calibration_state(REPO_ROOT)
        result["fish_calibration"] = {
            "total_calibrations": cal.get("total_calibrations", 0),
            "trend": cal.get("trend", "unknown"),
            "track_record_confidence": round(cal.get("track_record_confidence", 0.5), 2),
            "direction_hit_rate": cal.get("direction_hit_rate"),
            "streak": cal.get("streak", 0),
        }
    except Exception:
        pass

    # Regime guidance
    feedback_path = REPO_ROOT / "workspace" / "quant" / "shared" / "latest" / "rejection_feedback.json"
    if feedback_path.exists():
        result["rejection_feedback_exported"] = True
        try:
            data = json.loads(feedback_path.read_text())
            fish_regimes = data.get("fish", {}).get("regimes", {})
            result["regime_guidance_active"] = len(fish_regimes) > 0
        except (json.JSONDecodeError, OSError):
            pass

    return result


def _build_scenarios() -> dict:
    """Active Fish scenario summary."""
    fish_pkt = None
    try:
        from packets.writer import read_packet
        fish_pkt = read_packet("fish")
    except Exception:
        pass

    if not fish_pkt:
        return {"count": 0, "scenarios": []}

    data = fish_pkt.get("data", {})
    scenarios = data.get("scenarios", [])
    negative = [s for s in scenarios if s.get("impact") == "negative"]
    high_prob = [s for s in scenarios if (s.get("probability") or 0) >= 0.25]

    return {
        "count": len(scenarios),
        "negative_count": len(negative),
        "high_prob_count": len(high_prob),
        "top_risks": [
            {"type": s["type"], "probability": s["probability"], "impact": s["impact"]}
            for s in sorted(negative, key=lambda x: -(x.get("probability") or 0))[:3]
        ],
        "timestamp": fish_pkt.get("timestamp", "?")[:19],
    }


# ---------------------------------------------------------------------------
# Truth pack assembly
# ---------------------------------------------------------------------------

def build_truth_pack() -> dict:
    """Assemble the complete operator truth pack."""
    now = datetime.now(timezone.utc)
    return {
        "generated_at": now.isoformat(),
        "positions": _build_positions(),
        "exposure": _build_exposure(),
        "approvals": _build_approvals(),
        "rejection_intelligence": _build_rejection_intelligence(),
        "system_health": _build_system_health(),
        "slippage": _build_slippage(),
        "feedback_loops": _build_feedback_loops(),
        "scenarios": _build_scenarios(),
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_truth_pack(pack: dict) -> str:
    """Render truth pack as operator-readable Markdown."""
    now = pack.get("generated_at", "?")[:19]
    lines: list[str] = []
    lines.append(f"{'=' * 72}")
    lines.append(f"  OPERATOR TRUTH PACK — {now}")
    lines.append(f"{'=' * 72}")

    # 1. POSITIONS
    pos = pack.get("positions", {})
    perf = pos.get("performance", {})
    lines.append("")
    lines.append("POSITIONS")
    open_positions = pos.get("open_positions", [])
    if open_positions:
        for p in open_positions:
            lines.append(
                f"  {p['position_id']}: {p['direction']} {p['symbol']} "
                f"@ {p['entry_price']} -> mark {p['mark_price']}"
            )
            lines.append(
                f"    SL={p['stop_loss']} | TP={p['take_profit']} | R:R={p['reward_risk']}"
            )
            lines.append(
                f"    Unrealized: {p['unrealized_pnl_pts']:+.2f} pts "
                f"(${p['unrealized_pnl_usd']:+.2f})"
            )
            if p['dist_to_stop_pts'] is not None:
                lines.append(
                    f"    Dist to stop: {p['dist_to_stop_pts']:.2f} pts | "
                    f"to target: {p['dist_to_target_pts']:.2f} pts"
                )
            if p.get('slippage_pts'):
                lines.append(f"    Entry slippage: {p['slippage_pts']:.2f} pts")
    else:
        lines.append("  No open positions")

    if perf:
        lines.append(
            f"  Track record: {perf.get('total_trades', 0)} trades | "
            f"W:{perf.get('wins', 0)} L:{perf.get('losses', 0)} "
            f"({perf.get('win_rate', 0):.0f}% win rate)"
        )
        lines.append(
            f"  PnL: ${perf.get('total_pnl', 0):.2f} total | "
            f"${perf.get('avg_pnl', 0):.2f} avg | "
            f"best ${perf.get('best_trade', 0):.2f} | "
            f"worst ${perf.get('worst_trade', 0):.2f}"
        )

    # 2. EXPOSURE
    exp = pack.get("exposure", {})
    lines.append("")
    lines.append("EXPOSURE")
    lines.append(
        f"  Positions: {exp.get('open_position_count', 0)} | "
        f"Active strategies: {exp.get('active_strategy_count', 0)} "
        f"(max {exp.get('max_exposure_limit', '?')})"
    )
    nd = exp.get("net_direction", {})
    if nd:
        lines.append(f"  Net direction: long={nd.get('long', 0)} short={nd.get('short', 0)}")
    if exp.get("total_notional_usd"):
        lines.append(f"  Total notional: ${exp['total_notional_usd']:,.2f}")
    for sym, n in exp.get("symbol_exposure", {}).items():
        lines.append(f"    {sym}: ${n:,.2f}")
    status = exp.get("exposure_status", "UNKNOWN")
    if status != "CLEAN":
        lines.append(f"  !! Exposure status: {status}")
        for w in exp.get("concentration_warnings", []):
            lines.append(f"     Concentration: {w}")
        for w in exp.get("correlation_warnings", []):
            lines.append(f"     Correlation: {w}")
    else:
        lines.append("  Exposure status: CLEAN")

    # 3. APPROVALS
    appr = pack.get("approvals", {})
    lines.append("")
    lines.append("APPROVALS")
    if appr.get("total_pending", 0) > 0 or appr.get("live_queued_strategies"):
        for p in appr.get("pending_paper", []):
            lines.append(
                f"  PAPER pending: {p['strategy_id']} (ref: {p['approval_ref']})"
            )
        for p in appr.get("pending_live", []):
            lines.append(
                f"  LIVE pending: {p['strategy_id']} (ref: {p['approval_ref']})"
            )
        for lq in appr.get("live_queued_strategies", []):
            lines.append(
                f"  LIVE_QUEUED: {lq['strategy_id']} — {lq['label']}"
            )
            if lq.get("action"):
                lines.append(f"    Action: {lq['action']}")
    else:
        lines.append("  No pending approvals")

    # 4. REJECTION INTELLIGENCE
    rej = pack.get("rejection_intelligence", {})
    lines.append("")
    lines.append("REJECTION INTELLIGENCE")
    if rej.get("has_data"):
        lines.append(f"  Total rejections: {rej.get('total_rejections', 0)}")
        if rej.get("cooldown_families"):
            lines.append(f"  Cooldown families: {', '.join(rej['cooldown_families'])}")
        if rej.get("near_miss_families"):
            lines.append(f"  Near-miss families: {', '.join(rej['near_miss_families'])}")
        if rej.get("top_reasons"):
            reasons = ", ".join(
                f"{r['reason']}({r['count']})" for r in rej["top_reasons"]
            )
            lines.append(f"  Top reasons: {reasons}")
        if rej.get("exploration_shifts"):
            for shift in rej["exploration_shifts"]:
                lines.append(f"  >> {shift}")
        if rej.get("regime_blind_spots"):
            lines.append(
                f"  Regime blind spots: {', '.join(rej['regime_blind_spots'])}"
            )
    else:
        lines.append("  No rejection data")

    # 5. SYSTEM HEALTH
    sh = pack.get("system_health", {})
    lines.append("")
    lines.append("SYSTEM HEALTH")
    lines.append(
        f"  Active lanes: {', '.join(sorted(sh.get('active_lanes', []))) or 'none'}"
    )
    if sh.get("silent_lanes"):
        lines.append(f"  Silent/errored: {', '.join(sh['silent_lanes'])}")
    if sh.get("governor_paused_lanes"):
        lines.append(
            f"  !! Governor PAUSED: {', '.join(sh['governor_paused_lanes'])}"
        )
    cbs = sh.get("circuit_breakers", [])
    if cbs:
        for cb in cbs:
            icon = "!!" if cb.get("severity") == "critical" else "**"
            lines.append(f"  [{icon}] {cb['lane']}: {cb['detail']}")
    else:
        lines.append("  Circuit breakers: all clear")

    hs = sh.get("handshake")
    if hs:
        step_str = " ".join(f"{k}={v}" for k, v in hs.get("steps", {}).items())
        lines.append(f"  Handshake [{hs['completed_at']}]: {step_str}")

    # 6. SLIPPAGE
    slip = pack.get("slippage", {})
    lines.append("")
    lines.append("SLIPPAGE")
    if slip.get("has_data"):
        lines.append(
            f"  Trades tracked: {slip['trade_count']} | "
            f"Mean: {slip['mean_slippage_pts']:.2f} pts | "
            f"Max: {slip['max_slippage_pts']:.2f} pts"
        )
        lines.append(
            f"  Total cost: ${slip['total_slippage_usd']:.2f} | "
            f"Zero-slip: {slip['zero_slippage_pct']:.0f}%"
        )
    else:
        lines.append("  No slippage data")

    # 7. FEEDBACK LOOPS
    fb = pack.get("feedback_loops", {})
    lines.append("")
    lines.append("FEEDBACK LOOPS")
    lines.append(f"  Sigma->Atlas: {fb.get('sigma_atlas_loop', '?')}")
    cal = fb.get("fish_calibration", {})
    if isinstance(cal, dict) and cal.get("total_calibrations", 0) > 0:
        lines.append(
            f"  Fish calibration: {cal['total_calibrations']} calibrations, "
            f"trend={cal['trend']}, confidence={cal['track_record_confidence']:.2f}"
        )
        if cal.get("direction_hit_rate") is not None:
            lines.append(
                f"    Hit rate: {cal['direction_hit_rate']:.0%} | "
                f"Streak: {cal['streak']}"
            )
    else:
        lines.append("  Fish calibration: no data")
    lines.append(
        f"  Rejection feedback exported: "
        f"{'yes' if fb.get('rejection_feedback_exported') else 'no'}"
    )
    lines.append(
        f"  Regime guidance active: "
        f"{'yes' if fb.get('regime_guidance_active') else 'no'}"
    )

    # 8. SCENARIOS
    sc = pack.get("scenarios", {})
    lines.append("")
    lines.append("FISH SCENARIOS")
    if sc.get("count", 0) > 0:
        lines.append(
            f"  Active: {sc['count']} | "
            f"Negative: {sc.get('negative_count', 0)} | "
            f"High-prob: {sc.get('high_prob_count', 0)}"
        )
        for risk in sc.get("top_risks", []):
            lines.append(
                f"  >> {risk['type']} ({risk['probability']:.0%} prob, {risk['impact']})"
            )
    else:
        lines.append("  No active scenarios")

    lines.append("")
    lines.append(f"{'=' * 72}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def write_truth_pack(pack: dict | None = None) -> tuple[Path, Path]:
    """Build (if needed) and write truth pack to disk. Returns (json_path, md_path)."""
    if pack is None:
        pack = build_truth_pack()

    TRUTH_PACK_DIR.mkdir(parents=True, exist_ok=True)

    json_path = TRUTH_PACK_DIR / "latest.json"
    json_path.write_text(json.dumps(pack, indent=2, default=str) + "\n")

    md_text = render_truth_pack(pack)
    md_path = TRUTH_PACK_DIR / "latest.md"
    md_path.write_text(md_text)

    # Timestamped archive
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    (TRUTH_PACK_DIR / f"truth_pack_{ts}.json").write_text(
        json.dumps(pack, indent=2, default=str) + "\n"
    )

    return json_path, md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Operator Truth Pack")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    args = parser.parse_args()

    pack = build_truth_pack()

    if args.json:
        print(json.dumps(pack, indent=2, default=str))
    else:
        print(render_truth_pack(pack))

    json_path, md_path = write_truth_pack(pack)
    print(f"\n[truth-pack] Written to {json_path}")


if __name__ == "__main__":
    main()
