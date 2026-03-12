#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.dashboard.status_names import normalize_status_name


def _safe_load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _pick(record: dict, key: str):
    details = record.get("details", {})
    if isinstance(details, dict) and key in details:
        return details.get(key)
    return record.get(key)


def build_event_board(root: Path, limit: int = 50) -> dict:
    events_dir = root / "state" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for path in events_dir.glob("*.json"):
        record = _safe_load(path)
        if not record:
            continue

        rows.append(
            {
                "event_id": record.get("event_id"),
                "task_id": record.get("task_id"),
                "event_type": record.get("event_type"),
                "actor": record.get("actor"),
                "lane": record.get("lane"),
                "created_at": record.get("created_at"),
                "from_status": normalize_status_name(_pick(record, "from_status")),
                "to_status": normalize_status_name(_pick(record, "to_status")),
                "from_lifecycle_state": _pick(record, "from_lifecycle_state"),
                "to_lifecycle_state": _pick(record, "to_lifecycle_state"),
                "checkpoint_summary": _pick(record, "checkpoint_summary"),
                "reason": _pick(record, "reason"),
                "final_outcome": _pick(record, "final_outcome"),
                "artifact_id": _pick(record, "artifact_id"),
                "artifact_type": _pick(record, "artifact_type"),
                "artifact_title": _pick(record, "artifact_title") or _pick(record, "title"),
                "execution_backend": _pick(record, "execution_backend"),
                "backend_run_id": _pick(record, "backend_run_id"),
                "producer_metadata": {
                    "actor": record.get("actor"),
                    "lane": record.get("lane"),
                    "execution_backend": _pick(record, "execution_backend"),
                },
                "evidence_metadata": {
                    "artifact_id": _pick(record, "artifact_id"),
                    "backend_run_id": _pick(record, "backend_run_id"),
                },
                "provenance_metadata": {
                    "from_status": normalize_status_name(_pick(record, "from_status")),
                    "to_status": normalize_status_name(_pick(record, "to_status")),
                },
                "already_linked": _pick(record, "already_linked"),
            }
        )

    rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
    rows = rows[:limit]

    result = {
        "rows": rows,
        "total": len(rows),
    }

    out_path = root / "state" / "logs" / "event_board.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a recent task event board.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=50, help="Max number of events")
    args = parser.parse_args()

    result = build_event_board(Path(args.root).resolve(), limit=args.limit)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
