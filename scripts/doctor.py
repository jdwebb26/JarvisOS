#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bootstrap import resolve_repo_root
from scripts.preflight_lib import ROOT as DEFAULT_ROOT, build_doctor_report, render_doctor_report, write_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Operator-facing deployment/runtime triage for Jarvis v5.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Project root path")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    root = resolve_repo_root(Path(args.root))
    report = build_doctor_report(root)
    write_report(root, "doctor_report.json", report)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_doctor_report(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
