#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import import_gateway_reply_message


def main() -> int:
    parser = argparse.ArgumentParser(description="Import one bounded gateway-style operator reply payload into the file-backed reply queue.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--raw-text", required=True, help='Raw operator text, for example "A1"')
    parser.add_argument("--source-kind", default="gateway", help="Source kind")
    parser.add_argument("--source-lane", default="operator", help="Source lane")
    parser.add_argument("--source-channel", default="gateway", help="Source channel")
    parser.add_argument("--source-message-id", default="", help="Source message id")
    parser.add_argument("--source-user", default="operator", help="Source user")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-failure", action="store_true")
    args = parser.parse_args()

    payload = import_gateway_reply_message(
        Path(args.root).resolve(),
        payload={
            "raw_text": args.raw_text,
            "source_kind": args.source_kind,
            "source_lane": args.source_lane,
            "source_channel": args.source_channel,
            "source_message_id": args.source_message_id,
            "source_user": args.source_user,
            "apply": args.apply,
            "preview": args.preview,
            "dry_run": args.dry_run,
            "continue_on_failure": args.continue_on_failure,
        },
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
