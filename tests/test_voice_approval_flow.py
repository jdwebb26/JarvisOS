from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.spoken_approval import set_spoken_approval_code
from runtime.gateway.voice_command import handle_voice_command
from runtime.voice.approval_flow import extract_inline_approval_code


def test_extract_inline_code_from_normalized_command() -> None:
    result = extract_inline_approval_code("send external message code: pineapple")
    assert result["inline_code_present"] is True
    assert result["spoken_code"] == "pineapple"
    assert result["normalized_command_without_code"] == "send external message"


def test_confirmation_required_without_code_creates_challenge_and_prompt() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        set_spoken_approval_code("pineapple", actor="tester", lane="tests", root=root)
        result = handle_voice_command(
            "Jarvis send external message",
            voice_session_id="voicesess_approval_1",
            actor="tester",
            lane="tests",
            root=root,
        )
        assert result["kind"] == "confirmation_required"
        assert result["approval_flow"] is not None
        assert result["approval_flow"]["challenge"]["status"] == "pending"
        assert result["approval_flow"]["prompt"]["status"] == "prompted"


def test_valid_inline_code_approves_specific_pending_action() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        set_spoken_approval_code("pineapple", actor="tester", lane="tests", root=root)
        result = handle_voice_command(
            "Jarvis send external message code: pineapple",
            voice_session_id="voicesess_approval_2",
            actor="tester",
            lane="tests",
            root=root,
        )
        assert result["kind"] == "approved"
        assert result["approval_flow"]["verification"]["status"] == "approved"
        assert result["approval_flow"]["challenge"]["action_id"] == result["approval_flow"]["action_id"]


def test_invalid_inline_code_rejects_approval() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        set_spoken_approval_code("pineapple", actor="tester", lane="tests", root=root)
        result = handle_voice_command(
            "Jarvis send external message code: wrongfruit",
            voice_session_id="voicesess_approval_3",
            actor="tester",
            lane="tests",
            root=root,
        )
        assert result["kind"] == "approval_rejected"
        assert result["approval_flow"]["verification"]["status"] == "invalid_code"


def test_low_risk_command_bypasses_approval_flow() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = handle_voice_command(
            "Jarvis show status",
            voice_session_id="voicesess_approval_4",
            actor="tester",
            lane="tests",
            root=root,
        )
        assert result["kind"] == "accepted"
        assert result["approval_flow"] is None


if __name__ == "__main__":
    test_extract_inline_code_from_normalized_command()
    test_confirmation_required_without_code_creates_challenge_and_prompt()
    test_valid_inline_code_approves_specific_pending_action()
    test_invalid_inline_code_rejects_approval()
    test_low_risk_command_bypasses_approval_flow()
