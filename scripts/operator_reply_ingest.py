#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import ingest_operator_reply


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest one compact operator reply/message into the durable reply bridge.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--reply", required=True, help='Raw inbound operator message, for example "A1 X2"')
    parser.add_argument("--source-kind", default="cli", help="Inbound source kind")
    parser.add_argument("--source-lane", default="operator", help="Inbound source lane")
    parser.add_argument("--source-channel", default="cli", help="Inbound source channel")
    parser.add_argument("--source-message-id", default="", help="Durable inbound message id")
    parser.add_argument("--source-user", default="operator", help="Inbound operator identity")
    parser.add_argument("--preview", action="store_true", help="Resolve the reply and return preview data only")
    parser.add_argument("--apply", action="store_true", help="Resolve the reply and apply it through existing wrappers")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run the apply path")
    parser.add_argument("--continue-on-failure", action="store_true", help="Continue reply application after a failed step")
    parser.add_argument("--force-duplicate", action="store_true", help="Allow the same source_message_id to be processed again")
    args = parser.parse_args()

    mode = "apply" if args.apply else "preview" if args.preview else "plan"
    payload, exit_code = ingest_operator_reply(
        Path(args.root).resolve(),
        raw_text=args.reply,
        source_kind=args.source_kind,
        source_lane=args.source_lane,
        source_channel=args.source_channel,
        source_message_id=args.source_message_id,
        source_user=args.source_user,
        mode=mode,
        dry_run=args.dry_run,
        continue_on_failure=args.continue_on_failure,
        force_duplicate=args.force_duplicate,
    )
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
