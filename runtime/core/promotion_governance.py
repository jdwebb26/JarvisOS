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

from runtime.controls.control_store import assert_control_allows, build_control_summary
from runtime.core.candidate_store import find_candidate_for_artifact, list_candidates
from runtime.core.models import RecordLifecycleState
from runtime.core.task_store import load_task, task_dependency_summary


def _provider_id_for_task(task) -> Optional[str]:
    routing = ((task.backend_metadata if task else {}) or {}).get("routing", {})
    return routing.get("provider_id")


def assert_artifact_promotion_allowed(
    *,
    artifact,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
) -> dict:
    root_path = Path(root or ROOT).resolve()
    task = load_task(artifact.task_id, root=root_path)
    if task is None:
        raise ValueError(f"Task not found for artifact promotion: {artifact.task_id}")
    if artifact.lifecycle_state != RecordLifecycleState.CANDIDATE.value:
        raise ValueError(
            f"Artifact {artifact.artifact_id} is `{artifact.lifecycle_state}` and cannot be promoted from that state."
        )

    state = assert_control_allows(
        action="promote_artifact",
        root=root_path,
        task_id=artifact.task_id,
        subsystem=artifact.execution_backend or lane,
        provider_id=_provider_id_for_task(task),
        actor=actor,
        lane=lane,
    )
    candidate = find_candidate_for_artifact(artifact.artifact_id, root=root_path)
    if candidate is not None:
        if candidate.latest_revocation_id:
            raise ValueError(f"Artifact candidate {candidate.candidate_id} is revoked and cannot be promoted.")
        if candidate.latest_rejection_decision_id:
            raise ValueError(f"Artifact candidate {candidate.candidate_id} is rejected and cannot be promoted.")
        if candidate.latest_validation_id is None:
            raise ValueError(f"Artifact candidate {candidate.candidate_id} has no validation record.")
    dependency_state = task_dependency_summary(task.task_id, root=root_path)
    if dependency_state["hard_block"] or dependency_state["speculative_only"]:
        raise ValueError(str(dependency_state["reason"]))
    return {
        "control_state": state,
        "candidate_id": candidate.candidate_id if candidate else None,
        "policy_status": "eligible",
    }


def assert_artifact_publish_allowed(
    *,
    task_id: str,
    artifact_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
) -> dict:
    root_path = Path(root or ROOT).resolve()
    task = load_task(task_id, root=root_path)
    if task is None:
        raise ValueError(f"Task not found for output publish: {task_id}")
    if task.promoted_artifact_id and task.promoted_artifact_id != artifact_id:
        raise ValueError(
            f"Artifact {artifact_id} cannot be published because task {task_id} is currently promoted to {task.promoted_artifact_id}."
        )
    state = assert_control_allows(
        action="publish_output",
        root=root_path,
        task_id=task_id,
        subsystem=lane,
        provider_id=_provider_id_for_task(task),
        actor=actor,
        lane=lane,
    )
    dependency_state = task_dependency_summary(task.task_id, root=root_path)
    if dependency_state["hard_block"] or dependency_state["speculative_only"]:
        raise ValueError(str(dependency_state["reason"]))
    return {
        "control_state": state,
        "policy_status": "eligible",
    }


def build_promotion_governance_summary(*, root: Optional[Path] = None) -> dict:
    root_path = Path(root or ROOT).resolve()
    control_summary = build_control_summary(root=root_path)
    candidates = list_candidates(root=root_path)
    promoted = [row for row in candidates if row.lifecycle_state == RecordLifecycleState.PROMOTED.value]
    pending = [row for row in candidates if row.lifecycle_state == RecordLifecycleState.CANDIDATE.value]
    return {
        "candidate_count": len(candidates),
        "promotable_candidate_count": len(pending),
        "promoted_candidate_count": len(promoted),
        "effective_control_status": (control_summary.get("effective") or {}).get("effective_status"),
        "promotion_freeze_active": bool(((control_summary.get("effective") or {}).get("emergency_flags") or {}).get("promotion_freeze")),
        "memory_freeze_active": bool(((control_summary.get("effective") or {}).get("emergency_flags") or {}).get("memory_freeze")),
        "latest_blocked_action": control_summary.get("latest_blocked_action"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current promotion governance summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_promotion_governance_summary(root=Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
