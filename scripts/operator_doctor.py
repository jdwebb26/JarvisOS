#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import create_operator_doctor_report, triage_logs_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a compact operator doctor report over the saved control-plane state.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    report = create_operator_doctor_report(root, limit=args.limit)
    payload = {
        "report": report,
        "json_path": str(triage_logs_dir(root) / "operator_doctor_latest.json"),
        "markdown_path": str(triage_logs_dir(root) / "operator_doctor_latest.md"),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
