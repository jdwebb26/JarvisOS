#!/usr/bin/env python3
"""Build family and regime scoreboards from the rejection ledger.

Usage:
    python3 scripts/build_rejection_scoreboard.py [--state-dir STATE_DIR]
"""

import argparse
import json
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.quant.rejection_ledger import RejectionLedger
from runtime.quant.rejection_scoreboard import write_scoreboards


def main() -> None:
    parser = argparse.ArgumentParser(description="Build rejection scoreboards")
    parser.add_argument("--state-dir", type=Path, default=None, help="Override state directory")
    args = parser.parse_args()

    ledger = RejectionLedger(args.state_dir) if args.state_dir else RejectionLedger()
    count = ledger.count()

    if count == 0:
        print("No rejection records found. Run the normalizer first.")
        print(f"  State dir: {ledger.state_dir}")
        return

    paths = write_scoreboards(ledger=ledger)

    print(f"Built scoreboards from {count} rejection records:")
    for name, path in paths.items():
        data = json.loads(path.read_text())
        key = next((k for k in ("total_families", "total_regimes", "total_rejections") if k in data), None)
        detail = f" ({data[key]} entries)" if key else ""
        print(f"  {name}: {path}{detail}")


if __name__ == "__main__":
    main()
