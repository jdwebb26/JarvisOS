#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import compare_triage_snapshots


def _load_triage(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_triage(root: Path, *, other_triage_path: Path | None) -> dict:
    current_path = root / "state" / "logs" / "operator_triage_pack.json"
    current = _load_triage(current_path)
    other = _load_triage(other_triage_path) if other_triage_path else None
    result = compare_triage_snapshots(current, other)
    latest_path = root / "state" / "logs" / "operator_compare_triage_latest.json"
    latest_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare the current triage pack against another triage snapshot.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--other-triage-path", default="", help="Saved triage JSON path to compare against")
    args = parser.parse_args()
    payload = compare_triage(
        Path(args.root).resolve(),
        other_triage_path=Path(args.other_triage_path).resolve() if args.other_triage_path else None,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
