#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import execute_bridge_replay


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a prior gateway/operator bridge cycle through the existing bridge/reply wrappers only.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--cycle-id", required=True, help="Bridge cycle id to replay")
    parser.add_argument("--plan-only", action="store_true", help="Build and persist the bridge replay plan without executing it")
    parser.add_argument("--live-apply", action="store_true", help="Allow live apply replay when the source cycle was apply-mode")
    parser.add_argument("--continue-on-failure", action="store_true")
    args = parser.parse_args()

    payload, exit_code = execute_bridge_replay(
        Path(args.root).resolve(),
        cycle_id=args.cycle_id,
        plan_only=args.plan_only,
        live_apply=args.live_apply,
        continue_on_failure=args.continue_on_failure,
    )
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
