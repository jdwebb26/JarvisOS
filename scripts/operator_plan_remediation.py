#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import build_operator_remediation_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a bounded operator remediation plan from current saved state only.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    payload = {"plan": build_operator_remediation_plan(Path(args.root).resolve(), limit=args.limit)}
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
