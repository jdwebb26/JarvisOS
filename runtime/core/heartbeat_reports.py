#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import HeartbeatReportRecord, HeartbeatStatus, new_id, now_iso


def heartbeat_reports_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "heartbeat_reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(heartbeat_report_id: str, *, root: Optional[Path] = None) -> Path:
    return heartbeat_reports_dir(root) / f"{heartbeat_report_id}.json"


def save_heartbeat_report(record: HeartbeatReportRecord, *, root: Optional[Path] = None) -> HeartbeatReportRecord:
    record.updated_at = now_iso()
    _path(record.heartbeat_report_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def list_heartbeat_reports(*, root: Optional[Path] = None) -> list[HeartbeatReportRecord]:
    rows: list[HeartbeatReportRecord] = []
    for path in heartbeat_reports_dir(root).glob("*.json"):
        try:
            rows.append(HeartbeatReportRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: (row.updated_at, row.created_at), reverse=True)
    return rows


def list_latest_heartbeat_reports_by_subsystem(*, root: Optional[Path] = None) -> list[HeartbeatReportRecord]:
    latest: dict[str, HeartbeatReportRecord] = {}
    for row in list_heartbeat_reports(root=root):
        current = latest.get(row.subsystem_name)
        if current is None or (row.updated_at, row.created_at) > (current.updated_at, current.created_at):
            latest[row.subsystem_name] = row
    return sorted(latest.values(), key=lambda row: row.subsystem_name)


def build_heartbeat_report_summary(*, root: Optional[Path] = None) -> dict:
    all_rows = list_heartbeat_reports(root=root)
    latest = list_latest_heartbeat_reports_by_subsystem(root=root)
    counts: dict[str, int] = {}
    for row in latest:
        counts[row.status] = counts.get(row.status, 0) + 1
    overall_status = HeartbeatStatus.HEALTHY.value
    if counts.get(HeartbeatStatus.UNREACHABLE.value):
        overall_status = HeartbeatStatus.UNREACHABLE.value
    elif counts.get(HeartbeatStatus.STOPPED.value):
        overall_status = HeartbeatStatus.STOPPED.value
    elif counts.get(HeartbeatStatus.DEGRADED.value):
        overall_status = HeartbeatStatus.DEGRADED.value
    return {
        "heartbeat_report_count": len(list_heartbeat_reports(root=root)),
        "latest_subsystem_heartbeat_count": len(latest),
        "heartbeat_status_counts": counts,
        "overall_heartbeat_status": overall_status,
        "latest_heartbeats": [row.to_dict() for row in latest],
        "latest_heartbeat_report": all_rows[0].to_dict() if all_rows else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current durable HeartbeatReport summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_heartbeat_report_summary(root=Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
