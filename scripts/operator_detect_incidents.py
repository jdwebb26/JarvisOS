#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import detect_operator_incidents, operator_incident_reports_dir, operator_incident_snapshots_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect compact operator control-plane incidents from saved state only.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    payload = detect_operator_incidents(root, limit=args.limit)
    print(
        json.dumps(
            {
                "report": payload["report"],
                "snapshot": payload["snapshot"],
                "report_path": str(operator_incident_reports_dir(root) / f"{payload['report']['incident_report_id']}.json"),
                "snapshot_path": str(operator_incident_snapshots_dir(root) / f"{payload['snapshot']['incident_snapshot_id']}.json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
