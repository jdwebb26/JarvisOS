from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.router import classify_voice_route, maybe_route_voice_command


def test_spotify_command_routes_to_spotify() -> None:
    result = classify_voice_route("play lofi on spotify")
    assert result["matched"] is True
    assert result["subsystem"] == "spotify"
    assert result["intent"] == "play"
    assert result["query"] == "lofi"


def test_browser_like_command_routes_to_browser() -> None:
    result = classify_voice_route("open github.com")
    assert result["matched"] is True
    assert result["subsystem"] == "browser"
    assert result["intent"] == "navigate_allowlisted_page"
    assert result["target"] == "github.com"


def test_show_status_routes_to_system() -> None:
    result = classify_voice_route("show status")
    assert result["matched"] is True
    assert result["subsystem"] == "system"
    assert result["intent"] == "show_status"


def test_memory_recall_phrase_routes_to_memory() -> None:
    result = classify_voice_route("what do you remember about launch plan")
    assert result["matched"] is True
    assert result["subsystem"] == "memory"
    assert result["intent"] == "recall_memory"
    assert result["query"] == "launch plan"


def test_unknown_command_returns_no_route() -> None:
    result = classify_voice_route("sing me a song")
    assert result["matched"] is False
    assert result["reason"] == "no_voice_route_match"


def test_execute_false_returns_preview_only() -> None:
    with TemporaryDirectory() as tmp:
        result = maybe_route_voice_command(
            "pause spotify",
            actor="tester",
            lane="tests",
            root=Path(tmp),
            execute=False,
        )
        assert result["matched"] is True
        assert result["routed"] is False
        assert result["execute"] is False
        assert result["route"]["subsystem"] == "spotify"
        assert result["gateway_result"] is None


def test_execute_true_for_spotify_returns_gateway_result() -> None:
    with TemporaryDirectory() as tmp:
        result = maybe_route_voice_command(
            "play lofi on spotify",
            actor="tester",
            lane="tests",
            root=Path(tmp),
            execute=True,
        )
        assert result["matched"] is True
        assert result["execute"] is True
        assert result["route"]["subsystem"] == "spotify"
        assert result["gateway_result"] is not None
        assert result["gateway_result"]["kind"] == "accepted"
        assert result["gateway_result"]["result"]["integration"] == "spotify"


if __name__ == "__main__":
    test_spotify_command_routes_to_spotify()
    test_browser_like_command_routes_to_browser()
    test_show_status_routes_to_system()
    test_memory_recall_phrase_routes_to_memory()
    test_unknown_command_returns_no_route()
    test_execute_false_returns_preview_only()
    test_execute_true_for_spotify_returns_gateway_result()
