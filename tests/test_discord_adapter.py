from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.gateway.discord_command import handle_discord_command
from runtime.integrations.discord_adapter import DiscordAdapter


def test_discord_health_check() -> None:
    result = DiscordAdapter().health_check()
    assert result["integration"] == "discord"
    assert result["status"] == "stubbed"


def test_supported_low_risk_intent_accepted() -> None:
    result = DiscordAdapter().handle_command("open_discord", actor="tester", lane="tests")
    assert result["status"] == "accepted"
    assert result["intent"] == "open_discord"


def test_unsupported_intent_rejected() -> None:
    result = DiscordAdapter().handle_command("send_message", actor="tester", lane="tests")
    assert result["status"] == "rejected"
    assert result["reason"] == "unsupported_discord_intent"


def test_gateway_wrapper_stable_result() -> None:
    with TemporaryDirectory() as tmp:
        result = handle_discord_command(
            "open_channel",
            query="alpha",
            actor="tester",
            lane="tests",
            root=Path(tmp),
        )
        assert result["kind"] == "accepted"
        assert result["result"]["integration"] == "discord"


if __name__ == "__main__":
    test_discord_health_check()
    test_supported_low_risk_intent_accepted()
    test_unsupported_intent_rejected()
    test_gateway_wrapper_stable_result()
