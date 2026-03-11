from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.router import classify_voice_route, maybe_route_voice_command


def test_route_open_discord_to_desktop_open_app() -> None:
    result = classify_voice_route("open discord")
    assert result["matched"] is True
    assert result["subsystem"] == "desktop"
    assert result["intent"] == "open_app"
    assert result["target"] == "discord"


def test_route_focus_tradingview_to_desktop_focus_window() -> None:
    result = classify_voice_route("focus tradingview")
    assert result["matched"] is True
    assert result["subsystem"] == "desktop"
    assert result["intent"] == "focus_window"
    assert result["target"] == "tradingview"


def test_route_open_downloads_to_desktop_open_path() -> None:
    result = classify_voice_route("open downloads")
    assert result["matched"] is True
    assert result["subsystem"] == "desktop"
    assert result["intent"] == "open_path"
    assert result["target"] == "downloads"


def test_execute_false_returns_preview_only() -> None:
    with TemporaryDirectory() as tmp:
        result = maybe_route_voice_command(
            "open spotify",
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


def test_execute_true_returns_wrapped_desktop_gateway_result() -> None:
    with TemporaryDirectory() as tmp:
        result = maybe_route_voice_command(
            "open discord",
            actor="tester",
            lane="tests",
            task_id="task_voice_desktop_1",
            root=Path(tmp),
            execute=True,
        )
        assert result["matched"] is True
        assert result["execute"] is True
        assert result["route"]["subsystem"] == "desktop"
        assert result["gateway_result"] is not None
        assert result["gateway_result"]["kind"] == "executed"
        assert result["gateway_result"]["result"]["status"] == "stubbed"


def test_unknown_command_remains_no_route() -> None:
    result = classify_voice_route("close everything now")
    assert result["matched"] is False
    assert result["reason"] == "no_voice_route_match"


if __name__ == "__main__":
    test_route_open_discord_to_desktop_open_app()
    test_route_focus_tradingview_to_desktop_focus_window()
    test_route_open_downloads_to_desktop_open_path()
    test_execute_false_returns_preview_only()
    test_execute_true_returns_wrapped_desktop_gateway_result()
    test_unknown_command_remains_no_route()
