#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import explain_operator_doctor_issue


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain one operator doctor issue code in current context.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--issue-code", required=True, help="Doctor issue code to explain")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    payload = explain_operator_doctor_issue(Path(args.root).resolve(), issue_code=args.issue_code, limit=args.limit)
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
