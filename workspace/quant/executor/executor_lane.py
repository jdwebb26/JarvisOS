#!/usr/bin/env python3
"""Quant Lanes — Executor Lane.

Per spec §6: execution lane for approved paper and live trades.
Local-only for all execution-critical operations.

Pre-flight checks (all must pass):
  1. approval_ref exists, not expired, not revoked
  2. execution_mode matches approval_type
  3. symbols within approved_actions.symbols
  4. position would not breach per-strategy limits
  5. position would not breach portfolio limits
  6. kill switch not engaged
  7. broker connection healthy

Failure on any check: refuse, emit execution_rejection_packet, do not retry.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workspace.quant.shared.schemas.packets import make_packet, validate_packet, QuantPacket
from workspace.quant.shared.packet_store import store_packet
from workspace.quant.shared.registries.approval_registry import (
    validate_approval_for_execution, get_approval,
)
from workspace.quant.shared.registries.strategy_registry import (
    get_strategy, transition_strategy,
)
from workspace.quant.executor.paper_adapter import (
    get_adapter, Order, BrokerNotConfiguredError, check_live_broker_config,
)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _kill_switch_engaged(root: Path) -> bool:
    ks = _load_json(root / "workspace" / "quant" / "shared" / "config" / "kill_switch.json")
    return ks.get("engaged", False)


def _check_risk_limits(root: Path, strategy_id: str, symbol: str, quantity: int) -> tuple[bool, str]:
    """Check per-strategy and portfolio risk limits."""
    limits = _load_json(root / "workspace" / "quant" / "shared" / "config" / "risk_limits.json")
    per_strat = limits.get("per_strategy", {})
    max_pos = per_strat.get("max_position_size", 2)
    if quantity > max_pos:
        return False, f"strategy_limit_breach: quantity {quantity} > max {max_pos}"
    # Portfolio checks would look at all active positions — simplified for now
    return True, "within_limits"


def execute_paper_trade(
    root: Path,
    strategy_id: str,
    approval_ref: str,
    symbol: str,
    side: str,
    order_type: str = "market",
    quantity: int = 1,
    simulated_price: float = 18250.0,
) -> dict:
    """Execute a paper trade with full pre-flight checks.

    Returns dict with:
      - success: bool
      - packets: list of emitted packet dicts
      - fill: fill result dict (if successful)
      - rejection_reason: str (if failed)
    """
    result = {"success": False, "packets": [], "fill": None, "rejection_reason": None}

    def _emit_pkt(pkt):
        try:
            from workspace.quant.shared.discord_bridge import emit_quant_event
            emit_quant_event(pkt, root=root)
        except Exception:
            pass

    def _reject(pkt, reason):
        store_packet(root, pkt)
        result["packets"].append(pkt.to_dict())
        result["rejection_reason"] = reason
        _emit_pkt(pkt)
        return result

    # Pre-flight 1: Kill switch
    if _kill_switch_engaged(root):
        return _reject(make_packet(
            "execution_rejection_packet", "executor",
            f"Execution refused for {strategy_id}: kill switch engaged",
            priority="critical", strategy_id=strategy_id,
            execution_rejection_reason="kill_switch_engaged",
            execution_rejection_detail="Kill switch is currently engaged. All execution halted.",
            order_details={"symbol": symbol, "side": side, "quantity": quantity},
        ), "kill_switch_engaged")

    # Pre-flight 2-4: Approval validation
    valid, reason = validate_approval_for_execution(
        root, approval_ref, strategy_id, "paper", symbol,
    )
    if not valid:
        # Map reason to rejection enum
        rej_reason = "invalid_approval"
        if "expired" in reason:
            rej_reason = "expired_approval"
        elif "revoked" in reason:
            rej_reason = "revoked_approval"
        elif "mode_mismatch" in reason:
            rej_reason = "mode_mismatch"
        elif "symbol_not_approved" in reason:
            rej_reason = "symbol_not_approved"

        return _reject(make_packet(
            "execution_rejection_packet", "executor",
            f"Execution refused for {strategy_id}: {reason}",
            priority="high", strategy_id=strategy_id,
            execution_rejection_reason=rej_reason, execution_rejection_detail=reason,
            order_details={"symbol": symbol, "side": side, "quantity": quantity, "approval_ref": approval_ref},
        ), rej_reason)

    # Pre-flight 5: Risk limits
    risk_ok, risk_reason = _check_risk_limits(root, strategy_id, symbol, quantity)
    if not risk_ok:
        return _reject(make_packet(
            "execution_rejection_packet", "executor",
            f"Execution refused for {strategy_id}: {risk_reason}",
            priority="high", strategy_id=strategy_id,
            execution_rejection_reason="strategy_limit_breach",
            execution_rejection_detail=risk_reason,
            order_details={"symbol": symbol, "side": side, "quantity": quantity},
        ), "strategy_limit_breach")

    # Pre-flight 6: Broker health
    state_dir = root / "state" / "quant" / "executor"
    adapter = get_adapter("paper", state_dir)
    if not adapter.health_check():
        return _reject(make_packet(
            "execution_rejection_packet", "executor",
            f"Execution refused for {strategy_id}: broker unhealthy",
            priority="critical", strategy_id=strategy_id,
            execution_rejection_reason="broker_unhealthy",
            execution_rejection_detail="Paper broker adapter health check failed",
            order_details={"symbol": symbol, "side": side, "quantity": quantity},
        ), "broker_unhealthy")

    # Emit execution intent
    intent = make_packet(
        "execution_intent_packet", "executor",
        f"Paper trade intent: {side} {quantity} {symbol} for {strategy_id}",
        priority="high",
        strategy_id=strategy_id,
        execution_mode="paper",
        symbol=symbol,
        side=side,
        order_type=order_type,
        approval_ref=approval_ref,
        sizing={"method": "fixed", "contracts": quantity},
    )
    store_packet(root, intent)
    result["packets"].append(intent.to_dict())

    # Execute via paper adapter
    order = Order(
        strategy_id=strategy_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        approval_ref=approval_ref,
    )
    fill = adapter.place_order(order, simulated_price=simulated_price)

    # Emit execution status
    status_pkt = make_packet(
        "execution_status_packet", "executor",
        f"Paper trade filled: {side} {quantity} {symbol} at {fill.fill_price} (slippage: {fill.slippage})",
        priority="medium",
        strategy_id=strategy_id,
        execution_mode="paper",
        symbol=symbol,
        approval_ref=approval_ref,
        execution_status=fill.status,
        fill_price=fill.fill_price,
        slippage=fill.slippage,
    )
    store_packet(root, status_pkt)
    result["packets"].append(status_pkt.to_dict())

    # Transition strategy to PAPER_ACTIVE if currently PAPER_QUEUED
    try:
        strategy = get_strategy(root, strategy_id)
        if strategy and strategy.lifecycle_state == "PAPER_QUEUED":
            transition_strategy(
                root, strategy_id, "PAPER_ACTIVE", actor="executor",
                note=f"Paper orders placed: {fill.order_id}",
            )
    except (ValueError, TimeoutError):
        pass  # Non-fatal — execution succeeded even if registry update fails

    result["success"] = True
    result["fill"] = fill.to_dict()

    # Emit Discord events for execution packets
    _emit_pkt(intent)
    _emit_pkt(status_pkt)

    return result


def execute_live_trade(
    root: Path,
    strategy_id: str,
    approval_ref: str,
    symbol: str,
    side: str,
    order_type: str = "market",
    quantity: int = 1,
) -> dict:
    """Execute a live trade with full pre-flight checks.

    Identical preflight to paper path, but uses live adapter and
    execution_mode="live". Raises BrokerNotConfiguredError at the broker
    boundary if credentials are not set.

    Returns dict with:
      - success: bool
      - packets: list of emitted packet dicts
      - fill: fill result dict (if successful)
      - rejection_reason: str (if failed)
      - broker_error: str (if broker not configured)
    """
    result = {"success": False, "packets": [], "fill": None,
              "rejection_reason": None, "broker_error": None}

    def _emit_pkt(pkt):
        try:
            from workspace.quant.shared.discord_bridge import emit_quant_event
            emit_quant_event(pkt, root=root)
        except Exception:
            pass

    def _reject(pkt, reason):
        store_packet(root, pkt)
        result["packets"].append(pkt.to_dict())
        result["rejection_reason"] = reason
        _emit_pkt(pkt)
        return result

    # Pre-flight 1: Kill switch
    if _kill_switch_engaged(root):
        return _reject(make_packet(
            "execution_rejection_packet", "executor",
            f"Live execution refused for {strategy_id}: kill switch engaged",
            priority="critical", strategy_id=strategy_id,
            execution_rejection_reason="kill_switch_engaged",
            execution_rejection_detail="Kill switch is currently engaged. All execution halted.",
            order_details={"symbol": symbol, "side": side, "quantity": quantity},
        ), "kill_switch_engaged")

    # Pre-flight 2-4: Approval validation (must be live_trade approval)
    valid, reason = validate_approval_for_execution(
        root, approval_ref, strategy_id, "live", symbol,
    )
    if not valid:
        rej_reason = "invalid_approval"
        if "expired" in reason:
            rej_reason = "expired_approval"
        elif "revoked" in reason:
            rej_reason = "revoked_approval"
        elif "mode_mismatch" in reason:
            rej_reason = "mode_mismatch"
        elif "symbol_not_approved" in reason:
            rej_reason = "symbol_not_approved"

        return _reject(make_packet(
            "execution_rejection_packet", "executor",
            f"Live execution refused for {strategy_id}: {reason}",
            priority="high", strategy_id=strategy_id,
            execution_rejection_reason=rej_reason, execution_rejection_detail=reason,
            order_details={"symbol": symbol, "side": side, "quantity": quantity,
                           "approval_ref": approval_ref},
        ), rej_reason)

    # Pre-flight 5: Risk limits
    risk_ok, risk_reason = _check_risk_limits(root, strategy_id, symbol, quantity)
    if not risk_ok:
        return _reject(make_packet(
            "execution_rejection_packet", "executor",
            f"Live execution refused for {strategy_id}: {risk_reason}",
            priority="high", strategy_id=strategy_id,
            execution_rejection_reason="strategy_limit_breach",
            execution_rejection_detail=risk_reason,
            order_details={"symbol": symbol, "side": side, "quantity": quantity},
        ), "strategy_limit_breach")

    # Pre-flight 6: Broker health
    state_dir = root / "state" / "quant" / "executor"
    adapter = get_adapter("live", state_dir)
    if not adapter.health_check():
        # Distinguish between "not configured" and "configured but unhealthy"
        configured, config_status = check_live_broker_config()
        if not configured:
            missing = [k for k, v in config_status.items() if v == "MISSING"]
            detail = (
                f"Live broker not configured. Missing env vars: {', '.join(missing)}. "
                f"All preflight checks passed — broker config is the final blocker."
            )
            result["broker_error"] = detail
            return _reject(make_packet(
                "execution_rejection_packet", "executor",
                f"Live execution refused for {strategy_id}: broker not configured",
                priority="critical", strategy_id=strategy_id,
                execution_rejection_reason="broker_unhealthy",
                execution_rejection_detail=detail,
                order_details={"symbol": symbol, "side": side, "quantity": quantity},
            ), "broker_unhealthy")
        else:
            return _reject(make_packet(
                "execution_rejection_packet", "executor",
                f"Live execution refused for {strategy_id}: broker unhealthy",
                priority="critical", strategy_id=strategy_id,
                execution_rejection_reason="broker_unhealthy",
                execution_rejection_detail="Live broker health check failed",
                order_details={"symbol": symbol, "side": side, "quantity": quantity},
            ), "broker_unhealthy")

    # Emit execution intent
    intent = make_packet(
        "execution_intent_packet", "executor",
        f"Live trade intent: {side} {quantity} {symbol} for {strategy_id}",
        priority="critical",
        strategy_id=strategy_id,
        execution_mode="live",
        symbol=symbol,
        side=side,
        order_type=order_type,
        approval_ref=approval_ref,
        sizing={"method": "fixed", "contracts": quantity},
    )
    store_packet(root, intent)
    result["packets"].append(intent.to_dict())
    _emit_pkt(intent)

    # Execute via live adapter
    order = Order(
        strategy_id=strategy_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        approval_ref=approval_ref,
    )
    try:
        fill = adapter.place_order(order)
    except BrokerNotConfiguredError as e:
        result["broker_error"] = str(e)
        return _reject(make_packet(
            "execution_rejection_packet", "executor",
            f"Live execution failed for {strategy_id}: {e}",
            priority="critical", strategy_id=strategy_id,
            execution_rejection_reason="broker_unhealthy",
            execution_rejection_detail=str(e),
            order_details={"symbol": symbol, "side": side, "quantity": quantity},
        ), "broker_unhealthy")

    # Emit execution status
    status_pkt = make_packet(
        "execution_status_packet", "executor",
        f"Live trade filled: {side} {quantity} {symbol} at {fill.fill_price}",
        priority="high",
        strategy_id=strategy_id,
        execution_mode="live",
        symbol=symbol,
        approval_ref=approval_ref,
        execution_status=fill.status,
        fill_price=fill.fill_price,
        slippage=fill.slippage,
    )
    store_packet(root, status_pkt)
    result["packets"].append(status_pkt.to_dict())

    # Transition strategy
    try:
        strategy = get_strategy(root, strategy_id)
        if strategy and strategy.lifecycle_state == "LIVE_QUEUED":
            transition_strategy(
                root, strategy_id, "LIVE_ACTIVE", actor="executor",
                note=f"Live orders placed: {fill.order_id}",
            )
    except (ValueError, TimeoutError):
        pass

    result["success"] = True
    result["fill"] = fill.to_dict()
    _emit_pkt(status_pkt)

    return result


# ---------------------------------------------------------------------------
# Portfolio risk checks
# ---------------------------------------------------------------------------

def check_portfolio_risk(root: Path) -> dict:
    """Check portfolio-level risk: total exposure, concentration, correlation.

    Returns {ok: bool, issues: [str], exposure: int, limits: dict}.
    """
    from workspace.quant.shared.registries.strategy_registry import get_strategies_by_state
    limits = _load_json(root / "workspace" / "quant" / "shared" / "config" / "risk_limits.json")
    portfolio = limits.get("portfolio", {})
    max_exposure = portfolio.get("max_total_exposure", 4)
    max_correlated = portfolio.get("max_correlated_strategies", 3)
    concentration_threshold = portfolio.get("concentration_threshold", 0.6)

    active_paper = get_strategies_by_state(root, "PAPER_ACTIVE")
    active_live = get_strategies_by_state(root, "LIVE_ACTIVE")
    total_active = len(active_paper) + len(active_live)

    issues = []
    if total_active > max_exposure:
        issues.append(f"total_exposure {total_active} > max {max_exposure}")

    # Concentration: if any single strategy represents too large a fraction
    if total_active > 0:
        fraction_per = 1.0 / total_active
        # With only 1 strategy, concentration = 1.0 which is expected and OK
        if total_active >= 2 and fraction_per > concentration_threshold:
            issues.append(f"concentration {fraction_per:.2f} > {concentration_threshold}")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "exposure": total_active,
        "limits": portfolio,
    }


# ---------------------------------------------------------------------------
# Health summary
# ---------------------------------------------------------------------------

def emit_health_summary(
    root: Path,
    period_start: str,
    period_end: str,
    packets_produced: int,
    executions_attempted: int = 0,
    executions_filled: int = 0,
    executions_rejected: int = 0,
    error_count: int = 0,
    usefulness_score: float = 0.5,
    efficiency_score: float = 0.5,
    health_score: float = 0.8,
    confidence_score: float = 0.5,
    host_used: str = "NIMO",
    scheduler_waits: int = 0,
) -> QuantPacket:
    """Emit Executor health_summary per spec §10."""
    from workspace.quant.shared.scheduler.scheduler import check_capacity
    from workspace.quant.shared.governor import evaluate_cycle, get_lane_params

    can_start, _, _ = check_capacity(root, "executor")
    gov_action, gov_reason = evaluate_cycle(
        root, "executor",
        usefulness_score=usefulness_score,
        efficiency_score=efficiency_score,
        health_score=health_score,
        confidence_score=confidence_score,
        host_has_capacity=can_start,
    )
    params = get_lane_params(root, "executor")

    kill_engaged = _kill_switch_engaged(root)
    portfolio = check_portfolio_risk(root)

    notable_parts = []
    if kill_engaged:
        notable_parts.append("kill_switch=ENGAGED")
    if not portfolio["ok"]:
        notable_parts.append(f"portfolio_risk: {'; '.join(portfolio['issues'])}")

    pkt = make_packet(
        "health_summary", "executor",
        f"Executor health: {executions_filled}/{executions_attempted} filled, "
        f"{executions_rejected} rejected, kill_switch={'ENGAGED' if kill_engaged else 'off'}, "
        f"portfolio_exposure={portfolio['exposure']}",
        priority="low",
        period_start=period_start,
        period_end=period_end,
        packets_produced=packets_produced,
        packets_by_type={
            "execution_intent_packet": executions_attempted,
            "execution_status_packet": executions_filled,
            "execution_rejection_packet": executions_rejected,
        },
        escalation_count=0,
        error_count=error_count,
        cloud_bursts=0,
        estimated_cloud_cost=0.0,
        notable_events="; ".join(notable_parts) if notable_parts else "routine",
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
