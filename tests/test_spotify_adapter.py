from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.gateway.spotify_command import handle_spotify_command
from runtime.integrations.spotify_adapter import SpotifyAdapter


def test_health_check_result() -> None:
    adapter = SpotifyAdapter(config={"enabled": False})
    result = adapter.health_check()
    assert result["integration"] == "spotify"
    assert result["status"] == "stubbed"
    assert result["reason"] == "spotify_api_not_connected"


def test_supported_play_intent_returns_stubbed_accepted_result() -> None:
    adapter = SpotifyAdapter()
    result = adapter.handle_command("play", query="lofi", actor="tester", lane="tests")
    assert result["status"] == "accepted"
    assert result["intent"] == "play"
    assert result["query"] == "lofi"


def test_unsupported_intent_returns_rejected_result() -> None:
    adapter = SpotifyAdapter()
    result = adapter.handle_command("delete_playlist", actor="tester", lane="tests")
    assert result["status"] == "rejected"
    assert result["reason"] == "unsupported_spotify_intent"


def test_gateway_wrapper_returns_stable_result_for_low_risk_command() -> None:
    with TemporaryDirectory() as tmp:
        result = handle_spotify_command(
            "play",
            query="focus mix",
            actor="tester",
            lane="tests",
            root=Path(tmp),
        )
        assert result["kind"] == "accepted"
        assert result["policy"]["risk_tier"] == "low"
        assert result["result"]["integration"] == "spotify"
        assert result["result"]["status"] == "accepted"


if __name__ == "__main__":
    test_health_check_result()
    test_supported_play_intent_returns_stubbed_accepted_result()
    test_unsupported_intent_returns_rejected_result()
    test_gateway_wrapper_returns_stable_result_for_low_risk_command()
