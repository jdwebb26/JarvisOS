#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import (
    AuthorityClass,
    DegradationEventRecord,
    DegradationEventStatus,
    DegradationMode,
    DegradationPolicyRecord,
    new_id,
    now_iso,
)


DEGRADATION_MODE_PROFILES: dict[str, dict[str, Any]] = {
    DegradationMode.NONE.value: {
        "fallback_allowed": False,
        "fallback_action": "none",
        "operator_notification_required": False,
        "retry_policy": {"strategy": "none", "max_attempts": 0},
    },
    DegradationMode.HOLD.value: {
        "fallback_allowed": False,
        "fallback_action": "hold",
        "operator_notification_required": True,
        "retry_policy": {"strategy": "manual_retry", "max_attempts": 1},
    },
    DegradationMode.LOCAL_ONLY.value: {
        "fallback_allowed": True,
        "fallback_action": "local_only_execution",
        "operator_notification_required": True,
        "retry_policy": {"strategy": "manual_retry", "max_attempts": 1},
    },
    DegradationMode.REVIEW_ONLY.value: {
        "fallback_allowed": False,
        "fallback_action": "review_only_hold",
        "operator_notification_required": True,
        "retry_policy": {"strategy": "manual_review_restore", "max_attempts": 1},
    },
    DegradationMode.READ_ONLY.value: {
        "fallback_allowed": True,
        "fallback_action": "read_only_mode",
        "operator_notification_required": True,
        "retry_policy": {"strategy": "auto_retry", "max_attempts": 3},
    },
    DegradationMode.STOPPED.value: {
        "fallback_allowed": False,
        "fallback_action": "stopped",
        "operator_notification_required": True,
        "retry_policy": {"strategy": "manual_restore", "max_attempts": 1},
    },
    "BURST_WORKER_OFFLINE": {
        "fallback_allowed": True,
        "fallback_action": "primary_node_only",
        "operator_notification_required": True,
        "retry_policy": {"strategy": "auto_retry", "max_attempts": 3},
    },
    "RESEARCH_BACKEND_DOWN": {
        "fallback_allowed": True,
        "fallback_action": "summary_only_if_allowed",
        "operator_notification_required": True,
        "retry_policy": {"strategy": "manual_retry", "max_attempts": 1},
    },
    "NVIDIA_LANE_DOWN": {
        "fallback_allowed": True,
        "fallback_action": "hold_or_manual_reroute",
        "operator_notification_required": True,
        "retry_policy": {"strategy": "manual_retry", "max_attempts": 1},
    },
    "AMD_LANE_DOWN": {
        "fallback_allowed": True,
        "fallback_action": "hold_or_manual_reroute",
        "operator_notification_required": True,
        "retry_policy": {"strategy": "manual_retry", "max_attempts": 1},
    },
    "FALLBACK_SUMMARY_ONLY": {
        "fallback_allowed": True,
        "fallback_action": "summary_only",
        "operator_notification_required": True,
        "retry_policy": {"strategy": "manual_retry", "max_attempts": 1},
    },
}


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
    {
        "subsystem": "burst_worker",
        "degradation_mode": "BURST_WORKER_OFFLINE",
        "fallback_action": "primary_node_only",
        "requires_operator_notification": True,
        "auto_recover": True,
        "retry_policy": {"strategy": "auto_retry", "max_attempts": 3},
    },
    {
        "subsystem": "research_backend",
        "degradation_mode": "RESEARCH_BACKEND_DOWN",
        "fallback_action": "summary_only_if_allowed",
        "requires_operator_notification": True,
        "auto_recover": False,
        "retry_policy": {"strategy": "manual_retry", "max_attempts": 1},
    },
    {
        "subsystem": "nvidia_lane",
        "degradation_mode": "NVIDIA_LANE_DOWN",
        "fallback_action": "hold_or_manual_reroute",
        "requires_operator_notification": True,
        "auto_recover": True,
        "retry_policy": {"strategy": "manual_retry", "max_attempts": 1},
    },
    {
        "subsystem": "amd_lane",
        "degradation_mode": "AMD_LANE_DOWN",
        "fallback_action": "hold_or_manual_reroute",
        "requires_operator_notification": True,
        "auto_recover": True,
        "retry_policy": {"strategy": "manual_retry", "max_attempts": 1},
    },
    {
        "subsystem": "summary_fallback",
        "degradation_mode": "FALLBACK_SUMMARY_ONLY",
        "fallback_action": "summary_only",
        "requires_operator_notification": True,
        "auto_recover": False,
        "retry_policy": {"strategy": "manual_retry", "max_attempts": 1},
    },
]


