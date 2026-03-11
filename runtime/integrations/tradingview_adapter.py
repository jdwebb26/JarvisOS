#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


SUPPORTED_INTENTS = {
    "open_tradingview",
    "focus_tradingview",
    "set_symbol",
    "set_timeframe",
    "capture_chart",
}


class TradingViewAdapter:
    def __init__(self, config: dict | None = None):
        self.config = dict(config or {})

    def health_check(self) -> dict[str, Any]:
        return {
            "integration": "tradingview",
            "status": "stubbed",
            "reason": "tradingview_automation_not_connected",
            "mode": "local_stub",
            "config": dict(self.config),
        }

    def handle_command(
        self,
        intent: str,
        *,
        query: str = "",
        actor: str = "operator",
        lane: str = "tradingview",
        root=None,
    ) -> dict[str, Any]:
        del root
        normalized_intent = (intent or "").strip()
        if normalized_intent not in SUPPORTED_INTENTS:
            return {
                "integration": "tradingview",
                "intent": normalized_intent,
                "query": query,
                "status": "rejected",
                "reason": "unsupported_tradingview_intent",
                "mode": "local_stub",
                "actor": actor,
                "lane": lane,
            }
        return {
            "integration": "tradingview",
            "intent": normalized_intent,
            "query": query,
            "status": "accepted",
            "reason": "tradingview_adapter_stubbed",
            "mode": "local_stub",
            "actor": actor,
            "lane": lane,
        }
