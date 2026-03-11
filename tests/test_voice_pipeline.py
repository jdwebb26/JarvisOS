from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.pipeline import process_voice_transcript, voice_commands_dir


def test_rejected_command_persists_durable_record() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = process_voice_transcript(
            "open dashboard",
            voice_session_id="voicesess_1",
            actor="tester",
            lane="tests",
            root=root,
        )
        assert result["status"] == "rejected"
        assert result["voice_command"]["status"] == "rejected"
        assert voice_commands_dir(root=root).joinpath(f'{result["voice_command"]["command_id"]}.json').exists()


def test_accepted_command_persists_durable_record() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = process_voice_transcript(
            "Jarvis show status",
            voice_session_id="voicesess_2",
            actor="tester",
            lane="tests",
            task_id="task_voice_1",
            speaker_confidence=0.91,
            root=root,
        )
        assert result["status"] == "accepted"
        assert result["voice_command"]["status"] == "accepted"
        assert result["voice_command"]["normalized_command"] == "show status"
        assert voice_commands_dir(root=root).joinpath(f'{result["voice_command"]["command_id"]}.json').exists()
        event_types = [item["event_type"] for item in result["feedback"]]
        assert "wake_detected" in event_types
        assert "command_accepted" in event_types


def test_high_risk_accepted_command_surfaces_confirmation_required_cue() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = process_voice_transcript(
            "Jarvis send external message",
            voice_session_id="voicesess_3",
            actor="tester",
            lane="tests",
            task_id="task_voice_2",
            speaker_confidence=0.88,
            root=root,
        )
        assert result["status"] == "accepted"
        event_types = [item["event_type"] for item in result["feedback"]]
        assert "confirmation_required" in event_types


if __name__ == "__main__":
    test_rejected_command_persists_durable_record()
    test_accepted_command_persists_durable_record()
    test_high_risk_accepted_command_surfaces_confirmation_required_cue()
