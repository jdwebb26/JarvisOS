from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.mission_control_sync import sync_mission_control_read_model


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _init_mc_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE tasks (
              id INTEGER PRIMARY KEY,
              title TEXT,
              description TEXT,
              status TEXT,
              priority TEXT,
              assigned_to TEXT,
              created_by TEXT,
              created_at INTEGER,
              updated_at INTEGER,
              tags TEXT,
              metadata TEXT,
              workspace_id INTEGER
            );
            CREATE TABLE agents (
              id INTEGER PRIMARY KEY,
              name TEXT,
              role TEXT,
              session_key TEXT,
              status TEXT,
              last_seen INTEGER,
              last_activity TEXT,
              created_at INTEGER,
              updated_at INTEGER,
              config TEXT,
              workspace_id INTEGER
            );
            CREATE TABLE activities (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              type TEXT,
              entity_type TEXT,
              entity_id INTEGER,
              actor TEXT,
              description TEXT,
              data TEXT,
              created_at INTEGER,
              workspace_id INTEGER
            );
            CREATE TABLE notifications (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              recipient TEXT,
              type TEXT,
              title TEXT,
              message TEXT,
              source_type TEXT,
              source_id INTEGER,
              created_at INTEGER,
              workspace_id INTEGER
            );
            CREATE TABLE quality_reviews (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              task_id INTEGER,
              reviewer TEXT,
              status TEXT,
              notes TEXT,
              created_at INTEGER,
              workspace_id INTEGER
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_mission_control_sync_projects_tasks_reviews_and_knowledge_files(tmp_path: Path) -> None:
    root = tmp_path / "jarvis"
    logs = root / "state" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    _write_json(
        logs / "task_board.json",
        {
            "rows": [
                {
                    "task_id": "task_alpha",
                    "summary": "Fix replay bookkeeping bug",
                    "status": "waiting_review",
                    "priority": "normal",
                    "risk_level": "medium",
                    "execution_backend": "qwen-worker",
                    "assigned_model": "Qwen3.5-35B",
                    "updated_at": "2026-03-14T07:10:00+00:00",
                    "review_required": True,
                    "approval_required": False,
                    "related_review_ids": ["rev_alpha"],
                    "related_approval_ids": [],
                    "producer_metadata": {"source_lane": "discord"},
                    "provenance_metadata": {},
                    "evidence_metadata": {},
                },
                {
                    "task_id": "task_beta",
                    "summary": "Ship operator snapshot bridge",
                    "status": "ready_to_ship",
                    "priority": "high",
                    "risk_level": "high",
                    "execution_backend": "unassigned",
                    "assigned_model": "Qwen3.5-122B",
                    "updated_at": "2026-03-14T07:20:00+00:00",
                    "review_required": True,
                    "approval_required": True,
                    "related_review_ids": ["rev_beta"],
                    "related_approval_ids": ["apr_beta"],
                    "producer_metadata": {"source_lane": "review"},
                    "provenance_metadata": {},
                    "evidence_metadata": {},
                },
            ],
            "total": 2,
        },
    )
    _write_json(
        logs / "review_inbox.json",
        {
            "pending_reviews": [
                {
                    "review_id": "rev_alpha",
                    "task_id": "task_alpha",
                    "reviewer_role": "anton",
                    "summary": "Review required for task_alpha",
                }
            ],
            "pending_approvals": [
                {
                    "approval_id": "apr_beta",
                    "task_id": "task_beta",
                    "requested_reviewer": "operator",
                    "summary": "Approval required for task_beta",
                }
            ],
            "flowstate_waiting_promotion": [],
            "reply": "Pending reviews and approvals",
        },
    )
    _write_json(logs / "operator_snapshot.json", {"operator_focus": "Clear reviews first", "counts": {"pending_reviews": 1}})
    _write_json(logs / "state_export.json", {"counts": {"tasks": 2}, "autoresearch_summary": {"runs": 1}})
    _write_json(logs / "doctor_report.json", {"ok": True, "verdict": "healthy"})
    _write_json(logs / "validate_report.json", {"pass": 10, "fail": 0})
    _write_json(logs / "smoke_test_report.json", {"ok": True})
    _write_json(logs / "operator_handoff_pack.json", {"recommended_next_actions": ["Review task_alpha"]})

    mc_db = tmp_path / "mission-control.db"
    _init_mc_db(mc_db)
    knowledge_dir = tmp_path / "knowledge-base" / "mission-control"

    result = sync_mission_control_read_model(
        root=root,
        mission_control_db=mc_db,
        knowledge_base_dir=knowledge_dir,
        workspace_id=1,
        refresh_exports=False,
    )

    conn = sqlite3.connect(mc_db)
    try:
        tasks = conn.execute("SELECT title, status, priority, assigned_to, created_by, metadata FROM tasks ORDER BY title ASC").fetchall()
        assert len(tasks) == 2
        assert tasks[0][0] == "Fix replay bookkeeping bug"
        assert tasks[0][1] == "review"
        assert tasks[0][2] == "medium"
        assert tasks[0][3] == "qwen-worker"
        assert tasks[0][4] == "jarvis_read_model"
        metadata = json.loads(tasks[0][5])
        assert metadata["source_task_id"] == "task_alpha"
        assert metadata["source_status"] == "waiting_review"

        notifications = conn.execute("SELECT recipient, type, title FROM notifications ORDER BY recipient ASC").fetchall()
        assert notifications == [
            ("anton", "jarvis_pending_review", "Pending review for task_alpha"),
            ("operator", "jarvis_pending_approval", "Pending approval for task_beta"),
        ]

        activities = conn.execute("SELECT type, actor FROM activities ORDER BY id ASC").fetchall()
        assert any(row == ("jarvis_pending_review", "anton") for row in activities)
        assert any(row == ("jarvis_pending_approval", "operator") for row in activities)

        agents = conn.execute("SELECT name, role, status FROM agents ORDER BY name ASC").fetchall()
        assert ("anton", "reviewer", "idle") in agents
        assert ("operator", "reviewer", "idle") in agents
        assert ("qwen-worker", "runtime", "busy") in agents
    finally:
        conn.close()

    assert result.task_count == 2
    assert result.notification_count == 2
    assert (knowledge_dir / "operator_snapshot.json").exists()
    assert (knowledge_dir / "state_export.json").exists()
    assert (knowledge_dir / "README.md").exists()

