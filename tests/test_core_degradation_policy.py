from pathlib import Path

from runtime.core.degradation_policy import (
    list_degradation_events,
    load_degradation_policy_for_subsystem,
)
from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.status import build_status
from runtime.core.task_store import create_task, load_task
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.integrations.hermes_adapter import HERMES_BACKEND_ID, execute_hermes_task
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
            status=status,
            execution_backend="qwen_executor",
        ),
        root=root,
    )


def test_hermes_timeout_applies_degradation_policy_and_fails_task(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_degradation_timeout")

    result = execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: (_ for _ in ()).throw(TimeoutError("Hermes request exceeded timeout budget.")),
    )

    stored_task = load_task(task.task_id, root=tmp_path)
    hermes_policy = load_degradation_policy_for_subsystem(HERMES_BACKEND_ID, root=tmp_path)
    degradation_events = list_degradation_events(root=tmp_path)
    task_events = (tmp_path / "state" / "events").glob("*.json")
    event_payloads = [path.read_text(encoding="utf-8") for path in task_events]

    assert stored_task is not None
    assert stored_task.status == TaskStatus.FAILED.value
    assert result["result"]["status"] == "timeout"
    assert hermes_policy is not None
    assert hermes_policy.fallback_action == "no_local_fallback"
    assert hermes_policy.requires_operator_notification is True
    assert hermes_policy.retry_policy["strategy"] == "manual_retry"
    assert degradation_events[-1].subsystem == HERMES_BACKEND_ID
    assert degradation_events[-1].failure_category == "timeout"
    assert degradation_events[-1].fallback_action == "no_local_fallback"
    assert degradation_events[-1].requires_operator_notification is True
    assert degradation_events[-1].retry_policy["strategy"] == "manual_retry"
    assert stored_task.backend_metadata["degradation"]["degradation_event_id"] == degradation_events[-1].degradation_event_id
    assert any('"event_type": "hermes_degradation_applied"' in payload for payload in event_payloads)


def test_degradation_summary_surfaces_in_core_reporting(tmp_path: Path):
    task = _make_task(tmp_path, task_id="task_degradation_reporting")

    execute_hermes_task(
        task_id=task.task_id,
        actor="tester",
        lane="hermes",
        root=tmp_path,
        transport=lambda _request: (_ for _ in ()).throw(TimeoutError("Hermes request exceeded timeout budget.")),
    )

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    state_export = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]

    assert status["degradation_summary"]["degradation_policy_count"] >= 3
    assert status["degradation_summary"]["degradation_event_count"] == 1
    assert status["degradation_summary"]["latest_degradation_event"]["subsystem"] == HERMES_BACKEND_ID
    assert snapshot["degradation_summary"]["latest_degradation_event"]["failure_category"] == "timeout"
    assert state_export["degradation_summary"]["degradation_event_status_counts"]["applied"] == 1
    assert handoff["degradation_summary"]["latest_degradation_event"]["fallback_action"] == "no_local_fallback"
