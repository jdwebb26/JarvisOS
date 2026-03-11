from pathlib import Path

from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.status import build_status
from runtime.core.task_store import create_task
from runtime.core.voice_sessions import build_voice_session_summary
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


def test_voice_session_is_durable_and_summary_visible(tmp_path: Path):
    _make_task(tmp_path, task_id="task_voice_session")
    summary = build_voice_session_summary(root=tmp_path)
    rows = list((tmp_path / "state" / "voice_sessions").glob("*.json"))

    assert rows
    assert summary["voice_session_count"] >= 1
    latest = summary["latest_voice_session"]
    assert latest["channel_type"] == "text_fallback_only"
    assert latest["caller_identity"] == "unassigned"
    assert latest["transcript_ref"] == ""
    assert latest["barge_in_supported"] is False
    assert latest["escalation_state"] == "disabled_by_policy"
    assert latest["consent_state"] == "required"


def test_voice_session_summary_surfaces_in_reporting(tmp_path: Path):
    _make_task(tmp_path, task_id="task_voice_session_reporting")
    build_voice_session_summary(root=tmp_path)

    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    state_export = build_state_export(tmp_path)
    handoff = build_operator_handoff_pack(tmp_path)["pack"]

    assert status["voice_session_summary"]["voice_session_count"] >= 1
    assert snapshot["voice_session_summary"]["latest_voice_session"]["channel_type"] == "text_fallback_only"
    assert state_export["voice_session_summary"]["latest_voice_session"]["consent_state"] == "required"
    assert handoff["voice_session_summary"]["latest_voice_session"]["voice_session_id"]
