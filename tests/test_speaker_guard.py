from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.speaker_guard import SpeakerGuard


def test_speaker_guard_returns_stubbed_structured_score() -> None:
    guard = SpeakerGuard(config={"stub_confidence": 0.62})
    score = guard.score_speaker({"frames": []})
    assert score["status"] == "stubbed"
    assert score["mode"] == "speaker_guard_placeholder"
    assert score["confidence"] == 0.62
    assert score["reason"] == "speaker_guard_not_connected"


def test_confidence_threshold_logic_varies_by_risk_tier() -> None:
    guard = SpeakerGuard(config={"low_risk_threshold": 0.3, "medium_risk_threshold": 0.7})
    score = {"confidence": 0.6, "speaker_label": "unknown_operator"}
    assert guard.confidence_meets_threshold(score, "low") is True
    assert guard.confidence_meets_threshold(score, "medium") is False
    assert guard.confidence_meets_threshold(score, "high") is False


if __name__ == "__main__":
    test_speaker_guard_returns_stubbed_structured_score()
    test_confidence_threshold_logic_varies_by_risk_tier()
