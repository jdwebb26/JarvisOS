#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.integrations.openclaw_sessions import (
    build_openclaw_discord_session_integrity_summary,
    repair_discord_sessions,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and repair malformed external OpenClaw Discord sessions.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--openclaw-root", default="")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--session-key", default="")
    parser.add_argument("--repair-all-malformed", action="store_true")
    parser.add_argument("--repair", action="store_true", help="Apply the repair instead of dry-run only.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    openclaw_root = Path(args.openclaw_root).expanduser().resolve() if args.openclaw_root else None
    if not (args.repair_all_malformed or args.session_id or args.session_key):
        report = build_openclaw_discord_session_integrity_summary(repo_root=root, openclaw_root=openclaw_root)
    else:
        report = repair_discord_sessions(
            repo_root=root,
            openclaw_root=openclaw_root,
            session_id=args.session_id,
            session_key=args.session_key,
            repair_all_malformed=args.repair_all_malformed,
            apply=args.repair,
        )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(json.dumps(report, indent=2))
    if report.get("malformed_session_count"):
        return 1
    if report.get("applied"):
        return 0
    if report.get("target_count", 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
