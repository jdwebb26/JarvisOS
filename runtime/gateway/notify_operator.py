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
from runtime.integrations.notification_adapter import NotificationAdapter, SUPPORTED_CHANNELS


CHANNEL_ACTION_MAP = {
    "voice": "show_status",
    "dashboard": "show_status",
    "discord_stub": "create_draft_artifact",
    "mobile_stub": "show_status",
}


def handle_operator_notification(
    channel: str,
    message: str,
    *,
    actor: str,
    lane: str,
    priority: str = "normal",
    root=None,
) -> dict:
    resolved_root = Path(root or ROOT).resolve()
    normalized_channel = (channel or "").strip()
    action_type = CHANNEL_ACTION_MAP.get(normalized_channel, "send_external_message")
    risk = evaluate_risk_tier(action_type, "notification_adapter", {"channel": normalized_channel, "priority": priority})

    if normalized_channel not in SUPPORTED_CHANNELS:
        return {
            "kind": "rejected",
            "policy": {
                "risk_tier": risk["tier"],
                "reason": "unsupported_notification_channel",
            },
            "result": {
                "integration": "notification",
                "channel": normalized_channel,
                "message": message,
                "status": "rejected",
                "reason": "unsupported_notification_channel",
                "mode": "local_stub",
                "actor": actor,
                "lane": lane,
                "priority": priority,
            },
        }

    if risk["tier"] == "high":
        return {
            "kind": "rejected",
            "policy": {
                "risk_tier": risk["tier"],
                "reason": "notification_channel_high_risk_rejected",
            },
            "result": {
                "integration": "notification",
                "channel": normalized_channel,
                "message": message,
                "status": "rejected",
                "reason": "notification_channel_high_risk_rejected",
                "mode": "local_stub",
                "actor": actor,
                "lane": lane,
                "priority": priority,
            },
        }

    adapter = NotificationAdapter()
    result = adapter.send_notification(
        normalized_channel,
        message,
        actor=actor,
        lane=lane,
        priority=priority,
        root=resolved_root,
    )
    return {
        "kind": "accepted",
        "policy": {
            "risk_tier": risk["tier"],
            "reason": risk["reason"],
        },
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Thin operator notification gateway wrapper.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--channel", required=True, help="Notification channel")
    parser.add_argument("--message", required=True, help="Notification message")
    parser.add_argument("--actor", default="system", help="Actor name")
    parser.add_argument("--lane", default="notify", help="Lane name")
    parser.add_argument("--priority", default="normal", help="Notification priority")
    args = parser.parse_args()

    result = handle_operator_notification(
        args.channel,
        args.message,
        actor=args.actor,
        lane=args.lane,
        priority=args.priority,
        root=Path(args.root).resolve(),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
