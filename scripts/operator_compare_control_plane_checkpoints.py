#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import compare_control_plane_checkpoints


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare one operator control-plane checkpoint against another or against the previous checkpoint.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--checkpoint-id", default="", help="Current checkpoint id; defaults to latest")
    parser.add_argument("--other-checkpoint-id", default="", help="Other checkpoint id; defaults to previous")
    args = parser.parse_args()

    payload = compare_control_plane_checkpoints(
        Path(args.root).resolve(),
        checkpoint_id=args.checkpoint_id or None,
        other_checkpoint_id=args.other_checkpoint_id or None,
    )
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("current_checkpoint_id") or payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
