from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.wakeword import validate_wake_phrase


def test_transcript_without_wake_phrase_is_rejected() -> None:
    result = validate_wake_phrase("open the dashboard")
    assert result["valid"] is False
    assert result["wake_phrase_detected"] is False
    assert result["reason"] == "missing_wake_phrase"


def test_wake_phrase_only_is_rejected() -> None:
    result = validate_wake_phrase("Jarvis")
    assert result["valid"] is False
    assert result["wake_phrase_detected"] is True
    assert result["reason"] == "wake_phrase_without_command"


def test_wake_phrase_plus_command_is_accepted() -> None:
    result = validate_wake_phrase("jarvis show status")
    assert result["valid"] is True
    assert result["wake_phrase_detected"] is True
    assert result["normalized_command"] == "show status"


if __name__ == "__main__":
    test_transcript_without_wake_phrase_is_rejected()
    test_wake_phrase_only_is_rejected()
    test_wake_phrase_plus_command_is_accepted()
