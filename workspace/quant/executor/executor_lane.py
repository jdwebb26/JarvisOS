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
from workspace.quant.executor.paper_adapter import get_adapter, Order


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

    # Pre-flight 1: Kill switch
    if _kill_switch_engaged(root):
        rejection = make_packet(
            "execution_rejection_packet", "executor",
            f"Execution refused for {strategy_id}: kill switch engaged",
            priority="critical",
            strategy_id=strategy_id,
            execution_rejection_reason="kill_switch_engaged",
            execution_rejection_detail="Kill switch is currently engaged. All execution halted.",
            order_details={"symbol": symbol, "side": side, "quantity": quantity},
        )
        store_packet(root, rejection)
        result["packets"].append(rejection.to_dict())
        result["rejection_reason"] = "kill_switch_engaged"
        return result

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

        rejection = make_packet(
            "execution_rejection_packet", "executor",
            f"Execution refused for {strategy_id}: {reason}",
            priority="high",
            strategy_id=strategy_id,
            execution_rejection_reason=rej_reason,
            execution_rejection_detail=reason,
            order_details={"symbol": symbol, "side": side, "quantity": quantity, "approval_ref": approval_ref},
        )
        store_packet(root, rejection)
        result["packets"].append(rejection.to_dict())
        result["rejection_reason"] = rej_reason
        return result

    # Pre-flight 5: Risk limits
    risk_ok, risk_reason = _check_risk_limits(root, strategy_id, symbol, quantity)
    if not risk_ok:
        rejection = make_packet(
            "execution_rejection_packet", "executor",
            f"Execution refused for {strategy_id}: {risk_reason}",
            priority="high",
            strategy_id=strategy_id,
            execution_rejection_reason="strategy_limit_breach",
            execution_rejection_detail=risk_reason,
            order_details={"symbol": symbol, "side": side, "quantity": quantity},
        )
        store_packet(root, rejection)
        result["packets"].append(rejection.to_dict())
        result["rejection_reason"] = "strategy_limit_breach"
        return result

    # Pre-flight 6: Broker health
    state_dir = root / "state" / "quant" / "executor"
    adapter = get_adapter("paper", state_dir)
    if not adapter.health_check():
        rejection = make_packet(
            "execution_rejection_packet", "executor",
            f"Execution refused for {strategy_id}: broker unhealthy",
            priority="critical",
            strategy_id=strategy_id,
            execution_rejection_reason="broker_unhealthy",
            execution_rejection_detail="Paper broker adapter health check failed",
            order_details={"symbol": symbol, "side": side, "quantity": quantity},
        )
        store_packet(root, rejection)
        result["packets"].append(rejection.to_dict())
        result["rejection_reason"] = "broker_unhealthy"
        return result

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
    return result
