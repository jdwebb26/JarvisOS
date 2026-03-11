#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from runtime.core.models import (
    OperatorProfileRecord,
    ReplayExecutionRecord,
    ReplayResultKind,
    ReplayResultRecord,
    TrajectoryRecord,
    new_id,
    now_iso,
)


ROOT = Path(__file__).resolve().parents[2]


def _state_dir(name: str, root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def trajectories_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("trajectories", root=root)


def operator_profiles_dir(root: Optional[Path] = None) -> Path:
    return _state_dir("operator_profiles", root=root)


def _path(folder: Path, record_id: str) -> Path:
    return folder / f"{record_id}.json"


def _save(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def save_trajectory(record: TrajectoryRecord, *, root: Optional[Path] = None) -> TrajectoryRecord:
    record.updated_at = now_iso()
    _save(_path(trajectories_dir(root), record.trajectory_id), record.to_dict())
    return record


def save_operator_profile(record: OperatorProfileRecord, *, root: Optional[Path] = None) -> OperatorProfileRecord:
    record.updated_at = now_iso()
    _save(_path(operator_profiles_dir(root), record.operator_profile_id), record.to_dict())
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


def list_trajectories(root: Optional[Path] = None) -> list[TrajectoryRecord]:
    return _load_rows(trajectories_dir(root), TrajectoryRecord)


def list_operator_profiles(root: Optional[Path] = None) -> list[OperatorProfileRecord]:
    return _load_rows(operator_profiles_dir(root), OperatorProfileRecord)


def load_operator_profile_by_operator_id(operator_id: str, *, root: Optional[Path] = None) -> Optional[OperatorProfileRecord]:
    for row in list_operator_profiles(root=root):
        if row.operator_id == operator_id:
            return row
    return None


def ensure_operator_profile(operator_id: str, *, root: Optional[Path] = None) -> OperatorProfileRecord:
    existing = load_operator_profile_by_operator_id(operator_id, root=root)
    if existing is not None:
        return existing
    return save_operator_profile(
        OperatorProfileRecord(
            operator_profile_id=new_id("oprof"),
            operator_id=operator_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            notification_preference_refs=[],
            approval_surface_preference="default",
            verbosity_style="standard",
            escalation_rules_ref="",
        ),
        root=root,
    )


def _derive_outcome_quality(result: ReplayResultRecord) -> str:
    if result.result_kind == ReplayResultKind.MATCH.value:
        return "match"
    if result.result_kind == ReplayResultKind.DRIFT.value:
        return "drift"
    if result.result_kind == ReplayResultKind.BLOCKED_BY_CONTROL.value:
        return "blocked"
    if result.result_kind == ReplayResultKind.MISSING_SOURCE.value:
        return "missing_source"
    return "invalid"


def record_trajectory_from_replay(
    *,
    replay_execution: ReplayExecutionRecord,
    replay_result: ReplayResultRecord,
    root: Optional[Path] = None,
) -> TrajectoryRecord:
    root_path = Path(root or ROOT).resolve()
    from runtime.core.review_store import latest_review_for_task
    from runtime.core.task_store import load_task

    task = load_task(replay_result.task_id, root=root_path) if replay_result.task_id else None
    review = latest_review_for_task(replay_result.task_id, root=root_path) if replay_result.task_id else None
    expected = replay_result.expected_snapshot or {}
    observed = replay_result.observed_snapshot or {}
    tools_used = expected.get("tools_used") or observed.get("tools_used") or []
    ensure_operator_profile(replay_execution.actor, root=root_path)
    record = TrajectoryRecord(
        trajectory_id=new_id("traj"),
        task_id=replay_result.task_id,
        created_at=now_iso(),
        updated_at=now_iso(),
        prompt_class=replay_result.replay_kind,
        task_type=(task.task_type if task else ""),
        backend=(task.execution_backend if task else ""),
        tools_used=[str(item) for item in tools_used],
        outcome_quality=_derive_outcome_quality(replay_result),
        review_result=(review.status if review is not None else ""),
        replay_plan_id=expected.get("replay_plan_id") or observed.get("replay_plan_id"),
        replay_execution_id=replay_execution.replay_execution_id,
        replay_result_id=replay_result.replay_result_id,
        eval_result_id=expected.get("eval_result_id") or observed.get("eval_result_id"),
        trace_id=expected.get("trace_id") or observed.get("trace_id"),
        collection_policy="policy_controlled",
        sensitive_collection_enabled=False,
        source_refs={
            "source_record_id": replay_result.source_record_id,
            "drift_fields": list(replay_result.drift_fields),
            "reason": replay_result.reason,
        },
    )
    return save_trajectory(record, root=root_path)


def build_trajectory_summary(root: Optional[Path] = None) -> dict[str, Any]:
    rows = list_trajectories(root=root)
    outcome_counts: dict[str, int] = {}
    for row in rows:
        outcome_counts[row.outcome_quality] = outcome_counts.get(row.outcome_quality, 0) + 1
    return {
        "trajectory_count": len(rows),
        "trajectory_outcome_counts": outcome_counts,
        "latest_trajectory": rows[0].to_dict() if rows else None,
    }


def build_operator_profile_summary(root: Optional[Path] = None) -> dict[str, Any]:
    rows = list_operator_profiles(root=root)
    return {
        "operator_profile_count": len(rows),
        "latest_operator_profile": rows[0].to_dict() if rows else None,
    }
