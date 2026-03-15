#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.dashboard.task_board import build_task_board
from runtime.gateway.review_inbox import build_review_inbox


SYNC_NAMESPACE = "jarvis_read_model"


def _stable_int_id(value: str) -> int:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:15]
    return int(digest, 16)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iso_to_unix(value: str | None) -> int:
    if not value:
        return int(datetime.now(tz=timezone.utc).timestamp())
    text = str(value).strip()
    if not text:
        return int(datetime.now(tz=timezone.utc).timestamp())
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        pass
    try:
        return int(float(text))
    except ValueError:
        return int(datetime.now(tz=timezone.utc).timestamp())


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _normalize_priority(priority: str, risk_level: str) -> str:
    text = str(priority or "").strip().lower()
    risk = str(risk_level or "").strip().lower()
    if text in {"urgent", "critical"} or risk in {"high_stakes", "critical"}:
        return "urgent"
    if text in {"high", "elevated"} or risk in {"high", "medium_high"}:
        return "high"
    if text in {"low"}:
        return "low"
    return "medium"


def _normalize_task_status(status: str) -> str:
    text = str(status or "").strip().lower()
    mapping = {
        "queued": "inbox",
        "running": "in_progress",
        "waiting_review": "review",
        "waiting_approval": "quality_review",
        "ready_to_ship": "done",
        "shipped": "done",
        "completed": "done",
    }
    return mapping.get(text, "inbox")


def _task_description(row: dict[str, Any]) -> str:
    lines: list[str] = []
    summary = str(row.get("summary") or "").strip()
    checkpoint = str(row.get("checkpoint_summary") or "").strip()
    last_error = str(row.get("last_error") or "").strip()
    if summary:
        lines.append(summary)
    if checkpoint and checkpoint != summary:
        lines.append(f"Checkpoint: {checkpoint}")
    if last_error:
        lines.append(f"Last error: {last_error}")
    return "\n\n".join(lines)


def _task_tags(row: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for value in (
        row.get("task_type"),
        row.get("risk_level"),
        row.get("status"),
        row.get("execution_backend"),
        row.get("assigned_model"),
    ):
        text = str(value or "").strip()
        if text and text.lower() != "unassigned":
            tags.append(text)
    return tags[:8]


def _task_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": SYNC_NAMESPACE,
        "source_task_id": row.get("task_id"),
        "source_status": row.get("status"),
        "source_priority": row.get("priority"),
        "lifecycle_state": row.get("lifecycle_state"),
        "review_required": bool(row.get("review_required")),
        "approval_required": bool(row.get("approval_required")),
        "execution_backend": row.get("execution_backend"),
        "assigned_model": row.get("assigned_model"),
        "related_review_ids": list(row.get("related_review_ids") or []),
        "related_approval_ids": list(row.get("related_approval_ids") or []),
        "promoted_artifact_id": row.get("promoted_artifact_id"),
        "producer_metadata": dict(row.get("producer_metadata") or {}),
        "provenance_metadata": dict(row.get("provenance_metadata") or {}),
        "evidence_metadata": dict(row.get("evidence_metadata") or {}),
    }


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _insert(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    columns = _existing_columns(conn, table)
    payload = {key: value for key, value in row.items() if key in columns}
    keys = list(payload.keys())
    placeholders = ", ".join("?" for _ in keys)
    sql = f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({placeholders})"
    conn.execute(sql, [payload[key] for key in keys])


def _delete_prior_sync_rows(conn: sqlite3.Connection, workspace_id: int) -> None:
    task_ids = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM tasks WHERE workspace_id = ? AND created_by = ?",
            (workspace_id, SYNC_NAMESPACE),
        ).fetchall()
    ]
    conn.execute(
        "DELETE FROM notifications WHERE workspace_id = ? AND type IN (?, ?)",
        (workspace_id, "jarvis_pending_review", "jarvis_pending_approval"),
    )
    conn.execute(
        "DELETE FROM activities WHERE workspace_id = ? AND type IN (?, ?, ?)",
        (workspace_id, "jarvis_task_sync", "jarvis_pending_review", "jarvis_pending_approval"),
    )
    conn.execute(
        "DELETE FROM agents WHERE workspace_id = ? AND config LIKE ?",
        (workspace_id, f'%"{SYNC_NAMESPACE}"%'),
    )
    if task_ids:
        placeholders = ", ".join("?" for _ in task_ids)
        conn.execute(
            f"DELETE FROM quality_reviews WHERE workspace_id = ? AND task_id IN ({placeholders})",
            [workspace_id, *task_ids],
        )
        conn.execute(
            f"DELETE FROM tasks WHERE workspace_id = ? AND id IN ({placeholders})",
            [workspace_id, *task_ids],
        )


