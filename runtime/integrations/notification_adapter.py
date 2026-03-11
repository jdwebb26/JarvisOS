#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


SUPPORTED_CHANNELS = {
    "voice",
    "dashboard",
    "discord_stub",
    "mobile_stub",
}


class NotificationAdapter:
    def __init__(self, config: dict | None = None):
        self.config = dict(config or {})

    def health_check(self) -> dict[str, Any]:
        return {
            "integration": "notification",
            "status": "stubbed",
            "reason": "notification_delivery_not_connected",
            "mode": "local_stub",
            "config": dict(self.config),
        }

    def send_notification(
        self,
        channel: str,
        message: str,
        *,
        actor: str = "system",
        lane: str = "notify",
        priority: str = "normal",
        root=None,
    ) -> dict[str, Any]:
        del root
        normalized_channel = (channel or "").strip()
        if normalized_channel not in SUPPORTED_CHANNELS:
            return {
                "integration": "notification",
                "channel": normalized_channel,
                "message": message,
                "status": "rejected",
                "reason": "unsupported_notification_channel",
                "mode": "local_stub",
                "actor": actor,
                "lane": lane,
                "priority": priority,
            }

        return {
            "integration": "notification",
            "channel": normalized_channel,
            "message": message,
            "status": "accepted",
            "reason": "notification_adapter_stubbed",
            "mode": "local_stub",
            "actor": actor,
            "lane": lane,
            "priority": priority,
        }
