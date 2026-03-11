#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import (
    PublishProvenanceRecord,
    ArtifactRecord,
    OutputRecord,
    OutputStatus,
    RecordLifecycleState,
    new_id,
    now_iso,
)
from runtime.core.promotion_governance import assert_artifact_publish_allowed
from runtime.core.provenance_store import save_publish_provenance
from runtime.core.task_events import make_event
from runtime.core.task_runtime import append_task_event


def new_output_id() -> str:
    return f"out_{uuid.uuid4().hex[:12]}"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _task_path(task_id: str, *, root: Path) -> Path:
    return root / "state" / "tasks" / f"{task_id}.json"


def _artifact_path(artifact_id: str, *, root: Path) -> Path:
    return root / "state" / "artifacts" / f"{artifact_id}.json"


def load_task(task_id: str, *, root: Path) -> dict:
    path = _task_path(task_id, root=root)
    if not path.exists():
        raise ValueError(f"Task not found: {task_id}")
    return _load_json(path)


def load_artifact(artifact_id: str, *, root: Path) -> dict:
    path = _artifact_path(artifact_id, root=root)
    if not path.exists():
        raise ValueError(f"Artifact not found: {artifact_id}")
    return ArtifactRecord.from_dict(_load_json(path)).to_dict()


def output_dir(*, root: Path) -> Path:
    path = root / "workspace" / "out"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_outputs(*, root: Path) -> list[dict]:
    rows: list[dict] = []
    for path in output_dir(root=root).glob("*.json"):
        try:
            rows.append(OutputRecord.from_dict(_load_json(path)).to_dict())
        except Exception:
            continue
    rows.sort(key=lambda row: row.get("published_at", ""), reverse=True)
    return rows


def find_existing_output(*, task_id: str, artifact_id: str, root: Path) -> Optional[dict]:
    for row in list_outputs(root=root):
        if (
            row.get("task_id") == task_id
            and row.get("artifact_id") == artifact_id
            and row.get("status") == OutputStatus.PUBLISHED.value
        ):
            return row
    return None


def load_output(output_id: str, *, root: Path) -> OutputRecord:
    path = output_dir(root=root) / f"{output_id}.json"
    if not path.exists():
        raise ValueError(f"Output not found: {output_id}")
    return OutputRecord.from_dict(_load_json(path))


def save_output(record: OutputRecord, *, root: Path) -> OutputRecord:
    path = output_dir(root=root) / f"{record.output_id}.json"
    _save_json(path, record.to_dict())
    return record


def mark_outputs_impacted(
    *,
    artifact_id: str,
    root: Path,
    actor: str,
    lane: str,
    status: str,
    revocation_reason: str = "",
    superseded_by_artifact_id: Optional[str] = None,
) -> list[str]:
    impacted_output_ids: list[str] = []
    for row in list_outputs(root=root):
        if row.get("artifact_id") != artifact_id:
            continue
        record = OutputRecord.from_dict(row)
        record.status = status
        if artifact_id not in record.impacted_by_artifact_ids:
            record.impacted_by_artifact_ids.append(artifact_id)
        if superseded_by_artifact_id:
            record.superseded_by_artifact_id = superseded_by_artifact_id
        if revocation_reason:
            record.revocation_reason = revocation_reason
        if status == OutputStatus.REVOKED.value:
            record.revoked_at = now_iso()
        save_output(record, root=root)
        impacted_output_ids.append(record.output_id)
    return impacted_output_ids