@dataclass
class SyncResult:
    task_count: int
    agent_count: int
    notification_count: int
    activity_count: int
    knowledge_files: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_count": self.task_count,
            "agent_count": self.agent_count,
            "notification_count": self.notification_count,
            "activity_count": self.activity_count,
            "knowledge_files": self.knowledge_files,
        }


def sync_mission_control_read_model(
    *,
    root: Path,
    mission_control_db: Path,
    knowledge_base_dir: Path | None,
    workspace_id: int,
    refresh_exports: bool,
) -> SyncResult:
    if refresh_exports:
        build_task_board(root)
        build_review_inbox(root)
        build_operator_snapshot(root)
        build_state_export(root)

    task_board = _load_json(root / "state" / "logs" / "task_board.json")
    review_inbox = _load_json(root / "state" / "logs" / "review_inbox.json")
    operator_snapshot = _load_json(root / "state" / "logs" / "operator_snapshot.json")
    state_export = _load_json(root / "state" / "logs" / "state_export.json")

    doctor_report_path = root / "state" / "logs" / "doctor_report.json"
    validate_report_path = root / "state" / "logs" / "validate_report.json"
    smoke_report_path = root / "state" / "logs" / "smoke_test_report.json"
    handoff_pack_path = root / "state" / "logs" / "operator_handoff_pack.json"

    conn = sqlite3.connect(mission_control_db)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            _delete_prior_sync_rows(conn, workspace_id)

            task_id_map: dict[str, int] = {}
            task_rows = list(task_board.get("rows") or [])
            for source_row in task_rows:
                source_task_id = str(source_row.get("task_id") or "")
                if not source_task_id:
                    continue
                task_id = _stable_int_id(f"task:{source_task_id}")
                task_id_map[source_task_id] = task_id
                _insert(
                    conn,
                    "tasks",
                    {
                        "id": task_id,
                        "title": str(source_row.get("summary") or source_task_id)[:255],
                        "description": _task_description(source_row),
                        "status": _normalize_task_status(str(source_row.get("status") or "")),
                        "priority": _normalize_priority(
                            str(source_row.get("priority") or ""),
                            str(source_row.get("risk_level") or ""),
                        ),
                        "assigned_to": (
                            str(source_row.get("execution_backend") or "").strip()
                            if str(source_row.get("execution_backend") or "").strip().lower() != "unassigned"
                            else None
                        ),
                        "created_by": SYNC_NAMESPACE,
                        "created_at": _iso_to_unix(str(source_row.get("updated_at") or "")),
                        "updated_at": _iso_to_unix(str(source_row.get("updated_at") or "")),
                        "tags": json.dumps(_task_tags(source_row)),
                        "metadata": json.dumps(_task_metadata(source_row), sort_keys=True),
                        "workspace_id": workspace_id,
                    },
                )
                _insert(
                    conn,
                    "activities",
                    {
                        "type": "jarvis_task_sync",
                        "entity_type": "task",
                        "entity_id": task_id,
                        "actor": SYNC_NAMESPACE,
                        "description": f"Synced {source_task_id} ({source_row.get('status')}) into Mission Control",
                        "data": json.dumps(
                            {
                                "source": SYNC_NAMESPACE,
                                "source_task_id": source_task_id,
                                "source_status": source_row.get("status"),
                            },
                            sort_keys=True,
                        ),
                        "created_at": _iso_to_unix(str(source_row.get("updated_at") or "")),
                        "workspace_id": workspace_id,
                    },
                )

            agent_names: set[str] = set()
            agent_task_counts: dict[str, int] = {}
            for row in task_rows:
                execution_backend = str(row.get("execution_backend") or "").strip()
                if execution_backend and execution_backend.lower() != "unassigned":
                    agent_names.add(execution_backend)
                    agent_task_counts[execution_backend] = agent_task_counts.get(execution_backend, 0) + 1
            for pending in list(review_inbox.get("pending_reviews") or []):
                reviewer = str(pending.get("reviewer_role") or "").strip()
                if reviewer:
                    agent_names.add(reviewer)
            for pending in list(review_inbox.get("pending_approvals") or []):
                reviewer = str(pending.get("requested_reviewer") or "").strip()
                if reviewer:
                    agent_names.add(reviewer)

            for agent_name in sorted(agent_names):
                role = "reviewer" if agent_name in {"anton", "archimedes", "operator"} else "runtime"
                status = "busy" if agent_task_counts.get(agent_name, 0) else "idle"
                _insert(
                    conn,
                    "agents",
                    {
                        "id": _stable_int_id(f"agent:{agent_name}"),
                        "name": agent_name,
                        "role": role,
                        "session_key": agent_name,
                        "status": status,
                        "last_seen": int(datetime.now(tz=timezone.utc).timestamp()),
                        "last_activity": f"Jarvis read-model sync imported {agent_task_counts.get(agent_name, 0)} task(s)",
                        "created_at": int(datetime.now(tz=timezone.utc).timestamp()),
                        "updated_at": int(datetime.now(tz=timezone.utc).timestamp()),
                        "config": json.dumps({"source": SYNC_NAMESPACE, "role": role}, sort_keys=True),
                        "workspace_id": workspace_id,
                    },
                )

            for pending in list(review_inbox.get("pending_reviews") or []):
                source_task_id = str(pending.get("task_id") or "")
                task_id = task_id_map.get(source_task_id)
                if not task_id:
                    continue
                reviewer = str(pending.get("reviewer_role") or "operator")
                summary = str(pending.get("summary") or source_task_id)
                created_at = int(datetime.now(tz=timezone.utc).timestamp())
                _insert(
                    conn,
                    "notifications",
                    {
                        "recipient": reviewer,
                        "type": "jarvis_pending_review",
                        "title": f"Pending review for {source_task_id}",
                        "message": summary,
                        "source_type": "task",
                        "source_id": task_id,
                        "created_at": created_at,
                        "workspace_id": workspace_id,
                    },
                )
                _insert(
                    conn,
                    "activities",
                    {
                        "type": "jarvis_pending_review",
                        "entity_type": "task",
                        "entity_id": task_id,
                        "actor": reviewer,
                        "description": f"Pending review {pending.get('review_id')} for {source_task_id}",
                        "data": json.dumps(pending, sort_keys=True),
                        "created_at": created_at,
                        "workspace_id": workspace_id,
                    },
                )

            for pending in list(review_inbox.get("pending_approvals") or []):
                source_task_id = str(pending.get("task_id") or "")
                task_id = task_id_map.get(source_task_id)
                if not task_id:
                    continue
                reviewer = str(pending.get("requested_reviewer") or "operator")
                summary = str(pending.get("summary") or source_task_id)
                created_at = int(datetime.now(tz=timezone.utc).timestamp())
                _insert(
                    conn,
                    "notifications",
                    {
                        "recipient": reviewer,
                        "type": "jarvis_pending_approval",
                        "title": f"Pending approval for {source_task_id}",
                        "message": summary,
                        "source_type": "task",
                        "source_id": task_id,
                        "created_at": created_at,
                        "workspace_id": workspace_id,
                    },
                )
                _insert(
                    conn,
                    "activities",
                    {
                        "type": "jarvis_pending_approval",
                        "entity_type": "task",
                        "entity_id": task_id,
                        "actor": reviewer,
                        "description": f"Pending approval {pending.get('approval_id')} for {source_task_id}",
                        "data": json.dumps(pending, sort_keys=True),
                        "created_at": created_at,
                        "workspace_id": workspace_id,
                    },
                )

        knowledge_files: list[str] = []
        if knowledge_base_dir is not None:
            knowledge_base_dir.mkdir(parents=True, exist_ok=True)
            payloads: dict[str, Any] = {
                "task_board.json": task_board,
                "review_inbox.json": review_inbox,
                "operator_snapshot.json": operator_snapshot,
                "state_export.json": state_export,
            }
            optional_files = {
                "doctor_report.json": doctor_report_path,
                "validate_report.json": validate_report_path,
                "smoke_test_report.json": smoke_report_path,
                "operator_handoff_pack.json": handoff_pack_path,
            }
            for name, payload in payloads.items():
                target = knowledge_base_dir / name
                target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                knowledge_files.append(str(target))
            for name, source_path in optional_files.items():
                if not source_path.exists():
                    continue
                target = knowledge_base_dir / name
                target.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
                knowledge_files.append(str(target))
            readme = knowledge_base_dir / "README.md"
            readme.write_text(
                "\n".join(
                    [
                        "# Mission Control Jarvis Read Model",
                        "",
                        "These files are projections from the Jarvis operator/runtime state.",
                        "Source of truth remains Jarvis/OpenClaw.",
                        "",
                        "- `task_board.json`: task board projection used for Mission Control sync",
                        "- `review_inbox.json`: pending review and approval inbox",
                        "- `operator_snapshot.json`: high-level operator snapshot",
                        "- `state_export.json`: broad state export",
                        "- `doctor_report.json`, `validate_report.json`, `smoke_test_report.json`: health evidence when present",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            knowledge_files.append(str(readme))

        result = SyncResult(
            task_count=len(task_rows),
            agent_count=len(agent_names),
            notification_count=len(list(review_inbox.get("pending_reviews") or [])) + len(list(review_inbox.get("pending_approvals") or [])),
            activity_count=len(task_rows) + len(list(review_inbox.get("pending_reviews") or [])) + len(list(review_inbox.get("pending_approvals") or [])),
            knowledge_files=knowledge_files,
        )
        report_path = root / "state" / "logs" / "mission_control_sync.json"
        _ensure_parent(report_path)
        report_path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        conn.close()


def _default_mission_control_db(mission_control_root: Path) -> Path:
    return mission_control_root / ".data" / "mission-control.db"


def main() -> int:
    parser = argparse.ArgumentParser(description="Project Jarvis read-model data into Mission Control.")
    parser.add_argument("--root", default=str(ROOT), help="Jarvis repo root")
    parser.add_argument("--mission-control-root", default="/tmp/mission-control", help="Mission Control install root")
    parser.add_argument("--mission-control-db", default="", help="Mission Control sqlite path")
    parser.add_argument("--knowledge-base-dir", default="", help="Optional directory to mirror JSON artifacts for the Mission Control memory browser")
    parser.add_argument("--workspace-id", type=int, default=1, help="Mission Control workspace id")
    parser.add_argument("--no-refresh", action="store_true", help="Skip rebuilding Jarvis read-model JSON before syncing")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    mission_control_root = Path(args.mission_control_root).resolve()
    mission_control_db = Path(args.mission_control_db).resolve() if args.mission_control_db else _default_mission_control_db(mission_control_root)
    knowledge_base_dir = Path(args.knowledge_base_dir).resolve() if args.knowledge_base_dir else None

    result = sync_mission_control_read_model(
        root=root,
        mission_control_db=mission_control_db,
        knowledge_base_dir=knowledge_base_dir,
        workspace_id=args.workspace_id,
        refresh_exports=not args.no_refresh,
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
