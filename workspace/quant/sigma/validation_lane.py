#!/usr/bin/env python3
"""Quant Lanes — Sigma Validation Lane.

Per spec §6: Strategy Factory lane, validation, lifecycle gatekeeper,
paper-trade reviewer.

Sigma should: validate, gate, promote/reject, maintain rigor, explain
rejections for Atlas, review paper and live performance.

Thresholds loaded from shared/config/review_thresholds.json at runtime.
Falls back to hardcoded defaults if file is missing or corrupt.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import make_packet, QuantPacket, REJECTION_REASONS
from workspace.quant.shared.packet_store import store_packet
from workspace.quant.shared.registries.strategy_registry import transition_strategy, get_strategy

# Hardcoded defaults — used when config file is missing or corrupt.
_DEFAULT_VALIDATION = {
    "min_profit_factor": 1.3,
    "min_sharpe": 0.8,
    "max_drawdown_pct": 0.15,
    "min_trades": 20,
}

_DEFAULT_PAPER_REVIEW = {
    "min_profit_factor": 1.3,
    "min_sharpe": 0.8,
    "max_drawdown_pct": 0.15,
    "min_fill_rate": 0.90,
    "max_correlation": 0.7,
}


def load_thresholds(root: Path) -> dict:
    """Load review_thresholds.json. Returns full config dict.

    Falls back to defaults if missing or corrupt. Never crashes.
    """
    path = root / "workspace" / "quant" / "shared" / "config" / "review_thresholds.json"
    if not path.exists():
        return {"validation": dict(_DEFAULT_VALIDATION), "paper_review": dict(_DEFAULT_PAPER_REVIEW),
                "_source": "defaults"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Validate structure minimally
        if not isinstance(data.get("validation"), dict) or not isinstance(data.get("paper_review"), dict):
            return {"validation": dict(_DEFAULT_VALIDATION), "paper_review": dict(_DEFAULT_PAPER_REVIEW),
                    "_source": "defaults (invalid structure)"}
        return {**data, "_source": str(path)}
    except (json.JSONDecodeError, ValueError, OSError):
        return {"validation": dict(_DEFAULT_VALIDATION), "paper_review": dict(_DEFAULT_PAPER_REVIEW),
                "_source": "defaults (corrupt file)"}


def _get_validation_thresholds(root: Path) -> dict:
    """Get validation thresholds, merging config over defaults."""
    cfg = load_thresholds(root)
    result = dict(_DEFAULT_VALIDATION)
    result.update(cfg.get("validation", {}))
    return result


def _get_paper_review_thresholds(root: Path) -> dict:
    """Get paper review thresholds, merging config over defaults."""
    cfg = load_thresholds(root)
    result = dict(_DEFAULT_PAPER_REVIEW)
    result.update(cfg.get("paper_review", {}))
    return result


def _emit_discord(packet: QuantPacket, root: Path):
    """Best-effort Discord emission for sigma events."""
    try:
        from workspace.quant.shared.discord_bridge import emit_quant_event
        emit_quant_event(packet, root=root)
    except Exception:
        pass


def validate_candidate(
    root: Path,
    candidate_packet: QuantPacket,
    profit_factor: float,
    sharpe: float,
    max_drawdown_pct: float,
    trade_count: int,
    wfe: Optional[float] = None,
    regime_aware: bool = False,
) -> tuple[str, QuantPacket]:
    """Validate a candidate strategy and produce validation outcome.

    Thresholds loaded from review_thresholds.json; falls back to defaults.
    Returns (outcome, packet) where outcome is "promoted" or "rejected".
    """
    strategy_id = candidate_packet.strategy_id
    if not strategy_id:
        raise ValueError("candidate_packet must have strategy_id")

    t = _get_validation_thresholds(root)
    MIN_PF = t["min_profit_factor"]
    MIN_SHARPE = t["min_sharpe"]
    MAX_DD = t["max_drawdown_pct"]
    MIN_TRADES = t["min_trades"]

    rejection_reasons = []
    if profit_factor < MIN_PF:
        rejection_reasons.append(("poor_oos", f"PF {profit_factor} < {MIN_PF}"))
    if sharpe < MIN_SHARPE:
        rejection_reasons.append(("poor_oos", f"Sharpe {sharpe} < {MIN_SHARPE}"))
    if max_drawdown_pct > MAX_DD:
        rejection_reasons.append(("excessive_drawdown", f"DD {max_drawdown_pct:.1%} > {MAX_DD:.1%}"))
    if trade_count < MIN_TRADES:
        rejection_reasons.append(("insufficient_trades", f"Trades {trade_count} < {MIN_TRADES}"))

    if rejection_reasons:
        primary_reason, detail = rejection_reasons[0]
        all_details = "; ".join(d for _, d in rejection_reasons)

        rejection = make_packet(
            "strategy_rejection_packet", "sigma",
            f"Strategy {strategy_id} rejected: {all_details}",
            priority="medium",
            strategy_id=strategy_id,
            rejection_reason=primary_reason,
            rejection_detail=all_details,
            suggestion=f"Consider adjusting parameters to improve {'profitability' if profit_factor < MIN_PF else 'risk profile'}.",
            evidence_refs=[candidate_packet.packet_id],
            escalation_level="team_only",
        )
        store_packet(root, rejection)
        _emit_discord(rejection, root)

        try:
            strategy = get_strategy(root, strategy_id)
            if strategy and strategy.lifecycle_state == "VALIDATING":
                transition_strategy(root, strategy_id, "REJECTED", actor="sigma",
                                    note=f"Validation failed: {all_details}")
        except (ValueError, TimeoutError):
            pass

        return "rejected", rejection

    # Promote
    validation = make_packet(
        "validation_packet", "sigma",
        f"Strategy {strategy_id} passes validation: PF {profit_factor}, Sharpe {sharpe}, DD {max_drawdown_pct:.1%}, {trade_count} trades",
        priority="high",
        strategy_id=strategy_id,
        confidence=min(0.9, profit_factor / 2.0),
        evidence_refs=[candidate_packet.packet_id],
    )
    store_packet(root, validation)

    promotion = make_packet(
        "promotion_packet", "sigma",
        f"Strategy {strategy_id} promoted. Meets all validation gates.",
        priority="high",
        strategy_id=strategy_id,
        evidence_refs=[validation.packet_id, candidate_packet.packet_id],
        action_requested="Kitt: evaluate for paper trade request",
        escalation_level="kitt_only",
    )
    store_packet(root, promotion)
    _emit_discord(promotion, root)

    ptc = make_packet(
        "papertrade_candidate_packet", "sigma",
        f"Strategy {strategy_id} fit for paper trading. PF {profit_factor}, Sharpe {sharpe}.",
        priority="high",
        strategy_id=strategy_id,
        evidence_refs=[promotion.packet_id],
        action_requested="Kitt: request operator approval for paper trade",
    )
    store_packet(root, ptc)

    try:
        strategy = get_strategy(root, strategy_id)
        if strategy and strategy.lifecycle_state == "VALIDATING":
            transition_strategy(root, strategy_id, "PROMOTED", actor="sigma",
                                note=f"Validated: PF {profit_factor}, Sharpe {sharpe}")
    except (ValueError, TimeoutError):
        pass

    return "promoted", promotion


def review_paper_results(
    root: Path,
    strategy_id: str,
    realized_pf: float,
    realized_sharpe: float,
    max_drawdown: float,
    avg_slippage: float,
    fill_rate: float,
    trade_count: int,
    portfolio_correlation: float = 0.0,
) -> tuple[str, QuantPacket]:
    """Review paper trading results per spec §11.

    Thresholds loaded from review_thresholds.json; falls back to defaults.
    Returns (outcome, paper_review_packet) where outcome is
    "advance_to_live", "iterate", or "kill".
    """
    t = _get_paper_review_thresholds(root)
    MIN_PF = t["min_profit_factor"]
    MIN_SHARPE = t["min_sharpe"]
    MAX_DD = t["max_drawdown_pct"]
    MIN_FILL_RATE = t["min_fill_rate"]
    MAX_CORRELATION = t["max_correlation"]

    issues = []
    if realized_pf < MIN_PF:
        issues.append(f"PF {realized_pf} < {MIN_PF}")
    if realized_sharpe < MIN_SHARPE:
        issues.append(f"Sharpe {realized_sharpe} < {MIN_SHARPE}")
    if max_drawdown > MAX_DD:
        issues.append(f"DD {max_drawdown:.1%} > {MAX_DD:.1%}")
    if fill_rate < MIN_FILL_RATE:
        issues.append(f"Fill rate {fill_rate:.1%} < {MIN_FILL_RATE:.1%}")
    if portfolio_correlation > MAX_CORRELATION:
        issues.append(f"Correlation {portfolio_correlation} > {MAX_CORRELATION}")

    if len(issues) >= 3:
        outcome = "kill"
        outcome_reasoning = f"Too many failures: {'; '.join(issues)}"
    elif issues:
        outcome = "iterate"
        outcome_reasoning = f"Fixable issues: {'; '.join(issues)}"
    else:
        outcome = "advance_to_live"
        outcome_reasoning = "All paper review criteria pass."

    review = make_packet(
        "paper_review_packet", "sigma",
        f"Paper review for {strategy_id}: {outcome}",
        priority="high",
        strategy_id=strategy_id,
        trade_count=trade_count,
        realized_pf=realized_pf,
        realized_sharpe=realized_sharpe,
        max_drawdown=max_drawdown,
        avg_slippage=avg_slippage,
        fill_rate=fill_rate,
        portfolio_correlation=portfolio_correlation,
        outcome=outcome,
        outcome_reasoning=outcome_reasoning,
        iteration_guidance=f"Address: {'; '.join(issues)}" if outcome == "iterate" else None,
        consistency_flag="pass" if not issues else "fail",
    )
    store_packet(root, review)

    return outcome, review


# ---------------------------------------------------------------------------
# Health summary
# ---------------------------------------------------------------------------

def emit_health_summary(
    root: Path,
    period_start: str,
    period_end: str,
    packets_produced: int,
    validations_done: int = 0,
    promotions: int = 0,
    rejections: int = 0,
    paper_reviews: int = 0,
    error_count: int = 0,
    usefulness_score: float = 0.5,
    efficiency_score: float = 0.5,
    health_score: float = 0.8,
    confidence_score: float = 0.5,
    host_used: str = "NIMO",
    scheduler_waits: int = 0,
) -> QuantPacket:
    """Emit Sigma health_summary per spec §10."""
    from workspace.quant.shared.scheduler.scheduler import check_capacity
    from workspace.quant.shared.governor import evaluate_cycle, get_lane_params

    can_start, _, _ = check_capacity(root, "sigma")
    gov_action, gov_reason = evaluate_cycle(
        root, "sigma",
        usefulness_score=usefulness_score,
        efficiency_score=efficiency_score,
        health_score=health_score,
        confidence_score=confidence_score,
        host_has_capacity=can_start,
    )
    params = get_lane_params(root, "sigma")

    pkt = make_packet(
        "health_summary", "sigma",
        f"Sigma health: {validations_done} validations, {promotions} promoted, {rejections} rejected, {paper_reviews} paper reviews",
        priority="low",
        period_start=period_start,
        period_end=period_end,
        packets_produced=packets_produced,
        packets_by_type={
            "validation_packet": validations_done,
            "promotion_packet": promotions,
            "strategy_rejection_packet": rejections,
            "paper_review_packet": paper_reviews,
        },
        escalation_count=0,
        error_count=error_count,
        cloud_bursts=0,
        estimated_cloud_cost=0.0,
        notable_events=f"{promotions} promoted, {rejections} rejected" if promotions or rejections else "routine",
        scheduler_waits=scheduler_waits,
        scheduler_bypasses=0,
        host_used=host_used,
        local_runtime_seconds=0.0,
        cloud_runtime_seconds=0.0,
        usefulness_score=usefulness_score,
        efficiency_score=efficiency_score,
        health_score=health_score,
        confidence_score=confidence_score,
        governor_action_taken=gov_action,
        governor_reason=gov_reason,
        current_batch_size=params.get("batch_size", 1),
        current_cadence_multiplier=params.get("cadence_multiplier", 1.0),
    )
    store_packet(root, pkt)
    return pkt
