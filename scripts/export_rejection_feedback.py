#!/usr/bin/env python3
"""Export rejection feedback snapshots for Atlas, Fish, and Kitt.

Usage:
    python3 scripts/export_rejection_feedback.py [--state-dir STATE_DIR]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.quant.rejection_ledger import RejectionLedger
from runtime.quant.rejection_feedback import export_feedback


def main() -> None:
    parser = argparse.ArgumentParser(description="Export rejection feedback")
    parser.add_argument("--state-dir", type=Path, default=None, help="Override state directory")
    args = parser.parse_args()

    ledger = RejectionLedger(args.state_dir) if args.state_dir else RejectionLedger()
    count = ledger.count()

    if count == 0:
        print("No rejection records found. Run the normalizer first.")
        print(f"  State dir: {ledger.state_dir}")
        return

    paths = export_feedback(ledger=ledger)

    print(f"Exported feedback from {count} rejection records:")
    for name, path in paths.items():
        print(f"  {name}: {path}")

    # Print the markdown summary to stdout
    md_path = paths.get("md")
    if md_path and md_path.exists():
        print("\n" + "=" * 60)
        print(md_path.read_text())


if __name__ == "__main__":
    main()
