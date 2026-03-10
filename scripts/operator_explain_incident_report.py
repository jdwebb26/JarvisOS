#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import explain_incident_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain one operator incident report.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--report-id", default="", help="Incident report id; defaults to latest")
    args = parser.parse_args()

    payload = explain_incident_report(Path(args.root).resolve(), report_id=args.report_id or None)
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
