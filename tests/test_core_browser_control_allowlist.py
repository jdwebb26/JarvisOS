from pathlib import Path

from runtime.core.browser_control_allowlist import build_browser_control_allowlist_summary
from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.status import build_status
from runtime.core.task_store import create_task
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from scripts.operator_handoff_pack import build_operator_handoff_pack


def _make_task(root: Path, *, task_id: str) -> TaskRecord:
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
            status=TaskStatus.RUNNING.value,
            execution_backend="qwen_executor",
        ),
        root=root,
    )


def test_browser_control_allowlist_is_durable_and_summary_visible(tmp_path: Path):
    _make_task(tmp_path, task_id="task_browser_allowlist")
    summary = build_browser_control_allowlist_summary(root=tmp_path)
    rows = list((tmp_path / "state" / "browser_control_allowlists").glob("*.json"))

    assert rows
    assert summary["browser_control_allowlist_count"] >= 1
    latest = summary["latest_browser_control_allowlist"]
    assert latest["destructive_actions_require_confirmation"] is True
    assert latest["secret_entry_requires_manual_control"] is True
    assert latest["allowed_apps"] == []
    assert latest["blocked_sites"] == []


def test_browser_control_allowlist_summary_surfaces_in_reporting(tmp_path: Path):
    _make_task(tmp_path, task_id="task_browser_allowlist_reporting")
    build_browser_control_allowlist_summary(root=tmp_path)

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    state_export = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]

    assert status["browser_control_allowlist_summary"]["browser_control_allowlist_count"] >= 1
    assert snapshot["browser_control_allowlist_summary"]["destructive_actions_require_confirmation"] is True
    assert state_export["browser_control_allowlist_summary"]["secret_entry_requires_manual_control"] is True
    assert handoff["browser_control_allowlist_summary"]["latest_browser_control_allowlist"]["browser_control_allowlist_id"]