def publish_artifact(
    *,
    task_id: str,
    artifact_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    allow_duplicate: bool = False,
) -> dict:
    root_path = Path(root or ROOT).resolve()
    assert_artifact_publish_allowed(
        task_id=task_id,
        artifact_id=artifact_id,
        actor=actor,
        lane=lane,
        root=root_path,
    )

    task = load_task(task_id, root=root_path)
    artifact = load_artifact(artifact_id, root=root_path)

    if artifact.get("task_id") != task_id:
        raise ValueError(
            f"Artifact {artifact_id} belongs to task {artifact.get('task_id')}, not {task_id}"
        )

    if artifact.get("lifecycle_state") != RecordLifecycleState.PROMOTED.value:
        raise ValueError(
            f"Artifact {artifact_id} is `{artifact.get('lifecycle_state')}` and cannot be published until promoted."
        )

    if artifact_id not in task.get("related_artifact_ids", []):
        raise ValueError(
            f"Artifact {artifact_id} is not linked on task {task_id}. Link it before publishing."
        )

    existing = find_existing_output(task_id=task_id, artifact_id=artifact_id, root=root_path)
    if existing and not allow_duplicate:
        try:
            from runtime.dashboard.output_board import build_output_board
            build_output_board(root=root_path)
        except Exception:
            pass

        return {
            "output_id": existing.get("output_id"),
            "task_id": task_id,
            "artifact_id": artifact_id,
            "title": existing.get("title", artifact.get("title", "")),
            "summary": existing.get("summary", artifact.get("summary", "")),
            "markdown_path": existing.get("markdown_path"),
            "json_path": str(output_dir(root=root_path) / f"{existing.get('output_id')}.json"),
            "event_id": None,
            "already_published": True,
        }

    out_id = new_output_id()
    out_root = output_dir(root=root_path)

    md_path = out_root / f"{out_id}.md"
    json_path = out_root / f"{out_id}.json"

    published_at = now_iso()

    md_text = "\n".join(
        [
            f"# {artifact.get('title', 'Untitled output')}",
            "",
            f"**Output ID:** {out_id}",
            f"**Artifact ID:** {artifact_id}",
            f"**Task ID:** {task_id}",
            f"**Published by:** {actor}",
            f"**Published at:** {published_at}",
            "",
            "## Summary",
            "",
            artifact.get("summary", ""),
            "",
            "## Content",
            "",
            artifact.get("content", ""),
            "",
        ]
    )
    md_path.write_text(md_text, encoding="utf-8")

    record = OutputRecord(
        output_id=out_id,
        task_id=task_id,
        artifact_id=artifact_id,
        title=artifact.get("title", ""),
        summary=artifact.get("summary", ""),
        markdown_path=str(md_path),
        json_path=str(json_path),
        published_at=published_at,
        published_by=actor,
        lane=lane,
    ).to_dict()
    json_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    event = append_task_event(
        root_path,
        make_event(
            task_id=task_id,
            event_type="output_published",
            actor=actor,
            lane=lane,
            summary=f"Output published: {out_id}",
            artifact_id=artifact_id,
            artifact_type=artifact.get("artifact_type"),
            artifact_title=artifact.get("title"),
            details=artifact.get("summary", ""),
        ),
    )

    try:
        from runtime.dashboard.output_board import build_output_board
        build_output_board(root=root_path)
    except Exception:
        pass

    from runtime.core.rollback_store import record_output_dependency

    record_output_dependency(
        output_id=out_id,
        task_id=task_id,
        artifact_id=artifact_id,
        actor=actor,
        lane=lane,
        output_status=OutputStatus.PUBLISHED.value,
        root=root_path,
    )
    save_publish_provenance(
        PublishProvenanceRecord(
            publish_provenance_id=new_id("pprov"),
            output_id=out_id,
            task_id=task_id,
            artifact_id=artifact_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            output_status=OutputStatus.PUBLISHED.value,
            source_refs={
                "event_id": event.event_id,
                "routing_decision_id": (((task.get("backend_metadata") or {}).get("routing") or {}).get("routing_decision_id")),
            },
            replay_input={"task_id": task_id, "artifact_id": artifact_id, "allow_duplicate": allow_duplicate},
        ),
        root=root_path,
    )

    return {
        "output_id": out_id,
        "task_id": task_id,
        "artifact_id": artifact_id,
        "title": artifact.get("title", ""),
        "summary": artifact.get("summary", ""),
        "markdown_path": str(md_path),
        "json_path": str(json_path),
        "event_id": event.event_id,
        "already_published": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a linked artifact into the outputs lane.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--artifact-id", required=True, help="Artifact id")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="outputs", help="Lane name")
    parser.add_argument("--allow-duplicate", action="store_true", help="Allow duplicate output records")
    args = parser.parse_args()

    result = publish_artifact(
        task_id=args.task_id,
        artifact_id=args.artifact_id,
        actor=args.actor,
        lane=args.lane,
        root=Path(args.root).resolve(),
        allow_duplicate=args.allow_duplicate,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
