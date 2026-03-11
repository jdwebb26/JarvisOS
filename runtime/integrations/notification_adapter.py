#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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


def build_notification_summary(root=None) -> dict[str, Any]:
    del root
    return {
        "notification_capability_present": True,
        "supported_channels": sorted(SUPPORTED_CHANNELS),
        "stubbed_only": True,
        "voice_route_supported": True,
        "notes": [
            "Notification delivery remains stubbed in this slice.",
            "Voice commands can preview or explicitly route into the bounded notification gateway.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the notification adapter summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_notification_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
