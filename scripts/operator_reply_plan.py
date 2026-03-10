#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import build_reply_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a compact operator reply string into a durable plan without executing it.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--reply", required=True, help='Reply string such as "A1 X2"')
    args = parser.parse_args()

    payload = build_reply_plan(Path(args.root).resolve(), reply_string=args.reply)
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
