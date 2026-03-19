#!/usr/bin/env python3
"""Quant Lanes — Approval Bridge.

Bridges quant lane paper/live trade approvals with the live Jarvis runtime
approval system. This is the integration point that:

1. When a strategy is PROMOTED and Kitt wants paper trade approval:
   - Creates a quant approval_object (pending operator action)
   - Posts to #review via the live runtime approval_requested event
   - Returns the approval_ref for later use

2. When operator approves via #review or CLI:
   - Updates the quant approval_object
   - Transitions strategy registry to PAPER_QUEUED
   - Triggers Executor paper trade flow

Reuses the existing emit_event() and Discord event routing.
Does NOT create a Jarvis TaskRecord — quant approvals are lightweight
approval objects, not full tasks.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace.quant.shared.registries.approval_registry import (
    create_approval, get_approval, ApprovedActions, ApprovalObject,
)
from workspace.quant.shared.registries.strategy_registry import (
    get_strategy, transition_strategy,
)
from workspace.quant.shared.discord_bridge import emit_quant_approval_request
from workspace.quant.executor.executor_lane import execute_paper_trade


def request_paper_trade_approval(
    root: Path,
    strategy_id: str,
    symbols: list[str],
    max_position_size: int = 2,
    max_loss_per_trade: float = 500.0,
    max_total_drawdown: float = 2000.0,
    valid_days: int = 14,
    conditions: str = "Review after 14 days or 20 trades, whichever comes first.",
) -> dict:
    """Request operator approval for paper trading a promoted strategy.

    This is the live-runtime entry point for the paper trade approval flow.
    Creates the approval object, posts to #review, returns the approval_ref.

    Returns dict with:
        - approval_ref: str
        - strategy_id: str
        - discord_event: dict (emit_event result)
        - error: str or None
    """
    result = {"approval_ref": None, "strategy_id": strategy_id, "discord_event": None, "error": None}

    # Verify strategy exists and is in PROMOTED state
    strategy = get_strategy(root, strategy_id)
    if strategy is None:
        result["error"] = f"Strategy {strategy_id} not found"
        return result
    if strategy.lifecycle_state != "PROMOTED":
        result["error"] = f"Strategy {strategy_id} is in {strategy.lifecycle_state}, not PROMOTED"
        return result

    # Create approval object (pending)
    now = datetime.now(timezone.utc)
    actions = ApprovedActions(
        execution_mode="paper",
        symbols=symbols,
        max_position_size=max_position_size,
        max_loss_per_trade=max_loss_per_trade,
        max_total_drawdown=max_total_drawdown,
        slippage_tolerance=0.05,
        valid_from=now.isoformat(),
        valid_until=(now + timedelta(days=valid_days)).isoformat(),
        broker_target="paper_adapter",
    )

    approval = create_approval(
        root=root,
        strategy_id=strategy_id,
        approval_type="paper_trade",
        approved_actions=actions,
        conditions=conditions,
    )
    result["approval_ref"] = approval.approval_ref

    # Post to #review via live Discord event router
    detail = (
        f"Paper trade {strategy_id} on {', '.join(symbols)}. "
        f"Max pos {max_position_size}, max loss/trade ${max_loss_per_trade}, "
        f"max DD ${max_total_drawdown}. Valid {valid_days} days."
    )
    discord_result = emit_quant_approval_request(
        strategy_id=strategy_id,
        approval_type="paper_trade",
        approval_ref=approval.approval_ref,
        detail=detail,
        root=root,
    )
    result["discord_event"] = discord_result

    return result


def approve_paper_trade(
    root: Path,
    strategy_id: str,
    approval_ref: Optional[str] = None,
) -> dict:
    """Operator approves paper trade. Transitions strategy and triggers execution.

    If approval_ref is not provided, finds the latest pending approval for the strategy.

    Returns dict with:
        - success: bool
        - approval_ref: str
        - strategy_state: str
        - error: str or None
    """
    result = {"success": False, "approval_ref": None, "strategy_state": None, "error": None}

    # Find approval
    if approval_ref:
        approval = get_approval(root, approval_ref)
    else:
        # Find latest approval for this strategy
        from workspace.quant.shared.registries.approval_registry import load_all_approvals
        approvals = [a for a in load_all_approvals(root)
                     if a.strategy_id == strategy_id and not a.revoked]
        approval = approvals[-1] if approvals else None

    if approval is None:
        result["error"] = f"No approval found for {strategy_id}"
        return result

    result["approval_ref"] = approval.approval_ref

    # Verify it's valid
    valid, reason = approval.is_valid()
    if not valid:
        result["error"] = f"Approval invalid: {reason}"
        return result

    # Transition strategy to PAPER_QUEUED
    try:
        entry = transition_strategy(
            root, strategy_id, "PAPER_QUEUED",
            actor="kitt",
            approval_ref=approval.approval_ref,
            note="Operator approved paper trade",
        )
        result["strategy_state"] = entry.lifecycle_state
        result["success"] = True
    except ValueError as e:
        result["error"] = str(e)

    return result


def execute_approved_paper_trade(
    root: Path,
    strategy_id: str,
    approval_ref: str,
    symbol: str = "NQ",
    side: str = "long",
    quantity: int = 1,
    simulated_price: float = 18250.0,
) -> dict:
    """Execute a paper trade for an approved strategy.

    This calls the Executor lane with full pre-flight checks.
    """
    return execute_paper_trade(
        root=root,
        strategy_id=strategy_id,
        approval_ref=approval_ref,
        symbol=symbol,
        side=side,
        quantity=quantity,
        simulated_price=simulated_price,
    )
