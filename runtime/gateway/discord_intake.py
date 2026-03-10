#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.intake import create_task_from_message
from runtime.core.status import summarize_status
from runtime.gateway.acknowledgements import (
    chat_only_ack,
    duplicate_task_ack,
    status_ack,
    task_created_ack,
)


STATUS_PATTERNS = [
    "what is running",
    "whats running",
    "what's running",
    "status",
]


def looks_like_status_request(text: str) -> bool:
    lowered = text.strip().lower()
    return any(pattern in lowered for pattern in STATUS_PATTERNS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway wrapper for jarvis chat intake.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--text", required=True, help="Incoming message text")
    parser.add_argument("--user", default="operator", help="Source user")
    parser.add_argument("--lane", default="jarvis", help="Source lane")
    parser.add_argument("--channel", default="jarvis", help="Source channel")
    parser.add_argument("--message-id", default="manual_cli", help="Message id")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    text = args.text

    if looks_like_status_request(text):
        summary = summarize_status(root=root)
        ack = status_ack(summary)
        print(json.dumps({"kind": "status_response", "summary": summary, "ack": ack}, indent=2))
        return 0

    result = create_task_from_message(
        text=text,
        user=args.user,
        lane=args.lane,
        channel=args.channel,
        message_id=args.message_id,
        root=root,
    )

    if result["kind"] == "task_created":
        ack = task_created_ack(result)
        print(json.dumps({"kind": "task_created_response", "result": result, "ack": ack}, indent=2))
        return 0

    if result["kind"] == "duplicate_task_existing":
        ack = duplicate_task_ack(result)
        print(json.dumps({"kind": "duplicate_task_response", "result": result, "ack": ack}, indent=2))
        return 0

    ack = chat_only_ack()
    print(json.dumps({"kind": "chat_only_response", "result": result, "ack": ack}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
