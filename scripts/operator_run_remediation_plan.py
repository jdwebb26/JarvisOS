#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import execute_remediation_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute one bounded operator remediation plan through existing wrapper scripts only.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--plan-id", default="", help="Remediation plan id; defaults to latest")
    parser.add_argument("--step-index", type=int, default=None, help="Optional step index to execute from the plan")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-failure", action="store_true")
    args = parser.parse_args()

    payload, exit_code = execute_remediation_plan(
        Path(args.root).resolve(),
        plan_id=args.plan_id or None,
        step_index=args.step_index,
        dry_run=args.dry_run,
        continue_on_failure=args.continue_on_failure,
    )
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
