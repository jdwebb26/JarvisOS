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

from runtime.core.models import EvalProfileRecord, TaskType, now_iso


def eval_profiles_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "eval_profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _profile_path(profile_id: str, profile_version: str, *, root: Optional[Path] = None) -> Path:
    safe_id = f"{profile_id}__{profile_version}".replace("/", "_")
    return eval_profiles_dir(root) / f"{safe_id}.json"


def save_eval_profile(record: EvalProfileRecord, *, root: Optional[Path] = None) -> EvalProfileRecord:
    record.updated_at = now_iso()
    _profile_path(record.profile_id, record.profile_version, root=root).write_text(
        json.dumps(record.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def list_eval_profiles(*, root: Optional[Path] = None) -> list[EvalProfileRecord]:
    rows: list[EvalProfileRecord] = []
    for path in eval_profiles_dir(root).glob("*.json"):
        try:
            rows.append(EvalProfileRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: (row.updated_at, row.created_at, row.profile_version), reverse=True)
    return rows


def load_eval_profile(
    profile_id: str,
    *,
    profile_version: Optional[str] = None,
    root: Optional[Path] = None,
) -> Optional[EvalProfileRecord]:
    candidates = [row for row in list_eval_profiles(root=root) if row.profile_id == profile_id]
    if profile_version is not None:
        candidates = [row for row in candidates if row.profile_version == profile_version]
    return candidates[0] if candidates else None


def resolve_eval_profile(
    *,
    task_type: str,
    profile_id: Optional[str] = None,
    profile_version: Optional[str] = None,
    root: Optional[Path] = None,
) -> Optional[EvalProfileRecord]:
    ensure_default_eval_profiles(root=root)
    if profile_id:
        return load_eval_profile(profile_id, profile_version=profile_version, root=root)
    matches = [row for row in list_eval_profiles(root=root) if row.task_type == task_type]
    return matches[0] if matches else None


def ensure_default_eval_profiles(*, root: Optional[Path] = None) -> list[EvalProfileRecord]:
    root_path = Path(root or ROOT).resolve()
    defaults: list[EvalProfileRecord] = [
        EvalProfileRecord(
            profile_id="eval_profile_general",
            profile_version="v1",
            task_type=TaskType.GENERAL.value,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor="system",
            lane="eval",
            eval_command="replay_trace_to_eval",
            veto_checks=[
                {"name": "trace_status_completed", "kind": "trace_status_equals", "expected": "completed"},
            ],
            quality_metrics=[
                {"metric": "score", "minimum": 1.0},
            ],
            hard_fail_conditions=["trace_error_present"],
            reproducibility_requirements={"requires_replay_payload": True},
            promotion_thresholds={"minimum_score": 1.0},
        ),
        EvalProfileRecord(
            profile_id="eval_profile_code",
            profile_version="v1",
            task_type=TaskType.CODE.value,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor="system",
            lane="eval",
            eval_command="replay_trace_to_eval",
            veto_checks=[
                {"name": "trace_status_completed", "kind": "trace_status_equals", "expected": "completed"},
            ],
            quality_metrics=[
                {"metric": "score", "minimum": 1.0},
            ],
            hard_fail_conditions=["trace_error_present"],
            reproducibility_requirements={"requires_replay_payload": True},
            promotion_thresholds={"minimum_score": 1.0},
        ),
        EvalProfileRecord(
            profile_id="eval_profile_deploy",
            profile_version="v1",
            task_type=TaskType.DEPLOY.value,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor="system",
            lane="eval",
            eval_command="replay_trace_to_eval",
            veto_checks=[
                {"name": "trace_status_completed", "kind": "trace_status_equals", "expected": "completed"},
            ],
            quality_metrics=[
                {"metric": "score", "minimum": 1.0},
            ],
            hard_fail_conditions=["trace_error_present"],
            reproducibility_requirements={"requires_replay_payload": True},
            promotion_thresholds={"minimum_score": 1.0},
        ),
        EvalProfileRecord(
            profile_id="eval_profile_research",
            profile_version="v1",
            task_type=TaskType.RESEARCH.value,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor="system",
            lane="eval",
            eval_command="replay_trace_to_eval",
            veto_checks=[
                {"name": "trace_status_completed", "kind": "trace_status_equals", "expected": "completed"},
            ],
            quality_metrics=[
                {"metric": "score", "minimum": 1.0},
            ],
            hard_fail_conditions=["trace_error_present"],
            reproducibility_requirements={"requires_replay_payload": True},
            promotion_thresholds={"minimum_score": 1.0},
        ),
    ]
    saved: list[EvalProfileRecord] = []
    for record in defaults:
        if load_eval_profile(record.profile_id, profile_version=record.profile_version, root=root_path) is None:
            save_eval_profile(record, root=root_path)
        saved.append(load_eval_profile(record.profile_id, profile_version=record.profile_version, root=root_path) or record)
    return saved


def build_eval_profile_summary(*, root: Optional[Path] = None) -> dict:
    ensure_default_eval_profiles(root=root)
    profiles = list_eval_profiles(root=root)
    latest = profiles[0] if profiles else None
    by_task_type: dict[str, int] = {}
    for row in profiles:
        by_task_type[row.task_type] = by_task_type.get(row.task_type, 0) + 1
    return {
        "eval_profile_count": len(profiles),
        "eval_profile_task_type_counts": by_task_type,
        "latest_eval_profile": latest.to_dict() if latest else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current EvalProfile summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_eval_profile_summary(root=Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
