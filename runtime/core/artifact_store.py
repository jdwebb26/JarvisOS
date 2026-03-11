#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import ArtifactRecord, OutputStatus, RecordLifecycleState, TaskStatus
from runtime.core.output_store import mark_outputs_impacted
from runtime.core.promotion_governance import assert_artifact_promotion_allowed
from runtime.core.task_events import append_event, make_event
from runtime.core.task_runtime import load_task
from runtime.core.task_store import (
    mark_task_artifact_revoked,
    mark_task_output_impacts,
    set_task_lifecycle_state,
    transition_task,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_artifact_id() -> str:
    return f"art_{uuid.uuid4().hex[:12]}"


def artifacts_dir(root: Optional[Path] = None) -> Path:
    root_path = Path(root or ROOT).resolve()
    path = root_path / "state" / "artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def artifact_path(artifact_id: str, root: Optional[Path] = None) -> Path:
    return artifacts_dir(root=root) / f"{artifact_id}.json"


def save_artifact(record: ArtifactRecord, root: Optional[Path] = None) -> ArtifactRecord:
    record.updated_at = now_iso()
    path = artifact_path(record.artifact_id, root=root)
    path.write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return record


def load_artifact(artifact_id: str, root: Optional[Path] = None) -> ArtifactRecord:
    path = artifact_path(artifact_id, root=root)
    if not path.exists():
        raise ValueError(f"Artifact not found: {artifact_id}")
    return ArtifactRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def select_task_artifact(
    *,
    task_id: str,
    root: Optional[Path] = None,
    preferred_artifact_ids: Optional[list[str]] = None,
    allowed_states: Optional[set[str]] = None,
) -> Optional[ArtifactRecord]:
    root_path = Path(root or ROOT).resolve()
    task = load_task(root_path, task_id)
    if task is None:
        raise ValueError(f"Task not found: {task_id}")

    allowed = allowed_states or set(RecordLifecycleState.values())
    seen: set[str] = set()
    ordered_ids = list(preferred_artifact_ids or [])
    ordered_ids.extend(task.candidate_artifact_ids)
    if task.promoted_artifact_id:
        ordered_ids.append(task.promoted_artifact_id)
    ordered_ids.extend(task.related_artifact_ids)

    for artifact_id in ordered_ids:
        if not artifact_id or artifact_id in seen:
            continue
        seen.add(artifact_id)
        try:
            artifact = load_artifact(artifact_id, root=root_path)
        except Exception:
            continue
        if artifact.task_id != task_id:
            continue
        if artifact.lifecycle_state not in allowed:
            continue
        return artifact
    return None


def _enforce_task_state_after_artifact_change(
    *,
    artifact: ArtifactRecord,
    actor: str,
    lane: str,
    root: Path,
    reason: str,
) -> None:
    task = load_task(root, artifact.task_id)
    if task is None:
        return

    if artifact.lifecycle_state in {RecordLifecycleState.DEMOTED.value, RecordLifecycleState.SUPERSEDED.value}:
        if task.status in {TaskStatus.READY_TO_SHIP.value, TaskStatus.SHIPPED.value}:
            transition_task(
                task_id=task.task_id,
                to_status=TaskStatus.BLOCKED.value,
                actor=actor,
                lane=lane,
                root=root,
                summary=f"Task blocked after artifact {artifact.lifecycle_state}: {artifact.artifact_id}",
                details=reason,
            )


def _default_lifecycle_state(producer_kind: str, lifecycle_state: Optional[str]) -> str:
    if lifecycle_state:
        return lifecycle_state
    if producer_kind == "backend":
        return RecordLifecycleState.CANDIDATE.value
    return RecordLifecycleState.PROMOTED.value


def write_text_artifact(
    *,
    task_id: str,
    artifact_type: str,
    title: str,
    summary: str,
    content: str,
    actor: str = "operator",
    lane: str = "artifacts",
    root: Optional[Path] = None,
    producer_kind: str = "operator",
    lifecycle_state: Optional[str] = None,
    execution_backend: Optional[str] = None,
    backend_run_id: Optional[str] = None,
    provenance_ref: Optional[str] = None,
) -> dict:
    root_path = Path(root or ROOT).resolve()

    task = load_task(root_path, task_id)
    if not task:
        raise ValueError(f"Task not found: {task_id}")

    artifact_id = new_artifact_id()
    resolved_lifecycle = _default_lifecycle_state(producer_kind, lifecycle_state)
    promoted_at = now_iso() if resolved_lifecycle == RecordLifecycleState.PROMOTED.value else None

    record = ArtifactRecord(
        artifact_id=artifact_id,
        task_id=task_id,
        artifact_type=artifact_type,
        title=title,
        summary=summary,
        content=content,
        created_at=now_iso(),
        updated_at=now_iso(),
        created_by=actor,
        lane=lane,
        lifecycle_state=resolved_lifecycle,
        producer_kind=producer_kind,
        execution_backend=execution_backend,
        backend_run_id=backend_run_id,
        provenance_ref=provenance_ref,
        promoted_at=promoted_at,
        promoted_by=actor if promoted_at else None,
    )

    save_artifact(record, root=root_path)

    task_after = set_task_lifecycle_state(
        task_id=task_id,
        lifecycle_state=resolved_lifecycle,
        actor=actor,
        lane=lane,
        root=root_path,
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        artifact_title=title,
        execution_backend=execution_backend,
        backend_run_id=backend_run_id,
        reason=f"Artifact registered as {resolved_lifecycle}: {artifact_id}",
    )

    event = append_event(
        make_event(
            task_id=task_id,
            event_type="artifact_created",
            actor=actor,
            lane=lane,
            summary=f"Artifact created: {artifact_id}",
            from_status=task_after.status,
            to_status=task_after.status,
            from_lifecycle_state=None,
            to_lifecycle_state=resolved_lifecycle,
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            artifact_title=title,
            execution_backend=execution_backend,
            backend_run_id=backend_run_id,
            details=summary,
        ),
        root=root_path,
    )

    result = record.to_dict()
    result["event_id"] = event.event_id
    result["task_lifecycle_state"] = task_after.lifecycle_state
    if resolved_lifecycle == RecordLifecycleState.CANDIDATE.value:
        from runtime.core.candidate_store import register_candidate_artifact

        candidate = register_candidate_artifact(
            task_id=task_id,
            artifact_id=artifact_id,
            actor=actor,
            lane=lane,
            execution_backend=execution_backend,
            root=root_path,
        )
        result["candidate_id"] = candidate.candidate_id
        result["latest_validation_id"] = candidate.latest_validation_id
    return result


def promote_artifact(
    *,
    artifact_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    provenance_ref: Optional[str] = None,
) -> ArtifactRecord:
    root_path = Path(root or ROOT).resolve()
    artifact = load_artifact(artifact_id, root=root_path)
    assert_artifact_promotion_allowed(
        artifact=artifact,
        actor=actor,
        lane=lane,
        root=root_path,
    )
    previous_state = artifact.lifecycle_state

    artifact.lifecycle_state = RecordLifecycleState.PROMOTED.value
    artifact.promoted_at = now_iso()
    artifact.promoted_by = actor
    artifact.demoted_at = None
    artifact.demoted_by = None
    artifact.revoked_at = None
    artifact.revoked_by = None
    artifact.revocation_reason = ""
    artifact.superseded_by_artifact_id = None
    if provenance_ref is not None:
        artifact.provenance_ref = provenance_ref
    save_artifact(artifact, root=root_path)

    set_task_lifecycle_state(
        task_id=artifact.task_id,
        lifecycle_state=artifact.lifecycle_state,
        actor=actor,
        lane=lane,
        root=root_path,
        artifact_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
        artifact_title=artifact.title,
        execution_backend=artifact.execution_backend,
        backend_run_id=artifact.backend_run_id,
        reason=f"Artifact promoted: {artifact.artifact_id}",
    )

    append_event(
        make_event(
            task_id=artifact.task_id,
            event_type="artifact_lifecycle_changed",
            actor=actor,
            lane=lane,
            summary=f"Artifact lifecycle changed: {previous_state} -> {artifact.lifecycle_state}",
            from_lifecycle_state=previous_state,
            to_lifecycle_state=artifact.lifecycle_state,
            artifact_id=artifact.artifact_id,
            artifact_type=artifact.artifact_type,
            artifact_title=artifact.title,
            execution_backend=artifact.execution_backend,
            backend_run_id=artifact.backend_run_id,
        ),
        root=root_path,
    )
    from runtime.core.candidate_store import record_candidate_promotion

    record_candidate_promotion(
        artifact_id=artifact.artifact_id,
        actor=actor,
        lane=lane,
        reason=f"Artifact promoted by {actor}",
        provenance_ref=artifact.provenance_ref,
        root=root_path,
    )
    return artifact


def demote_artifact(
    *,
    artifact_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    superseded_by_artifact_id: Optional[str] = None,
) -> ArtifactRecord:
    root_path = Path(root or ROOT).resolve()
    artifact = load_artifact(artifact_id, root=root_path)
    previous_state = artifact.lifecycle_state

    artifact.lifecycle_state = (
        RecordLifecycleState.SUPERSEDED.value if superseded_by_artifact_id else RecordLifecycleState.DEMOTED.value
    )
    artifact.demoted_at = now_iso()
    artifact.demoted_by = actor
    artifact.superseded_by_artifact_id = superseded_by_artifact_id
    artifact.revoked_at = None
    artifact.revoked_by = None
    artifact.revocation_reason = ""
    impacted_output_ids = mark_outputs_impacted(
        artifact_id=artifact.artifact_id,
        root=root_path,
        actor=actor,
        lane=lane,
        status=OutputStatus.IMPACTED.value,
        superseded_by_artifact_id=superseded_by_artifact_id,
        revocation_reason=(
            f"Artifact superseded by {superseded_by_artifact_id}."
            if superseded_by_artifact_id
            else f"Artifact demoted: {artifact.artifact_id}."
        ),
    )
    artifact.downstream_impacted_output_ids = impacted_output_ids
    save_artifact(artifact, root=root_path)
    if impacted_output_ids:
        mark_task_output_impacts(
            task_id=artifact.task_id,
            output_ids=impacted_output_ids,
            actor=actor,
            lane=lane,
            root=root_path,
            reason=f"Artifact {artifact.artifact_id} impacted downstream outputs.",
        )

    set_task_lifecycle_state(
        task_id=artifact.task_id,
        lifecycle_state=artifact.lifecycle_state,
        actor=actor,
        lane=lane,
        root=root_path,
        artifact_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
        artifact_title=artifact.title,
        execution_backend=artifact.execution_backend,
        backend_run_id=artifact.backend_run_id,
        reason=f"Artifact {artifact.lifecycle_state}: {artifact.artifact_id}",
    )
    task_reason = (
        f"Artifact {artifact.artifact_id} superseded by {superseded_by_artifact_id}."
        if superseded_by_artifact_id
        else f"Artifact {artifact.artifact_id} demoted."
    )
    _enforce_task_state_after_artifact_change(
        artifact=artifact,
        actor=actor,
        lane=lane,
        root=root_path,
        reason=task_reason,
    )

    append_event(
        make_event(
            task_id=artifact.task_id,
            event_type="artifact_lifecycle_changed",
            actor=actor,
            lane=lane,
            summary=f"Artifact lifecycle changed: {previous_state} -> {artifact.lifecycle_state}",
            from_lifecycle_state=previous_state,
            to_lifecycle_state=artifact.lifecycle_state,
            artifact_id=artifact.artifact_id,
            artifact_type=artifact.artifact_type,
            artifact_title=artifact.title,
            execution_backend=artifact.execution_backend,
            backend_run_id=artifact.backend_run_id,
            details=f"superseded_by={superseded_by_artifact_id}" if superseded_by_artifact_id else "",
        ),
        root=root_path,
    )
    return artifact


def revoke_artifact(
    *,
    artifact_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    reason: str,
) -> ArtifactRecord:
    root_path = Path(root or ROOT).resolve()
    artifact = load_artifact(artifact_id, root=root_path)
    previous_state = artifact.lifecycle_state

    artifact.lifecycle_state = RecordLifecycleState.DEMOTED.value
    artifact.demoted_at = now_iso()
    artifact.demoted_by = actor
    artifact.revoked_at = artifact.demoted_at
    artifact.revoked_by = actor
    artifact.revocation_reason = reason
    impacted_output_ids = mark_outputs_impacted(
        artifact_id=artifact.artifact_id,
        root=root_path,
        actor=actor,
        lane=lane,
        status=OutputStatus.REVOKED.value,
        revocation_reason=reason,
    )
    artifact.downstream_impacted_output_ids = impacted_output_ids
    save_artifact(artifact, root=root_path)

    mark_task_artifact_revoked(
        task_id=artifact.task_id,
        artifact_id=artifact.artifact_id,
        actor=actor,
        lane=lane,
        root=root_path,
        reason=reason,
        impacted_output_ids=impacted_output_ids,
    )
    _enforce_task_state_after_artifact_change(
        artifact=artifact,
        actor=actor,
        lane=lane,
        root=root_path,
        reason=reason,
    )

    append_event(
        make_event(
            task_id=artifact.task_id,
            event_type="artifact_revoked",
            actor=actor,
            lane=lane,
            summary=f"Artifact revoked: {artifact.artifact_id}",
            from_lifecycle_state=previous_state,
            to_lifecycle_state=artifact.lifecycle_state,
            artifact_id=artifact.artifact_id,
            artifact_type=artifact.artifact_type,
            artifact_title=artifact.title,
            execution_backend=artifact.execution_backend,
            backend_run_id=artifact.backend_run_id,
            details=reason,
        ),
        root=root_path,
    )
    from runtime.core.candidate_store import record_candidate_revocation_hook
    from runtime.memory.governance import revoke_memory_candidates_for_artifact

    record_candidate_revocation_hook(
        artifact_id=artifact.artifact_id,
        actor=actor,
        lane=lane,
        reason=reason,
        impacted_output_ids=impacted_output_ids,
        root=root_path,
    )
    revoke_memory_candidates_for_artifact(
        artifact_id=artifact.artifact_id,
        task_id=artifact.task_id,
        actor=actor,
        lane=lane,
        reason=reason,
        root=root_path,
    )
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a text artifact and link it back onto a task.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--artifact-type", required=True, help="Artifact type")
    parser.add_argument("--title", required=True, help="Artifact title")
    parser.add_argument("--summary", required=True, help="Artifact summary")
    parser.add_argument("--content", required=True, help="Artifact content")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="artifacts", help="Lane name")
    parser.add_argument("--producer-kind", default="operator", choices=["operator", "backend"])
    parser.add_argument("--lifecycle-state", default="", help="Optional explicit lifecycle state")
    parser.add_argument("--execution-backend", default="", help="Execution backend name")
    parser.add_argument("--backend-run-id", default="", help="Backend run identifier")
    parser.add_argument("--provenance-ref", default="", help="Promotion/provenance reference")
    args = parser.parse_args()

    record = write_text_artifact(
        task_id=args.task_id,
        artifact_type=args.artifact_type,
        title=args.title,
        summary=args.summary,
        content=args.content,
        actor=args.actor,
        lane=args.lane,
        root=Path(args.root).resolve(),
        producer_kind=args.producer_kind,
        lifecycle_state=args.lifecycle_state or None,
        execution_backend=args.execution_backend or None,
        backend_run_id=args.backend_run_id or None,
        provenance_ref=args.provenance_ref or None,
    )

    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
