from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.policy import evaluate_voice_command_policy


def test_low_risk_voice_command_policy_result() -> None:
    with TemporaryDirectory() as tmp:
        result = evaluate_voice_command_policy("show status", root=Path(tmp))
        assert result["risk_tier"] == "low"
        assert result["requires_confirmation"] is False
        assert result["allowed"] is True


def test_high_risk_voice_command_requires_confirmation() -> None:
    with TemporaryDirectory() as tmp:
        result = evaluate_voice_command_policy("send external message", root=Path(tmp))
        assert result["risk_tier"] == "high"
        assert result["requires_confirmation"] is True
        assert result["confirmation_reason"] == "high_risk_requires_text_confirmation"


if __name__ == "__main__":
    test_low_risk_voice_command_policy_result()
    test_high_risk_voice_command_requires_confirmation()
