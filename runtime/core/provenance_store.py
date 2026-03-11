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

from runtime.core.models import (
    ArtifactProvenanceRecord,
    DecisionProvenanceRecord,
    MemoryProvenanceRecord,
    PublishProvenanceRecord,
    RollbackProvenanceRecord,
    RoutingProvenanceRecord,
    TaskProvenanceRecord,
    now_iso,
)


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def task_provenance_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("task_provenance", root=root)


def artifact_provenance_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("artifact_provenance", root=root)


def routing_provenance_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("routing_provenance", root=root)


def decision_provenance_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("decision_provenance", root=root)


def publish_provenance_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("publish_provenance", root=root)


def rollback_provenance_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("rollback_provenance", root=root)


def memory_provenance_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("memory_provenance", root=root)


def _path(folder: Path, record_id: str) -> Path:
    return folder / f"{record_id}.json"


def _save(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _save_record(folder: Path, record, record_id: str):
    record.updated_at = now_iso()
    _save(_path(folder, record_id), record.to_dict())
    return record


def _load_rows(folder: Path, model) -> list:
    rows = []
    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(model.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def save_task_provenance(record: TaskProvenanceRecord, *, root: Optional[Path] = None) -> TaskProvenanceRecord:
    return _save_record(task_provenance_dir(root), record, record.task_provenance_id)


def save_artifact_provenance(record: ArtifactProvenanceRecord, *, root: Optional[Path] = None) -> ArtifactProvenanceRecord:
    return _save_record(artifact_provenance_dir(root), record, record.artifact_provenance_id)


def save_routing_provenance(record: RoutingProvenanceRecord, *, root: Optional[Path] = None) -> RoutingProvenanceRecord:
    return _save_record(routing_provenance_dir(root), record, record.routing_provenance_id)


def save_decision_provenance(record: DecisionProvenanceRecord, *, root: Optional[Path] = None) -> DecisionProvenanceRecord:
    return _save_record(decision_provenance_dir(root), record, record.decision_provenance_id)


def save_publish_provenance(record: PublishProvenanceRecord, *, root: Optional[Path] = None) -> PublishProvenanceRecord:
    return _save_record(publish_provenance_dir(root), record, record.publish_provenance_id)


def save_rollback_provenance(record: RollbackProvenanceRecord, *, root: Optional[Path] = None) -> RollbackProvenanceRecord:
    return _save_record(rollback_provenance_dir(root), record, record.rollback_provenance_id)


def save_memory_provenance(record: MemoryProvenanceRecord, *, root: Optional[Path] = None) -> MemoryProvenanceRecord:
    return _save_record(memory_provenance_dir(root), record, record.memory_provenance_id)


def list_task_provenance(root: Optional[Path] = None) -> list[TaskProvenanceRecord]:
    return _load_rows(task_provenance_dir(root), TaskProvenanceRecord)


def list_artifact_provenance(root: Optional[Path] = None) -> list[ArtifactProvenanceRecord]:
    return _load_rows(artifact_provenance_dir(root), ArtifactProvenanceRecord)


def list_routing_provenance(root: Optional[Path] = None) -> list[RoutingProvenanceRecord]:
    return _load_rows(routing_provenance_dir(root), RoutingProvenanceRecord)


def list_decision_provenance(root: Optional[Path] = None) -> list[DecisionProvenanceRecord]:
    return _load_rows(decision_provenance_dir(root), DecisionProvenanceRecord)


def list_publish_provenance(root: Optional[Path] = None) -> list[PublishProvenanceRecord]:
    return _load_rows(publish_provenance_dir(root), PublishProvenanceRecord)


def list_rollback_provenance(root: Optional[Path] = None) -> list[RollbackProvenanceRecord]:
    return _load_rows(rollback_provenance_dir(root), RollbackProvenanceRecord)


def list_memory_provenance(root: Optional[Path] = None) -> list[MemoryProvenanceRecord]:
    return _load_rows(memory_provenance_dir(root), MemoryProvenanceRecord)


def build_provenance_summary(root: Optional[Path] = None) -> dict:
    task_rows = list_task_provenance(root=root)
    artifact_rows = list_artifact_provenance(root=root)
    routing_rows = list_routing_provenance(root=root)
    decision_rows = list_decision_provenance(root=root)
    publish_rows = list_publish_provenance(root=root)
    rollback_rows = list_rollback_provenance(root=root)
    memory_rows = list_memory_provenance(root=root)
    return {
        "task_provenance_count": len(task_rows),
        "artifact_provenance_count": len(artifact_rows),
        "routing_provenance_count": len(routing_rows),
        "decision_provenance_count": len(decision_rows),
        "publish_provenance_count": len(publish_rows),
        "rollback_provenance_count": len(rollback_rows),
        "memory_provenance_count": len(memory_rows),
        "latest_task_provenance": task_rows[0].to_dict() if task_rows else None,
        "latest_artifact_provenance": artifact_rows[0].to_dict() if artifact_rows else None,
        "latest_routing_provenance": routing_rows[0].to_dict() if routing_rows else None,
        "latest_decision_provenance": decision_rows[0].to_dict() if decision_rows else None,
        "latest_publish_provenance": publish_rows[0].to_dict() if publish_rows else None,
        "latest_rollback_provenance": rollback_rows[0].to_dict() if rollback_rows else None,
        "latest_memory_provenance": memory_rows[0].to_dict() if memory_rows else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current provenance summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_provenance_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