_AUTHORITY_FLOOR_ORDER = {
    AuthorityClass.OBSERVE_ONLY.value: 0,
    AuthorityClass.SUGGEST_ONLY.value: 1,
    AuthorityClass.REVIEW_REQUIRED.value: 2,
    AuthorityClass.APPROVAL_REQUIRED.value: 3,
    AuthorityClass.EXECUTE_BOUNDED.value: 2,
}


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


def load_degradation_policies(root: Optional[Path] = None) -> list[DegradationPolicyRecord]:
    ensure_default_degradation_policies(root=root)
    return list_degradation_policies(root=root)


def _mode_profile(mode: str) -> dict[str, Any]:
    profile = DEGRADATION_MODE_PROFILES.get(mode, {})
    return {
        "fallback_allowed": bool(profile.get("fallback_allowed", False)),
        "fallback_action": str(profile.get("fallback_action", "")),
        "operator_notification_required": bool(profile.get("operator_notification_required", True)),
        "retry_policy": dict(profile.get("retry_policy", {"strategy": "manual_retry", "max_attempts": 1})),
    }


def _normalize_authority_class(authority_class: Optional[str]) -> str:
    return AuthorityClass.coerce(
        str(authority_class or AuthorityClass.SUGGEST_ONLY.value).strip().lower(),
        default=AuthorityClass.SUGGEST_ONLY,
    ).value


def _authority_rank(authority_class: Optional[str]) -> int:
    return _AUTHORITY_FLOOR_ORDER.get(_normalize_authority_class(authority_class), 1)


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


def list_active_degradation_modes(root: Optional[Path] = None) -> list[dict[str, Any]]:
    ensure_default_degradation_policies(root=root)
    latest_by_subsystem: dict[str, DegradationEventRecord] = {}
    for event in list_degradation_events(root=root):
        if event.status not in {DegradationEventStatus.RECORDED.value, DegradationEventStatus.APPLIED.value}:
            continue
        latest_by_subsystem.setdefault(event.subsystem, event)
    active = []
    for subsystem, event in sorted(latest_by_subsystem.items()):
        active.append(
            {
                "subsystem": subsystem,
                "degradation_mode": event.degradation_mode,
                "fallback_action": event.fallback_action,
                "status": event.status,
                "requires_operator_notification": event.requires_operator_notification,
                "degradation_event_id": event.degradation_event_id,
                "reason": event.reason,
            }
        )
    return active


def retry_policy_for_subsystem(subsystem: str, *, root: Optional[Path] = None) -> dict[str, Any]:
    ensure_default_degradation_policies(root=root)
    policy = load_degradation_policy_for_subsystem(subsystem, root=root)
    if policy is not None and policy.retry_policy:
        return dict(policy.retry_policy)
    return _mode_profile(policy.degradation_mode if policy else DegradationMode.HOLD.value)["retry_policy"]


def operator_notification_required_for_subsystem(
    subsystem: str,
    *,
    degradation_mode: Optional[str] = None,
    root: Optional[Path] = None,
) -> bool:
    ensure_default_degradation_policies(root=root)
    policy = load_degradation_policy_for_subsystem(subsystem, root=root)
    if policy is not None:
        return bool(policy.requires_operator_notification)
    if degradation_mode:
        return bool(_mode_profile(degradation_mode)["operator_notification_required"])
    return True


