#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import (
    AuthorityClass,
    BackendRuntime,
    RoutingReason,
    TaskLeaseRecord,
    new_id,
    now_iso,
)
from runtime.core.node_registry import ensure_default_nodes, get_node


ACTIVE_LEASE_STATUSES = {"active", "renewed"}
TERMINAL_LEASE_STATUSES = {"expired", "requeued", "released"}


def task_leases_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "task_leases"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(task_lease_id: str, *, root: Optional[Path] = None) -> Path:
    return task_leases_dir(root=root) / f"{task_lease_id}.json"


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _save(record: TaskLeaseRecord, *, root: Optional[Path] = None) -> TaskLeaseRecord:
    record.updated_at = now_iso()
    _path(record.task_lease_id, root=root).write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return record


def load_task_lease(task_lease_id: str, *, root: Optional[Path] = None) -> Optional[TaskLeaseRecord]:
    path = _path(task_lease_id, root=root)
    if not path.exists():
        return None
    try:
        return TaskLeaseRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def list_task_leases(*, root: Optional[Path] = None) -> list[TaskLeaseRecord]:
    rows: list[TaskLeaseRecord] = []
    for path in sorted(task_leases_dir(root=root).glob("*.json")):
        try:
            rows.append(TaskLeaseRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows.sort(key=lambda row: (row.updated_at, row.created_at), reverse=True)
    return rows


def get_active_lease(task_id: str, *, root: Optional[Path] = None) -> Optional[TaskLeaseRecord]:
    for row in list_task_leases(root=root):
        if row.task_id == task_id and row.lease_status in ACTIVE_LEASE_STATUSES:
            return row
    return None


def create_task_lease(
    *,
    task_id: str,
    holder_node_id: str,
    actor: str,
    lane: str,
    holder_backend_runtime: str = BackendRuntime.UNASSIGNED.value,
    authority_class: str = AuthorityClass.SUGGEST_ONLY.value,
    lease_duration_seconds: int = 900,
    lease_expires_at: Optional[str] = None,
    routing_reason: str = RoutingReason.POLICY_DEFAULT.value,
    source_refs: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> TaskLeaseRecord:
    ensure_default_nodes(root=root)
    if get_node(holder_node_id, root=root) is None:
        raise ValueError(f"Unknown holder node: {holder_node_id}")
    existing = get_active_lease(task_id, root=root)
    if existing is not None:
        return existing
    timestamp = now_iso()
    expiry = lease_expires_at
    if expiry is None:
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=max(int(lease_duration_seconds), 1))).isoformat()
    record = TaskLeaseRecord(
        task_lease_id=new_id("lease"),
        task_id=task_id,
        created_at=timestamp,
        updated_at=timestamp,
        actor=actor,
        lane=lane,
        holder_node_id=holder_node_id,
        holder_backend_runtime=holder_backend_runtime,
        authority_class=authority_class,
        lease_status="active",
        lease_expires_at=expiry,
        routing_reason=routing_reason,
        source_refs=dict(source_refs or {}),
        metadata={
            "checkpoint_summary": "",
            "progress_summary": "",
            "requeue_target": None,
            "requeue_reason": "",
            **dict(metadata or {}),
        },
    )
    return _save(record, root=root)


def renew_task_lease(
    *,
    task_lease_id: str,
    actor: str,
    lane: str,
    lease_duration_seconds: int = 900,
    lease_expires_at: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> TaskLeaseRecord:
    record = load_task_lease(task_lease_id, root=root)
    if record is None:
        raise ValueError(f"Task lease not found: {task_lease_id}")
    if record.lease_status in TERMINAL_LEASE_STATUSES:
        raise ValueError(f"Cannot renew terminal task lease: {task_lease_id}")
    expiry = lease_expires_at
    if expiry is None:
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=max(int(lease_duration_seconds), 1))).isoformat()
    record.actor = actor
    record.lane = lane
    record.lease_status = "renewed"
    record.lease_expires_at = expiry
    if metadata:
        record.metadata = {**dict(record.metadata or {}), **dict(metadata)}
    return _save(record, root=root)


def expire_stale_leases(
    *,
    actor: str = "system",
    lane: str = "task_lease",
    now: Optional[str] = None,
    root: Optional[Path] = None,
) -> list[TaskLeaseRecord]:
    now_dt = _parse_iso(now) or datetime.now(timezone.utc)
    expired: list[TaskLeaseRecord] = []
    for row in list_task_leases(root=root):
        if row.lease_status not in ACTIVE_LEASE_STATUSES:
            continue
        expiry_dt = _parse_iso(row.lease_expires_at)
        if expiry_dt is None or expiry_dt > now_dt:
            continue
        row.actor = actor
        row.lane = lane
        row.lease_status = "expired"
        row.metadata = {
            **dict(row.metadata or {}),
            "expired_at": now_dt.isoformat(),
            "reclaimable": True,
            "requeue_reason": (row.metadata or {}).get("requeue_reason") or "lease_expired",
        }
        expired.append(_save(row, root=root))
    return expired


def requeue_expired_lease(
    *,
    task_lease_id: str,
    actor: str,
    lane: str,
    requeue_target: str = "primary",
    requeue_reason: str = "lease_expired_reclaim",
    metadata: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> TaskLeaseRecord:
    record = load_task_lease(task_lease_id, root=root)
    if record is None:
        raise ValueError(f"Task lease not found: {task_lease_id}")
    if record.lease_status != "expired":
        raise ValueError(f"Only expired leases can be marked for requeue: {task_lease_id}")
    record.actor = actor
    record.lane = lane
    record.lease_status = "requeued"
    record.metadata = {
        **dict(record.metadata or {}),
        "reclaimable": True,
        "requeue_target": requeue_target,
        "requeue_reason": requeue_reason,
        "requeue_marked_at": now_iso(),
        **dict(metadata or {}),
    }
    return _save(record, root=root)


def build_task_lease_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    rows = list_task_leases(root=root)
    status_counts: dict[str, int] = {}
    holder_counts: dict[str, int] = {}
    reclaimable_count = 0
    for row in rows:
        status_counts[row.lease_status] = status_counts.get(row.lease_status, 0) + 1
        holder_counts[row.holder_node_id] = holder_counts.get(row.holder_node_id, 0) + 1
        if bool((row.metadata or {}).get("reclaimable", False)):
            reclaimable_count += 1
    active = [row.to_dict() for row in rows if row.lease_status in ACTIVE_LEASE_STATUSES]
    expired = [row.to_dict() for row in rows if row.lease_status == "expired"]
    requeued = [row.to_dict() for row in rows if row.lease_status == "requeued"]
    return {
        "task_lease_count": len(rows),
        "active_task_lease_count": len(active),
        "expired_task_lease_count": len(expired),
        "requeued_task_lease_count": len(requeued),
        "reclaimable_task_lease_count": reclaimable_count,
        "task_lease_status_counts": status_counts,
        "task_lease_holder_counts": holder_counts,
        "latest_task_lease": rows[0].to_dict() if rows else None,
        "active_task_leases": active[:10],
        "expired_task_leases": expired[:10],
        "requeued_task_leases": requeued[:10],
    }

