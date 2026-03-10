#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import inspect_reply_transport_cycle


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain one operator reply transport cycle.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--cycle-id", default="", help="Transport cycle id; defaults to latest")
    args = parser.parse_args()

    payload = inspect_reply_transport_cycle(Path(args.root).resolve(), cycle_id=args.cycle_id or None)
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
