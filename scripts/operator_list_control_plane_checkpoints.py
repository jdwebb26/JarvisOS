#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import list_control_plane_checkpoints_view


def main() -> int:
    parser = argparse.ArgumentParser(description="List recent operator control-plane checkpoints.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    print(json.dumps(list_control_plane_checkpoints_view(Path(args.root).resolve(), limit=args.limit), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
