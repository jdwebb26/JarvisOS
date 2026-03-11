#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.risk_tier import evaluate_risk_tier
from runtime.integrations.tradingview_adapter import TradingViewAdapter


TRADINGVIEW_INTENT_ACTION_MAP = {
    "open_tradingview": "open_app",
    "focus_tradingview": "focus_window",
    "set_symbol": "type_into_field",
    "set_timeframe": "type_into_field",
    "capture_chart": "inspect_page",
}

_TRADE_LIKE_INTENTS = {"place_trade", "buy", "sell", "submit_order", "execute_trade"}


def handle_tradingview_command(
    intent: str,
    *,
    query: str = "",
    actor: str,
    lane: str,
    task_id: str = "",
    root=None,
) -> dict:
    del task_id
    resolved_root = Path(root or ROOT).resolve()
    normalized_intent = (intent or "").strip()

    if normalized_intent in _TRADE_LIKE_INTENTS:
        return {
            "kind": "rejected",
            "policy": {"risk_tier": "high", "reason": "trade_execution_not_allowed_in_slice"},
            "result": {
                "integration": "tradingview",
                "intent": normalized_intent,
                "query": query,
                "status": "rejected",
                "reason": "trade_execution_not_allowed_in_slice",
                "mode": "local_stub",
                "actor": actor,
                "lane": lane,
            },
        }

    action_type = TRADINGVIEW_INTENT_ACTION_MAP.get(normalized_intent, "trading_action")
    risk = evaluate_risk_tier(action_type, "tradingview_adapter", {"intent": normalized_intent})

    if normalized_intent not in TRADINGVIEW_INTENT_ACTION_MAP:
        return {
            "kind": "rejected",
            "policy": {"risk_tier": risk["tier"], "reason": "unsupported_tradingview_intent"},
            "result": {
                "integration": "tradingview",
                "intent": normalized_intent,
                "query": query,
                "status": "rejected",
                "reason": "unsupported_tradingview_intent",
                "mode": "local_stub",
                "actor": actor,
                "lane": lane,
            },
        }

    if risk["tier"] == "high":
        return {
            "kind": "rejected",
            "policy": {"risk_tier": risk["tier"], "reason": "tradingview_intent_high_risk_rejected"},
            "result": {
                "integration": "tradingview",
                "intent": normalized_intent,
                "query": query,
                "status": "rejected",
                "reason": "tradingview_intent_high_risk_rejected",
                "mode": "local_stub",
                "actor": actor,
                "lane": lane,
            },
        }

    adapter = TradingViewAdapter()
    result = adapter.handle_command(
        normalized_intent,
        query=query,
        actor=actor,
        lane=lane,
        root=resolved_root,
    )
    return {
        "kind": "accepted",
        "policy": {"risk_tier": risk["tier"], "reason": risk["reason"]},
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Thin TradingView command gateway wrapper.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--intent", required=True, help="TradingView intent")
    parser.add_argument("--query", default="", help="Optional query")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="tradingview", help="Lane name")
    parser.add_argument("--task-id", default="", help="Task id")
    args = parser.parse_args()

    result = handle_tradingview_command(
        args.intent,
        query=args.query,
        actor=args.actor,
        lane=args.lane,
        task_id=args.task_id,
        root=Path(args.root).resolve(),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
