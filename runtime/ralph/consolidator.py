#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.controls.control_store import assert_control_allows
from runtime.core.approval_store import (
    ApprovalStatus,
    latest_approval_for_task,
    load_approval_checkpoint,
    request_approval,
    save_approval,
    save_approval_checkpoint,
)
from runtime.core.artifact_store import load_artifact, write_text_artifact
from runtime.core.models import (
    ConsolidationRunRecord,
    DigestArtifactLinkRecord,
    MemoryCandidateRecord,
    RecordLifecycleState,
    ReviewStatus,
    TaskStatus,
    new_id,
    now_iso,
)
from runtime.core.review_store import latest_review_for_task, request_review, save_review
from runtime.core.task_events import append_event, make_event
from runtime.core.task_store import load_task, save_task, transition_task
from runtime.evals.trace_store import list_eval_results_for_task, list_run_traces_for_task
from runtime.memory.governance import register_memory_candidate


RALPH_BACKEND_ID = "ralph_adapter"


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def consolidation_runs_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("consolidation_runs", root=root)


def digest_artifact_links_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("digest_artifact_links", root=root)


def memory_candidates_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("memory_candidates", root=root)


def _record_path(folder: Path, record_id: str) -> Path:
    return folder / f"{record_id}.json"


def save_consolidation_run(record: ConsolidationRunRecord, *, root: Optional[Path] = None) -> ConsolidationRunRecord:
    record.updated_at = now_iso()
    _record_path(consolidation_runs_dir(root), record.consolidation_run_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_consolidation_run(consolidation_run_id: str, *, root: Optional[Path] = None) -> Optional[ConsolidationRunRecord]:
    path = _record_path(consolidation_runs_dir(root), consolidation_run_id)
    if not path.exists():
        return None
    return ConsolidationRunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_digest_artifact_link(
    record: DigestArtifactLinkRecord,
    *,
    root: Optional[Path] = None,
) -> DigestArtifactLinkRecord:
    record.updated_at = now_iso()
    _record_path(digest_artifact_links_dir(root), record.digest_link_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def save_memory_candidate(record: MemoryCandidateRecord, *, root: Optional[Path] = None) -> MemoryCandidateRecord:
    record.updated_at = now_iso()
    _record_path(memory_candidates_dir(root), record.memory_candidate_id).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_memory_candidate(memory_candidate_id: str, *, root: Optional[Path] = None) -> Optional[MemoryCandidateRecord]:
    path = _record_path(memory_candidates_dir(root), memory_candidate_id)
    if not path.exists():
        return None
    return MemoryCandidateRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_memory_candidates_for_task(task_id: str, *, root: Optional[Path] = None) -> list[MemoryCandidateRecord]:
    rows: list[MemoryCandidateRecord] = []
    for path in memory_candidates_dir(root).glob("*.json"):
        try:
            row = MemoryCandidateRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if row.task_id == task_id:
            rows.append(row)
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows


def _link_candidate_to_pending_records(*, task_id: str, artifact_id: str, root: Path) -> None:
    review = latest_review_for_task(task_id, root=root)
    if review is not None and review.status == ReviewStatus.PENDING.value and artifact_id not in review.linked_artifact_ids:
        review.linked_artifact_ids.append(artifact_id)
        save_review(review, root=root)

    approval = latest_approval_for_task(task_id, root=root)
    if approval is not None and approval.status == ApprovalStatus.PENDING.value and artifact_id not in approval.linked_artifact_ids:
        approval.linked_artifact_ids.append(artifact_id)
        save_approval(approval, root=root)
        if approval.resumable_checkpoint_id:
            checkpoint = load_approval_checkpoint(approval.resumable_checkpoint_id, root=root)
            if checkpoint is not None and artifact_id not in checkpoint.linked_artifact_ids:
                checkpoint.linked_artifact_ids.append(artifact_id)
                save_approval_checkpoint(checkpoint, root=root)


def _maybe_request_operator_gate(*, task, actor: str, lane: str, artifact_id: str, root: Path) -> None:
    summary = f"Ralph digest candidate ready: {task.task_id}"
    if task.review_required:
        existing = latest_review_for_task(task.task_id, root=root)
        if existing is None or existing.status != ReviewStatus.PENDING.value:
            request_review(
                task_id=task.task_id,
                reviewer_role="anton" if task.risk_level == "high_stakes" else "operator",
                requested_by=actor,
                lane=lane,
                summary=summary,
                linked_artifact_ids=[artifact_id],
                root=root,
            )
        return

    if task.approval_required:
        existing = latest_approval_for_task(task.task_id, root=root)
        if existing is None or existing.status != ApprovalStatus.PENDING.value:
            request_approval(
                task_id=task.task_id,
                approval_type=task.task_type,
                requested_by=actor,
                requested_reviewer="anton" if task.risk_level == "high_stakes" else "operator",
                lane=lane,
                summary=summary,
                linked_artifact_ids=[artifact_id],
                root=root,
            )


def _task_artifacts(task, *, root: Path, max_items: int) -> list[dict]:
    seen: set[str] = set()
    ordered_ids = list(task.candidate_artifact_ids)
    if task.promoted_artifact_id:
        ordered_ids.append(task.promoted_artifact_id)
    ordered_ids.extend(task.related_artifact_ids)
    rows: list[dict] = []
    for artifact_id in ordered_ids:
        if not artifact_id or artifact_id in seen:
            continue
        seen.add(artifact_id)
        try:
            artifact = load_artifact(artifact_id, root=root)
        except Exception:
            continue
        rows.append(artifact.to_dict())
        if len(rows) >= max_items:
            break
    return rows


def _build_digest_content(*, task, artifacts: list[dict], traces: list, eval_results: list) -> str:
    lines = [
        f"# Ralph Consolidation Digest for {task.task_id}",
        "",
        f"Task: {task.normalized_request}",
        f"Status: {task.status}",
        f"Lifecycle: {task.lifecycle_state}",
        f"Execution backend: {task.execution_backend}",
        "",
        "## Artifact Signals",
    ]
    if artifacts:
        for artifact in artifacts:
            lines.append(
                f"- {artifact.get('artifact_id')}: {artifact.get('title')} [{artifact.get('lifecycle_state')}] {artifact.get('summary')}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Trace Signals"])
    if traces:
        for trace in traces:
            lines.append(
                f"- {trace.trace_id}: {trace.trace_kind} status={trace.status} response={trace.response_summary}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Eval Signals"])
    if eval_results:
        for eval_result in eval_results:
            lines.append(
                f"- {eval_result.eval_result_id}: passed={eval_result.passed} score={eval_result.score:.4f} summary={eval_result.summary}"
            )
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Operator Digest",
            f"Ralph observed {len(artifacts)} artifacts, {len(traces)} traces, and {len(eval_results)} eval results.",
            "This digest is a candidate artifact only and requires the normal review/approval/promotion path.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def execute_consolidation(
    *,
    task_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
    max_artifacts: int = 5,
    max_traces: int = 5,
    max_eval_results: int = 5,
) -> dict:
    root_path = Path(root or ROOT).resolve()
    task = load_task(task_id, root=root_path)
    if task is None:
        raise ValueError(f"Task not found: {task_id}")
    if task.status not in {
        TaskStatus.QUEUED.value,
        TaskStatus.RUNNING.value,
        TaskStatus.WAITING_REVIEW.value,
        TaskStatus.WAITING_APPROVAL.value,
    }:
        raise ValueError(f"Task {task_id} is `{task.status}` and cannot be consolidated from this state.")

    assert_control_allows(
        action="task_progress",
        root=root_path,
        task_id=task_id,
        subsystem=RALPH_BACKEND_ID,
        provider_id=((task.backend_metadata if task else {}) or {}).get("routing", {}).get("provider_id"),
        actor=actor,
        lane=lane,
    )
    assert_control_allows(
        action="memory_write",
        root=root_path,
        task_id=task_id,
        subsystem=RALPH_BACKEND_ID,
        provider_id=((task.backend_metadata if task else {}) or {}).get("routing", {}).get("provider_id"),
        actor=actor,
        lane=lane,
    )

    original_status = task.status
    run = ConsolidationRunRecord(
        consolidation_run_id=new_id("ralphrun"),
        task_id=task_id,
        created_at=now_iso(),
        updated_at=now_iso(),
        actor=actor,
        lane=lane,
        status="running",
        execution_backend=RALPH_BACKEND_ID,
    )
    save_consolidation_run(run, root=root_path)

    if original_status == TaskStatus.QUEUED.value:
        transition_task(
            task_id=task_id,
            to_status=TaskStatus.RUNNING.value,
            actor=actor,
            lane=lane,
            summary=f"Ralph consolidation started: {run.consolidation_run_id}",
            root=root_path,
            details="Ralph claimed queued task for bounded consolidation.",
        )

    append_event(
        make_event(
            task_id=task_id,
            event_type="ralph_consolidation_started",
            actor=actor,
            lane=lane,
            summary=f"Ralph consolidation started: {run.consolidation_run_id}",
            from_status=original_status,
            to_status=TaskStatus.RUNNING.value if original_status == TaskStatus.QUEUED.value else original_status,
            execution_backend=RALPH_BACKEND_ID,
        ),
        root=root_path,
    )

    artifacts = _task_artifacts(task, root=root_path, max_items=max_artifacts)
    traces = list_run_traces_for_task(task_id, root=root_path)[:max_traces]
    eval_results = list_eval_results_for_task(task_id, root=root_path)[:max_eval_results]

    run.source_artifact_ids = [artifact["artifact_id"] for artifact in artifacts]
    run.source_trace_ids = [trace.trace_id for trace in traces]
    run.source_eval_result_ids = [eval_result.eval_result_id for eval_result in eval_results]

    digest_artifact = write_text_artifact(
        task_id=task_id,
        artifact_type="report",
        title=f"Ralph digest: {task.normalized_request}",
        summary=f"Bounded operator digest for {task.task_id}",
        content=_build_digest_content(task=task, artifacts=artifacts, traces=traces, eval_results=eval_results),
        actor="ralph",
        lane=lane,
        root=root_path,
        producer_kind="backend",
        execution_backend=RALPH_BACKEND_ID,
        backend_run_id=run.consolidation_run_id,
        provenance_ref=f"ralph:{run.consolidation_run_id}",
    )
    run.digest_artifact_id = digest_artifact["artifact_id"]

    digest_link = DigestArtifactLinkRecord(
        digest_link_id=new_id("diglink"),
        consolidation_run_id=run.consolidation_run_id,
        task_id=task_id,
        artifact_id=digest_artifact["artifact_id"],
        created_at=now_iso(),
        updated_at=now_iso(),
        actor=actor,
        lane=lane,
        execution_backend=RALPH_BACKEND_ID,
    )
    save_digest_artifact_link(digest_link, root=root_path)

    memory_candidates: list[MemoryCandidateRecord] = []
    memory_candidates.append(
        MemoryCandidateRecord(
            memory_candidate_id=new_id("memcand"),
            consolidation_run_id=run.consolidation_run_id,
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            candidate_kind="consolidation_candidate",
            memory_type="task_digest",
            title=f"Task digest memory for {task.task_id}",
            summary=f"Digest derived from {len(artifacts)} artifacts, {len(traces)} traces, and {len(eval_results)} eval results.",
            content=f"Task `{task.normalized_request}` currently has status `{task.status}` with digest artifact `{digest_artifact['artifact_id']}`.",
            source_artifact_ids=run.source_artifact_ids,
            source_trace_ids=run.source_trace_ids,
            source_eval_result_ids=run.source_eval_result_ids,
            lifecycle_state=RecordLifecycleState.CANDIDATE.value,
            execution_backend=RALPH_BACKEND_ID,
        )
    )
    if eval_results:
        latest_eval = eval_results[0]
        memory_candidates.append(
            MemoryCandidateRecord(
                memory_candidate_id=new_id("memcand"),
                consolidation_run_id=run.consolidation_run_id,
                task_id=task_id,
                created_at=now_iso(),
                updated_at=now_iso(),
                actor=actor,
                lane=lane,
                candidate_kind="memory_candidate",
                memory_type="eval_summary",
                title=f"Eval summary memory for {task.task_id}",
                summary=latest_eval.summary,
                content=f"Latest eval `{latest_eval.eval_result_id}` passed={latest_eval.passed} score={latest_eval.score:.4f}.",
                source_artifact_ids=[item for item in [latest_eval.report_artifact_id, digest_artifact['artifact_id']] if item],
                source_trace_ids=[latest_eval.trace_id],
                source_eval_result_ids=[latest_eval.eval_result_id],
                lifecycle_state=RecordLifecycleState.CANDIDATE.value,
                execution_backend=RALPH_BACKEND_ID,
            )
        )

    registered_memory_candidates: list[MemoryCandidateRecord] = []
    for memory_candidate in memory_candidates:
        memory_candidate.source_provenance_refs = {
            "consolidation_run_id": run.consolidation_run_id,
            "digest_artifact_id": digest_artifact["artifact_id"],
        }
        registered_memory_candidates.append(
            register_memory_candidate(
                record=memory_candidate,
                actor=actor,
                lane=lane,
                root=root_path,
            )
        )
    run.memory_candidate_ids = [item.memory_candidate_id for item in registered_memory_candidates]
    run.status = "completed"
    run.summary = f"Ralph produced digest artifact {digest_artifact['artifact_id']} and {len(memory_candidates)} memory candidates."
    save_consolidation_run(run, root=root_path)

    _link_candidate_to_pending_records(task_id=task_id, artifact_id=digest_artifact["artifact_id"], root=root_path)
    _maybe_request_operator_gate(task=task, actor=actor, lane=lane, artifact_id=digest_artifact["artifact_id"], root=root_path)

    task = load_task(task_id, root=root_path)
    task.execution_backend = RALPH_BACKEND_ID
    task.backend_run_id = run.consolidation_run_id
    task.backend_metadata.setdefault("ralph", {})
    task.backend_metadata["ralph"] = {
        "last_run_id": run.consolidation_run_id,
        "digest_artifact_id": digest_artifact["artifact_id"],
        "memory_candidate_ids": list(run.memory_candidate_ids),
    }
    task.checkpoint_summary = f"Ralph digest candidate stored: {digest_artifact['artifact_id']}"
    save_task(task, root=root_path)

    if original_status == TaskStatus.QUEUED.value:
        task = load_task(task_id, root=root_path)
        if task.status == TaskStatus.RUNNING.value:
            transition_task(
                task_id=task_id,
                to_status=TaskStatus.QUEUED.value,
                actor=actor,
                lane=lane,
                summary=f"Ralph consolidation complete: {run.consolidation_run_id}",
                root=root_path,
                details=run.summary,
            )

    append_event(
        make_event(
            task_id=task_id,
            event_type="ralph_consolidation_completed",
            actor="ralph",
            lane=lane,
            summary=f"Ralph consolidation completed: {run.consolidation_run_id}",
            from_status=original_status,
            to_status=load_task(task_id, root=root_path).status,
            artifact_id=digest_artifact["artifact_id"],
            artifact_type=digest_artifact["artifact_type"],
            artifact_title=digest_artifact["title"],
            execution_backend=RALPH_BACKEND_ID,
            backend_run_id=run.consolidation_run_id,
            details=run.summary,
        ),
        root=root_path,
    )

    return {
        "consolidation_run": run.to_dict(),
        "digest_artifact_id": digest_artifact["artifact_id"],
        "memory_candidate_ids": list(run.memory_candidate_ids),
        "task_status": load_task(task_id, root=root_path).status,
    }
