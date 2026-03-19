#!/usr/bin/env python3
"""Quant Lanes — Sigma Validation Lane.

Per spec §6: Strategy Factory lane, validation, lifecycle gatekeeper,
paper-trade reviewer.

Sigma should: validate, gate, promote/reject, maintain rigor, explain
rejections for Atlas, review paper and live performance.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import make_packet, QuantPacket, REJECTION_REASONS
from workspace.quant.shared.packet_store import store_packet
from workspace.quant.shared.registries.strategy_registry import transition_strategy, get_strategy


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

    Returns (outcome, packet) where outcome is "promoted" or "rejected".
    """
    strategy_id = candidate_packet.strategy_id
    if not strategy_id:
        raise ValueError("candidate_packet must have strategy_id")

    # Simple validation gates (will be configurable via review_thresholds.json later)
    MIN_PF = 1.3
    MIN_SHARPE = 0.8
    MAX_DD = 0.15  # 15%
    MIN_TRADES = 20

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
        # Reject — use the first/primary reason
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

        # Transition registry
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

    # Emit papertrade_candidate_packet for Kitt
    ptc = make_packet(
        "papertrade_candidate_packet", "sigma",
        f"Strategy {strategy_id} fit for paper trading. PF {profit_factor}, Sharpe {sharpe}.",
        priority="high",
        strategy_id=strategy_id,
        evidence_refs=[promotion.packet_id],
        action_requested="Kitt: request operator approval for paper trade",
    )
    store_packet(root, ptc)

    # Transition registry
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

    Returns (outcome, paper_review_packet) where outcome is
    "advance_to_live", "iterate", or "kill".
    """
    # Review thresholds per spec §11
    MIN_PF = 1.3
    MIN_SHARPE = 0.8
    MAX_DD = 0.15
    MAX_SLIPPAGE_MULT = 2.0  # vs backtest
    MIN_FILL_RATE = 0.90
    MAX_CORRELATION = 0.7

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
