#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


SUPPORTED_INTENTS = {
    "open_discord",
    "focus_discord",
    "open_server",
    "open_channel",
    "draft_message",
}


class DiscordAdapter:
    def __init__(self, config: dict | None = None):
        self.config = dict(config or {})

    def health_check(self) -> dict[str, Any]:
        return {
            "integration": "discord",
            "status": "stubbed",
            "reason": "discord_api_not_connected",
            "mode": "local_stub",
            "config": dict(self.config),
        }

    def handle_command(
        self,
        intent: str,
        *,
        query: str = "",
        actor: str = "operator",
        lane: str = "discord",
        root=None,
    ) -> dict[str, Any]:
        del root
        normalized_intent = (intent or "").strip()
        if normalized_intent not in SUPPORTED_INTENTS:
            return {
                "integration": "discord",
                "intent": normalized_intent,
                "query": query,
                "status": "rejected",
                "reason": "unsupported_discord_intent",
                "mode": "local_stub",
                "actor": actor,
                "lane": lane,
            }
        return {
            "integration": "discord",
            "intent": normalized_intent,
            "query": query,
            "status": "accepted",
            "reason": "discord_adapter_stubbed",
            "mode": "local_stub",
            "actor": actor,
            "lane": lane,
        }
