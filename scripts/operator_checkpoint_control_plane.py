#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import build_control_plane_checkpoint, operator_control_plane_checkpoints_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture one compact operator control-plane checkpoint from saved state.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    checkpoint = build_control_plane_checkpoint(root, limit=args.limit)
    payload = {
        "checkpoint": checkpoint,
        "path": str(operator_control_plane_checkpoints_dir(root) / f"{checkpoint['control_plane_checkpoint_id']}.json"),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
