#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import explain_recovery_cycle


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain one operator recovery cycle.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--recovery-cycle-id", default="", help="Recovery cycle id; defaults to latest")
    args = parser.parse_args()

    payload = explain_recovery_cycle(Path(args.root).resolve(), recovery_cycle_id=args.recovery_cycle_id or None)
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
