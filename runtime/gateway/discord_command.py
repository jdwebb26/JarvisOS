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
from runtime.integrations.discord_adapter import DiscordAdapter


DISCORD_INTENT_ACTION_MAP = {
    "open_discord": "open_app",
    "focus_discord": "focus_window",
    "open_server": "show_status",
    "open_channel": "show_status",
    "draft_message": "create_draft_artifact",
}


def handle_discord_command(
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
    action_type = DISCORD_INTENT_ACTION_MAP.get(normalized_intent, "send_external_message")
    risk = evaluate_risk_tier(action_type, "discord_adapter", {"intent": normalized_intent})

    if normalized_intent not in DISCORD_INTENT_ACTION_MAP:
        return {
            "kind": "rejected",
            "control_note": "discord_specific_control_action_not_added_in_this_slice",
            "policy": {"risk_tier": risk["tier"], "reason": "unsupported_discord_intent"},
            "result": {
                "integration": "discord",
                "intent": normalized_intent,
                "query": query,
                "status": "rejected",
                "reason": "unsupported_discord_intent",
                "mode": "local_stub",
                "actor": actor,
                "lane": lane,
            },
        }

    if risk["tier"] == "high":
        return {
            "kind": "rejected",
            "control_note": "discord_specific_control_action_not_added_in_this_slice",
            "policy": {"risk_tier": risk["tier"], "reason": "discord_intent_high_risk_rejected"},
            "result": {
                "integration": "discord",
                "intent": normalized_intent,
                "query": query,
                "status": "rejected",
                "reason": "discord_intent_high_risk_rejected",
                "mode": "local_stub",
                "actor": actor,
                "lane": lane,
            },
        }

    adapter = DiscordAdapter()
    result = adapter.handle_command(
        normalized_intent,
        query=query,
        actor=actor,
        lane=lane,
        root=resolved_root,
    )
    return {
        "kind": "accepted",
        "control_note": "discord_specific_control_action_not_added_in_this_slice",
        "policy": {"risk_tier": risk["tier"], "reason": risk["reason"]},
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Thin Discord command gateway wrapper.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--intent", required=True, help="Discord intent")
    parser.add_argument("--query", default="", help="Optional query")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="discord", help="Lane name")
    parser.add_argument("--task-id", default="", help="Task id")
    args = parser.parse_args()

    result = handle_discord_command(
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
