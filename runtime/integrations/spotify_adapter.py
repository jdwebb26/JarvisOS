#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_INTENTS = {
    "play",
    "pause",
    "next_track",
    "previous_track",
    "set_volume",
    "open_spotify",
}


class SpotifyAdapter:
    def __init__(self, config: dict | None = None):
        self.config = dict(config or {})

    def health_check(self) -> dict[str, Any]:
        return {
            "integration": "spotify",
            "status": "stubbed",
            "reason": "spotify_api_not_connected",
            "mode": "local_stub",
            "config": dict(self.config),
        }

    def handle_command(
        self,
        intent: str,
        *,
        query: str = "",
        actor: str = "operator",
        lane: str = "spotify",
        root=None,
    ) -> dict[str, Any]:
        del root
        normalized_intent = (intent or "").strip()
        if normalized_intent not in SUPPORTED_INTENTS:
            return {
                "integration": "spotify",
                "intent": normalized_intent,
                "query": query,
                "status": "rejected",
                "reason": "unsupported_spotify_intent",
                "mode": "local_stub",
                "actor": actor,
                "lane": lane,
            }
        return {
            "integration": "spotify",
            "intent": normalized_intent,
            "query": query,
            "status": "accepted",
            "reason": "spotify_adapter_stubbed",
            "mode": "local_stub",
            "actor": actor,
            "lane": lane,
        }
