from pathlib import Path

from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.task_store import create_task
from runtime.core.status import build_status
from runtime.dashboard.heartbeat_report import build_heartbeat_report
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from scripts.operator_handoff_pack import build_operator_handoff_pack


def _make_task(root: Path, *, task_id: str, status: str = TaskStatus.RUNNING.value) -> TaskRecord:
    return create_task(
        TaskRecord(
            task_id=task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            source_lane="tests",
            source_channel="tests",
            source_message_id=f"{task_id}_msg",
            source_user="tester",
            trigger_type="explicit_task_colon",
            raw_request=f"task: {task_id}",
            normalized_request=task_id,
            task_type="general",
            status=status,
            execution_backend="qwen_executor",
        ),
        root=root,
    )


def test_heartbeat_report_persists_common_subsystem_shape(tmp_path: Path):
    _make_task(tmp_path, task_id="task_heartbeat")

    heartbeat = build_heartbeat_report(tmp_path)
    heartbeat_reports = list((tmp_path / "state" / "heartbeat_reports").glob("*.json"))

    assert heartbeat["heartbeat_summary"]["latest_subsystem_heartbeat_count"] >= 8
    assert heartbeat_reports
    subsystem_names = {row["subsystem_name"] for row in heartbeat["subsystem_heartbeats"]}
    assert "local_core" in subsystem_names
    assert "Hermes" in subsystem_names
    assert "autoresearch" in subsystem_names
    assert "Ralph" in subsystem_names
    assert "browser_automation" in subsystem_names
    assert "voice" in subsystem_names
    assert "reviewer_lane" in subsystem_names
    assert "auditor_lane" in subsystem_names
    for row in heartbeat["subsystem_heartbeats"]:
        assert set(row) >= {
            "heartbeat_report_id",
            "subsystem_name",
            "status",
            "last_active_at",
            "current_task_count",
            "error_summary",
            "budget_remaining",
        }


def test_heartbeat_summary_surfaces_in_reporting(tmp_path: Path):
    _make_task(tmp_path, task_id="task_heartbeat_reporting")
    build_heartbeat_report(tmp_path)

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    state_export = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]

    assert status["heartbeat_summary"]["latest_subsystem_heartbeat_count"] >= 8
    assert snapshot["heartbeat_summary"]["overall_heartbeat_status"] in {"healthy", "degraded", "stopped", "unreachable"}
    assert state_export["heartbeat_summary"]["heartbeat_report_count"] >= 8
    assert handoff["heartbeat_summary"]["latest_heartbeat_report"]["subsystem_name"]
