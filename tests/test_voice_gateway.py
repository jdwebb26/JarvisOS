from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.gateway.voice_command import handle_voice_command
from runtime.integrations.voice_gateway import run_voice_gateway_cycle


def test_rejected_transcript_path() -> None:
    with TemporaryDirectory() as tmp:
        result = handle_voice_command(
            "open dashboard",
            voice_session_id="voicesess_gateway_1",
            actor="tester",
            lane="tests",
            root=Path(tmp),
        )
        assert result["kind"] == "rejected"
        assert result["routed"] is False
        session_path = Path(tmp) / "state" / "voice_sessions" / "voicesess_gateway_1.json"
        session = __import__("json").loads(session_path.read_text(encoding="utf-8"))
        assert session["transcript_ref"]
        assert session["summary_ref"]
        assert session["confirmation_state"] == "not_required"


def test_accepted_low_risk_transcript_path() -> None:
    with TemporaryDirectory() as tmp:
        result = handle_voice_command(
            "Jarvis show status",
            voice_session_id="voicesess_gateway_2",
            actor="tester",
            lane="tests",
            root=Path(tmp),
        )
        assert result["kind"] == "accepted"
        assert result["policy"]["risk_tier"] == "low"
        assert result["policy"]["requires_confirmation"] is False
        session_path = Path(tmp) / "state" / "voice_sessions" / "voicesess_gateway_2.json"
        session = __import__("json").loads(session_path.read_text(encoding="utf-8"))
        assert session["confirmation_required"] is False
        assert session["confirmation_state"] == "not_required"


def test_high_risk_transcript_surfaces_confirmation_requirement() -> None:
    with TemporaryDirectory() as tmp:
        result = handle_voice_command(
            "Jarvis send external message",
            voice_session_id="voicesess_gateway_3",
            actor="tester",
            lane="tests",
            root=Path(tmp),
        )
        assert result["kind"] == "confirmation_required"
        assert result["policy"]["risk_tier"] == "high"
        assert result["policy"]["requires_confirmation"] is True
        session_path = Path(tmp) / "state" / "voice_sessions" / "voicesess_gateway_3.json"
        session = __import__("json").loads(session_path.read_text(encoding="utf-8"))
        assert session["confirmation_required"] is True
        assert session["confirmation_state"] == "pending_confirmation"
        assert session["latest_challenge_id"] == result["approval_flow"]["challenge"]["challenge_id"]
        assert session["latest_action_id"] == result["approval_flow"]["action_id"]
        assert session["latest_verification_status"] == "pending"


def test_integration_adapter_returns_stable_wrapper_result() -> None:
    with TemporaryDirectory() as tmp:
        result = run_voice_gateway_cycle(
            "Jarvis show status",
            voice_session_id="voicesess_gateway_4",
            actor="tester",
            lane="tests",
            root=Path(tmp),
        )
        assert result["integration"] == "voice_gateway"
        assert result["status"] == "stubbed"
        assert result["gateway_result"]["kind"] == "accepted"


if __name__ == "__main__":
    test_rejected_transcript_path()
    test_accepted_low_risk_transcript_path()
    test_high_risk_transcript_surfaces_confirmation_requirement()
    test_integration_adapter_returns_stable_wrapper_result()
