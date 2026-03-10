#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import list_reply_transport_cycles_view


def main() -> int:
    parser = argparse.ArgumentParser(description="List compact recent operator reply transport cycles.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--failed-only", action="store_true")
    parser.add_argument("--mode", choices=["plan", "preview", "apply"], default="")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    payload = list_reply_transport_cycles_view(
        Path(args.root).resolve(),
        limit=args.limit,
        failed_only=args.failed_only,
        mode=args.mode or None,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
