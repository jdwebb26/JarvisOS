#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import compare_bridge_cycles


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare one gateway/operator bridge cycle against another or against the previous cycle.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--cycle-id", default="", help="Current bridge cycle id; defaults to latest")
    parser.add_argument("--other-cycle-id", default="", help="Other bridge cycle id; defaults to previous")
    args = parser.parse_args()

    payload = compare_bridge_cycles(
        Path(args.root).resolve(),
        current_cycle_id=args.cycle_id or None,
        other_cycle_id=args.other_cycle_id or None,
    )
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("current_bridge_cycle_id") or payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
