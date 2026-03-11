from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.spotify_router import maybe_route_voice_to_spotify, parse_spotify_voice_command


def test_parse_play_lofi_on_spotify() -> None:
    result = parse_spotify_voice_command("play lofi on spotify")
    assert result["matched"] is True
    assert result["intent"] == "play"
    assert result["query"] == "lofi"


def test_parse_pause_spotify() -> None:
    result = parse_spotify_voice_command("pause spotify")
    assert result["matched"] is True
    assert result["intent"] == "pause"


def test_reject_non_spotify_command() -> None:
    result = parse_spotify_voice_command("open dashboard")
    assert result["matched"] is False
    assert result["reason"] == "no_spotify_match"


def test_execute_false_returns_route_preview_only() -> None:
    with TemporaryDirectory() as tmp:
        result = maybe_route_voice_to_spotify(
            "play lofi on spotify",
            actor="tester",
            lane="tests",
            root=Path(tmp),
            execute=False,
        )
        assert result["matched"] is True
        assert result["routed"] is False
        assert result["gateway_result"] is None


def test_execute_true_returns_wrapped_spotify_gateway_result() -> None:
    with TemporaryDirectory() as tmp:
        result = maybe_route_voice_to_spotify(
            "pause spotify",
            actor="tester",
            lane="tests",
            root=Path(tmp),
            execute=True,
        )
        assert result["matched"] is True
        assert result["routed"] is True
        assert result["gateway_result"]["result"]["integration"] == "spotify"
        assert result["gateway_result"]["result"]["status"] == "accepted"


if __name__ == "__main__":
    test_parse_play_lofi_on_spotify()
    test_parse_pause_spotify()
    test_reject_non_spotify_command()
    test_execute_false_returns_route_preview_only()
    test_execute_true_returns_wrapped_spotify_gateway_result()
