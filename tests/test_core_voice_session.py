from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import TaskRecord, TaskStatus, now_iso
from runtime.core.voice_sessions import build_voice_session_summary, load_voice_session
from runtime.core.status import build_status
from runtime.core.task_store import create_task
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.gateway.voice_command import handle_voice_command
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
    assert latest["summary_ref"] == ""
    assert latest["barge_in_supported"] is False
    assert latest["escalation_state"] == "disabled_by_policy"
    assert latest["consent_state"] == "required"
    assert latest["confirmation_state"] == "not_required"


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


def test_voice_session_persists_transcript_summary_and_confirmation_linkage(tmp_path: Path):
    result = handle_voice_command(
        "Jarvis send external message",
        voice_session_id="voicesess_session_completion",
        actor="tester",
        lane="tests",
        root=tmp_path,
    )

    stored = load_voice_session("voicesess_session_completion", root=tmp_path)
    summary = build_voice_session_summary(root=tmp_path)
    status = build_status(tmp_path)
    snapshot = build_operator_snapshot(tmp_path)
    state_export = build_state_export(tmp_path)

    assert result["kind"] == "confirmation_required"
    assert stored is not None
    assert stored.transcript_ref
    assert stored.summary_ref
    assert stored.confirmation_required is True
    assert stored.confirmation_state == "pending_confirmation"
    assert stored.latest_challenge_id == result["approval_flow"]["challenge"]["challenge_id"]
    assert stored.latest_action_id == result["approval_flow"]["action_id"]
    assert stored.latest_verification_status == "pending"

    assert summary["transcript_present_count"] >= 1
    assert summary["summary_present_count"] >= 1
    assert summary["confirmation_required_count"] >= 1
    assert summary["challenge_linked_session_count"] >= 1
    assert status["voice_session_summary"]["latest_voice_session"]["confirmation_state"] == "pending_confirmation"
    assert snapshot["voice_session_summary"]["latest_voice_session"]["latest_challenge_id"]
    assert state_export["voice_session_summary"]["confirmation_state_counts"]["pending_confirmation"] >= 1
