#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import execute_operator_recovery_cycle


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded operator recovery cycle over the saved doctor/remediation state.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--live", action="store_true", help="Execute remediation live instead of the default dry-run-safe mode")
    parser.add_argument("--skip-remediation", action="store_true", help="Build doctor/report state only without running remediation")
    parser.add_argument("--continue-on-failure", action="store_true")
    parser.add_argument("--skip-handoff-refresh", action="store_true", help="Do not refresh the handoff artifact at the end of the cycle")
    args = parser.parse_args()

    payload, exit_code = execute_operator_recovery_cycle(
        Path(args.root).resolve(),
        dry_run=not args.live,
        continue_on_failure=args.continue_on_failure,
        execute_remediation=not args.skip_remediation,
        refresh_handoff=not args.skip_handoff_refresh,
    )
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
