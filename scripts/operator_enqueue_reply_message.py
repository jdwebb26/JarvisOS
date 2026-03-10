#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import new_id, now_iso
from scripts.operator_triage_support import operator_reply_messages_dir


def enqueue_reply_message(
    root: Path,
    *,
    raw_text: str,
    source_kind: str,
    source_lane: str,
    source_channel: str,
    source_message_id: str,
    source_user: str,
    apply: bool,
    preview: bool,
    dry_run: bool,
    continue_on_failure: bool,
) -> dict[str, str | dict]:
    message_id = source_message_id or new_id("opreplymsg")
    payload = {
        "created_at": now_iso(),
        "source_kind": source_kind,
        "source_lane": source_lane,
        "source_channel": source_channel,
        "source_message_id": message_id,
        "source_user": source_user,
        "raw_text": raw_text,
        "apply": apply,
        "preview": preview,
        "dry_run": dry_run,
        "continue_on_failure": continue_on_failure,
    }
    folder = operator_reply_messages_dir(root)
    path = folder / f"{message_id}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"message": payload, "path": str(path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Enqueue one file-backed operator reply message for bounded batch processing.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--raw-text", required=True, help='Raw operator reply text, for example "A1 X2"')
    parser.add_argument("--source-kind", default="cli", help="Inbound source kind")
    parser.add_argument("--source-lane", default="operator", help="Inbound source lane")
    parser.add_argument("--source-channel", default="cli", help="Inbound source channel")
    parser.add_argument("--source-message-id", default="", help="Durable inbound message id")
    parser.add_argument("--source-user", default="operator", help="Inbound operator identity")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-failure", action="store_true")
    args = parser.parse_args()

    result = enqueue_reply_message(
        Path(args.root).resolve(),
        raw_text=args.raw_text,
        source_kind=args.source_kind,
        source_lane=args.source_lane,
        source_channel=args.source_channel,
        source_message_id=args.source_message_id,
        source_user=args.source_user,
        apply=args.apply,
        preview=args.preview,
        dry_run=args.dry_run,
        continue_on_failure=args.continue_on_failure,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
