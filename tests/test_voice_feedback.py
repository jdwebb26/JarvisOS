from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.feedback import play_voice_cue, speak_response, voice_feedback_dir, voice_responses_dir


def test_feedback_helper_creates_durable_feedback_record() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = play_voice_cue("wake_detected", actor="tester", lane="tests", root=root)
        assert result["status"] == "stubbed"
        assert result["mode"] == "cue_placeholder"
        assert voice_feedback_dir(root=root).joinpath(f'{result["feedback_id"]}.json').exists()


def test_speak_response_creates_durable_stub_response_record() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = speak_response("Hello from Jarvis", actor="tester", lane="tests", root=root)
        assert result["status"] == "stubbed"
        assert result["mode"] == "tts_placeholder"
        assert result["text"] == "Hello from Jarvis"
        assert voice_responses_dir(root=root).joinpath(f'{result["response_id"]}.json').exists()


if __name__ == "__main__":
    test_feedback_helper_creates_durable_feedback_record()
    test_speak_response_creates_durable_stub_response_record()
