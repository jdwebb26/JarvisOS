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
from scripts.preflight_lib import ROOT as DEFAULT_ROOT, render_validate_report, run_validate, write_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Repo-local preflight validation for Jarvis v5.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Project root path")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as blocking failures.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    root = resolve_repo_root(Path(args.root))
    report = run_validate(root, strict=args.strict)
    write_report(root, "validate_report.json", report)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_validate_report(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
