#!/usr/bin/env python3
"""Cron-friendly cadence wrapper: checkpoint → compare → prune.

Intended for periodic invocation (e.g. every 30 minutes via cron).
Creates a new control-plane checkpoint, compares it against the previous one,
and prunes old checkpoints and compare-history files that exceed retention.

Usage:
    python3 scripts/operator_checkpoint_cadence.py                     # defaults
    python3 scripts/operator_checkpoint_cadence.py --keep-checkpoints 50
    python3 scripts/operator_checkpoint_cadence.py --keep-compare 50
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import (
    build_control_plane_checkpoint,
    compare_control_plane_checkpoints,
    prune_compare_history,
    prune_control_plane_checkpoints,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cron-friendly checkpoint cadence: create → compare → prune.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--keep-checkpoints", type=int, default=30, help="Max checkpoint records to retain (default 30)")
    parser.add_argument("--keep-compare", type=int, default=30, help="Max compare-history log files to retain (default 30)")
    parser.add_argument("--limit", type=int, default=5, help="Limit for inbox/subsystem queries inside checkpoint builder")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    checkpoint = build_control_plane_checkpoint(root, limit=args.limit)
    compare = compare_control_plane_checkpoints(root)
    pruned_checkpoints = prune_control_plane_checkpoints(root, keep=args.keep_checkpoints)
    pruned_compare = prune_compare_history(root, keep=args.keep_compare)

    print(json.dumps({
        "ok": True,
        "checkpoint_id": checkpoint["control_plane_checkpoint_id"],
        "compare": {
            "current": compare.get("current_checkpoint_id"),
            "other": compare.get("other_checkpoint_id"),
            "any_change": any(compare.get("changed_flags", {}).values()),
        },
        "pruned_checkpoints": pruned_checkpoints,
        "pruned_compare": pruned_compare,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
