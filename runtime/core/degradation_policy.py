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
    DegradationEventRecord,
    DegradationEventStatus,
    DegradationPolicyRecord,
    new_id,
    now_iso,
)


DEFAULT_POLICIES = [
    {
        "subsystem": "hermes_adapter",
        "degradation_mode": "fail_closed",
        "fallback_action": "no_local_fallback",
        "requires_operator_notification": True,
        "auto_recover": False,
        "retry_policy": {"strategy": "manual_retry", "max_attempts": 1},
    },
    {
        "subsystem": "reviewer_lane",
        "degradation_mode": "review_hold",
        "fallback_action": "no_auto_promotion",
        "requires_operator_notification": True,
        "auto_recover": False,
        "retry_policy": {"strategy": "manual_review_restore", "max_attempts": 1},
    },
    {
        "subsystem": "auditor_lane",
        "degradation_mode": "review_hold",
        "fallback_action": "no_auto_promotion",
        "requires_operator_notification": True,
        "auto_recover": False,
        "retry_policy": {"strategy": "manual_auditor_restore", "max_attempts": 1},
    },
    {
        "subsystem": "browser_backend",
        "degradation_mode": "fail_closed",
        "fallback_action": "no_browser_execution",
        "requires_operator_notification": True,
        "auto_recover": False,
        "retry_policy": {"strategy": "manual_retry", "max_attempts": 1},
    },
    {
        "subsystem": "voice_pipeline",
        "degradation_mode": "text_fallback",
        "fallback_action": "text_input_only",
        "requires_operator_notification": True,
        "auto_recover": True,
        "retry_policy": {"strategy": "auto_retry", "max_attempts": 3},
    },
    {
        "subsystem": "desktop_executor",
        "degradation_mode": "fail_closed",
        "fallback_action": "no_desktop_execution",
        "requires_operator_notification": True,
        "auto_recover": False,
        "retry_policy": {"strategy": "manual_retry", "max_attempts": 1},
    },
    {
        "subsystem": "memory_spine",
        "degradation_mode": "read_only",
        "fallback_action": "no_memory_writes",
        "requires_operator_notification": True,
        "auto_recover": True,
        "retry_policy": {"strategy": "auto_retry", "max_attempts": 3},
    },
    {
        "subsystem": "speaker_guard",
        "degradation_mode": "require_text_confirm",
        "fallback_action": "voice_commands_require_text_confirmation",
        "requires_operator_notification": True,
        "auto_recover": True,
        "retry_policy": {"strategy": "auto_retry", "max_attempts": 3},
    },
]


def degradation_policies_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "degradation_policies"
    path.mkdir(parents=True, exist_ok=True)
    return path


def degradation_events_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "degradation_events"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(folder: Path, record_id: str) -> Path:
    return folder / f"{record_id}.json"


def _save(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def save_degradation_policy(record: DegradationPolicyRecord, *, root: Optional[Path] = None) -> DegradationPolicyRecord:
    record.updated_at = now_iso()
    _save(_path(degradation_policies_dir(root), record.degradation_policy_id), record.to_dict())
    return record


def save_degradation_event(record: DegradationEventRecord, *, root: Optional[Path] = None) -> DegradationEventRecord:
    record.updated_at = now_iso()
    _save(_path(degradation_events_dir(root), record.degradation_event_id), record.to_dict())
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


def list_degradation_policies(root: Optional[Path] = None) -> list[DegradationPolicyRecord]:
    return _load_rows(degradation_policies_dir(root), DegradationPolicyRecord)


def list_degradation_events(root: Optional[Path] = None) -> list[DegradationEventRecord]:
    return _load_rows(degradation_events_dir(root), DegradationEventRecord)


def load_degradation_policy_for_subsystem(subsystem: str, *, root: Optional[Path] = None) -> Optional[DegradationPolicyRecord]:
    for row in list_degradation_policies(root=root):
        if row.subsystem == subsystem:
            return row
    return None


def ensure_default_degradation_policies(root: Optional[Path] = None) -> list[DegradationPolicyRecord]:
    root_path = Path(root or ROOT).resolve()
    created_or_existing: list[DegradationPolicyRecord] = []
    for row in DEFAULT_POLICIES:
        existing = load_degradation_policy_for_subsystem(row["subsystem"], root=root_path)
        if existing is not None:
            created_or_existing.append(existing)
            continue
        created_or_existing.append(
            save_degradation_policy(
                DegradationPolicyRecord(
                    degradation_policy_id=new_id("degpol"),
                    subsystem=row["subsystem"],
                    created_at=now_iso(),
                    updated_at=now_iso(),
                    actor="system",
                    lane="bootstrap",
                    degradation_mode=row["degradation_mode"],
                    fallback_action=row["fallback_action"],
                    requires_operator_notification=row["requires_operator_notification"],
                    auto_recover=row["auto_recover"],
                    retry_policy=dict(row["retry_policy"]),
                ),
                root=root_path,
            )
        )
    return created_or_existing


def record_degradation_event(
    *,
    subsystem: str,
    actor: str,
    lane: str,
    failure_category: str,
    reason: str,
    task_id: Optional[str] = None,
    source_refs: Optional[dict] = None,
    status: str = DegradationEventStatus.RECORDED.value,
    root: Optional[Path] = None,
) -> DegradationEventRecord:
    policy = load_degradation_policy_for_subsystem(subsystem, root=root)
    return save_degradation_event(
        DegradationEventRecord(
            degradation_event_id=new_id("degev"),
            subsystem=subsystem,
            degradation_policy_id=policy.degradation_policy_id if policy else None,
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=actor,
            lane=lane,
            failure_category=failure_category,
            degradation_mode=policy.degradation_mode if policy else "",
            fallback_action=policy.fallback_action if policy else "",
            requires_operator_notification=bool(policy.requires_operator_notification) if policy else False,
            auto_recover=bool(policy.auto_recover) if policy else False,
            retry_policy=dict(policy.retry_policy) if policy else {},
            status=status,
            reason=reason,
            source_refs=dict(source_refs or {}),
        ),
        root=root,
    )


def build_degradation_summary(root: Optional[Path] = None) -> dict:
    ensure_default_degradation_policies(root=root)
    policies = list_degradation_policies(root=root)
    events = list_degradation_events(root=root)
    subsystem_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for row in events:
        subsystem_counts[row.subsystem] = subsystem_counts.get(row.subsystem, 0) + 1
        status_counts[row.status] = status_counts.get(row.status, 0) + 1
    return {
        "degradation_policy_count": len(policies),
        "degradation_event_count": len(events),
        "degradation_event_subsystem_counts": subsystem_counts,
        "degradation_event_status_counts": status_counts,
        "latest_degradation_policy": policies[0].to_dict() if policies else None,
        "latest_degradation_event": events[0].to_dict() if events else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the current DegradationPolicy summary.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()
    print(json.dumps(build_degradation_summary(Path(args.root).resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
