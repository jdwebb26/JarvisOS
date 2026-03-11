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

from runtime.core.models import BackendAssignmentRecord, now_iso


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def backend_assignments_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("backend_assignments", root=root)


def _path(record_id: str, root: Optional[Path] = None) -> Path:
    return backend_assignments_dir(root=root) / f"{record_id}.json"


def save_backend_assignment(record: BackendAssignmentRecord, *, root: Optional[Path] = None) -> BackendAssignmentRecord:
    record.updated_at = now_iso()
    _path(record.backend_assignment_id, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_backend_assignment(backend_assignment_id: str, *, root: Optional[Path] = None) -> Optional[BackendAssignmentRecord]:
    path = _path(backend_assignment_id, root=root)
    if not path.exists():
        return None
    return BackendAssignmentRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_backend_assignments(root: Optional[Path] = None) -> list[BackendAssignmentRecord]:
    rows: list[BackendAssignmentRecord] = []
    for path in sorted(backend_assignments_dir(root=root).glob("*.json")):
        try:
            rows.append(BackendAssignmentRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def latest_backend_assignment(root: Optional[Path] = None) -> Optional[BackendAssignmentRecord]:
    rows = list_backend_assignments(root=root)
    return rows[0] if rows else None


def build_backend_assignment_summary(root: Optional[Path] = None) -> dict:
    rows = list_backend_assignments(root=root)
    provider_counts: dict[str, int] = {}
    backend_counts: dict[str, int] = {}
    for row in rows:
        provider_counts[row.provider_id] = provider_counts.get(row.provider_id, 0) + 1
        backend_counts[row.execution_backend] = backend_counts.get(row.execution_backend, 0) + 1
    return {
        "backend_assignment_count": len(rows),
        "provider_counts": provider_counts,
        "execution_backend_counts": backend_counts,
        "latest_backend_assignment": rows[0].to_dict() if rows else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current backend assignment summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_backend_assignment_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
