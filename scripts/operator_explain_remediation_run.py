#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import explain_remediation_run


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain one operator remediation run in compact JSON.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--run-id", default="", help="Remediation run id; defaults to latest")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    payload = explain_remediation_run(Path(args.root).resolve(), run_id=args.run_id or None, limit=args.limit)
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
