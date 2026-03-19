"""Shared helper: resolve the live-approval state for a LIVE_QUEUED strategy.

This is the single source of truth for all operator surfaces that need to
display what state a LIVE_QUEUED strategy's live-trade approval is in and
what operator action is needed next.

Callers: quant_lanes.py, brief_producer.py, operator_status.py
"""
from __future__ import annotations


def resolve_live_approval_state(strategy_id: str, approvals) -> dict:
    """Resolve the live-approval state for a LIVE_QUEUED strategy.

    *approvals* is an iterable of ApprovalObject instances (from
    ``load_all_approvals``).

    Returns ``{state, approval_ref, action, label}`` where *state* is one of:
    ``no_request``, ``pending``, ``approved``, ``revoked``, ``expired``.
    """
    live_approvals = [
        a for a in approvals
        if a.strategy_id == strategy_id and a.approval_type == "live_trade"
    ]

    if not live_approvals:
        return {
            "state": "no_request",
            "approval_ref": None,
            "action": f"request-live {strategy_id}",
            "label": "needs live_trade approval request",
        }

    latest = live_approvals[-1]

    if latest.revoked:
        return {
            "state": "revoked",
            "approval_ref": latest.approval_ref,
            "action": f"request-live {strategy_id}",
            "label": f"live approval revoked ({latest.approval_ref})",
        }

    # Check for pending operator review before time-window validity so that
    # a pending approval is never misclassified as expired.
    if getattr(latest, "decision_status", None) == "pending":
        return {
            "state": "pending",
            "approval_ref": latest.approval_ref,
            "action": f"approve {latest.approval_ref}",
            "label": f"live approval pending review ({latest.approval_ref})",
        }

    valid, _reason = latest.is_valid()
    if not valid:
        return {
            "state": "expired",
            "approval_ref": latest.approval_ref,
            "action": f"request-live {strategy_id}",
            "label": f"live approval expired ({latest.approval_ref})",
        }

    return {
        "state": "approved",
        "approval_ref": latest.approval_ref,
        "action": f"execute-live {strategy_id} --approval-ref {latest.approval_ref}",
        "label": f"live-approved, ready for execute-live ({latest.approval_ref})",
    }