def fallback_allowed(
    *,
    subsystem: str,
    authority_class: Optional[str] = None,
    degradation_mode: Optional[str] = None,
    fallback_action: Optional[str] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    ensure_default_degradation_policies(root=root)
    policy = load_degradation_policy_for_subsystem(subsystem, root=root)
    mode = degradation_mode or (policy.degradation_mode if policy else DegradationMode.HOLD.value)
    action = fallback_action or (policy.fallback_action if policy else _mode_profile(mode)["fallback_action"])
    authority = _normalize_authority_class(authority_class)
    profile = _mode_profile(mode)
    allowed = bool(profile["fallback_allowed"])
    reasons: list[str] = []

    if not allowed:
        reasons.append("policy_disallows_fallback")
    if action in {"summary_only", "summary_only_if_allowed"} and _authority_rank(authority) >= _authority_rank(
        AuthorityClass.REVIEW_REQUIRED.value
    ):
        allowed = False
        reasons.append("summary_only_fallback_forbidden_for_sensitive_authority")
    if action in {"hold", "stopped", "review_only_hold"}:
        allowed = False
        reasons.append("hold_style_modes_require_operator_resolution")
    if action == "local_only_execution" and authority == AuthorityClass.APPROVAL_REQUIRED.value:
        allowed = False
        reasons.append("approval_required_work_cannot_silently_drop_to_local_only")

    return {
        "allowed": allowed,
        "subsystem": subsystem,
        "authority_class": authority,
        "degradation_mode": mode,
        "fallback_action": action,
        "requires_operator_notification": operator_notification_required_for_subsystem(
            subsystem,
            degradation_mode=mode,
            root=root,
        ),
        "retry_policy": retry_policy_for_subsystem(subsystem, root=root),
        "reasons": reasons,
    }


def assert_no_forbidden_authority_downgrade(
    *,
    subsystem: str,
    authority_class: Optional[str] = None,
    degradation_mode: Optional[str] = None,
    fallback_action: Optional[str] = None,
    root: Optional[Path] = None,
) -> None:
    legality = fallback_allowed(
        subsystem=subsystem,
        authority_class=authority_class,
        degradation_mode=degradation_mode,
        fallback_action=fallback_action,
        root=root,
    )
    if legality["allowed"]:
        return
    if any("sensitive_authority" in reason or "approval_required" in reason for reason in legality["reasons"]):
        raise ValueError(
            f"Forbidden degraded fallback for {subsystem}: "
            f"{legality['degradation_mode']} -> {legality['fallback_action']} under {legality['authority_class']}"
        )


def degradation_retry_policy(
    *,
    subsystem: str,
    failure_count: int = 0,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    policy = retry_policy_for_subsystem(subsystem, root=root)
    max_attempts = int(policy.get("max_attempts", 1) or 1)
    return {
        **policy,
        "attempts_remaining": max(max_attempts - int(failure_count or 0), 0),
        "retry_allowed": int(failure_count or 0) < max_attempts,
    }


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
    ensure_default_degradation_policies(root=root)
    policy = load_degradation_policy_for_subsystem(subsystem, root=root)
    mode_profile = _mode_profile(policy.degradation_mode if policy else "")
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
            fallback_action=policy.fallback_action if policy else mode_profile["fallback_action"],
            requires_operator_notification=bool(policy.requires_operator_notification) if policy else mode_profile["operator_notification_required"],
            auto_recover=bool(policy.auto_recover) if policy else False,
            retry_policy=dict(policy.retry_policy) if policy and policy.retry_policy else mode_profile["retry_policy"],
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
    mode_counts: dict[str, int] = {}
    operator_notification_count = 0
    for row in events:
        subsystem_counts[row.subsystem] = subsystem_counts.get(row.subsystem, 0) + 1
        status_counts[row.status] = status_counts.get(row.status, 0) + 1
        mode_counts[row.degradation_mode] = mode_counts.get(row.degradation_mode, 0) + 1
        if row.requires_operator_notification:
            operator_notification_count += 1
    active_modes = list_active_degradation_modes(root=root)
    return {
        "degradation_policy_count": len(policies),
        "degradation_event_count": len(events),
        "degradation_event_subsystem_counts": subsystem_counts,
        "degradation_event_status_counts": status_counts,
        "degradation_event_mode_counts": mode_counts,
        "active_degradation_modes": active_modes,
        "active_degradation_mode_count": len(active_modes),
        "operator_notification_required_event_count": operator_notification_count,
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
