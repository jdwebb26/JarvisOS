from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.router import classify_voice_route, maybe_route_voice_command


def test_open_discord_routes_to_discord() -> None:
    result = classify_voice_route("open discord")
    assert result["matched"] is True
    assert result["subsystem"] == "discord"
    assert result["intent"] == "open_discord"


def test_open_discord_channel_alpha_routes_to_open_channel() -> None:
    result = classify_voice_route("open discord channel alpha")
    assert result["matched"] is True
    assert result["subsystem"] == "discord"
    assert result["intent"] == "open_channel"
    assert result["query"] == "alpha"


def test_open_tradingview_routes_to_tradingview() -> None:
    result = classify_voice_route("open tradingview")
    assert result["matched"] is True
    assert result["subsystem"] == "tradingview"
    assert result["intent"] == "open_tradingview"


def test_set_tradingview_symbol_routes_to_set_symbol() -> None:
    result = classify_voice_route("set tradingview symbol to NQ1!")
    assert result["matched"] is True
    assert result["subsystem"] == "tradingview"
    assert result["intent"] == "set_symbol"
    assert result["query"] == "NQ1!"


def test_execute_false_returns_preview_only() -> None:
    with TemporaryDirectory() as tmp:
        result = maybe_route_voice_command(
            "open discord",
            actor="tester",
            lane="tests",
            root=Path(tmp),
            execute=False,
        )
        assert result["matched"] is True
        assert result["routed"] is False
        assert result["gateway_result"] is None


def test_execute_true_returns_discord_gateway_result() -> None:
    with TemporaryDirectory() as tmp:
        result = maybe_route_voice_command(
            "open discord",
            actor="tester",
            lane="tests",
            root=Path(tmp),
            execute=True,
        )
        assert result["matched"] is True
        assert result["route"]["subsystem"] == "discord"
        assert result["gateway_result"] is not None
        assert result["gateway_result"]["result"]["integration"] == "discord"


def test_execute_true_returns_tradingview_gateway_result() -> None:
    with TemporaryDirectory() as tmp:
        result = maybe_route_voice_command(
            "set tradingview symbol to NQ1!",
            actor="tester",
            lane="tests",
            root=Path(tmp),
            execute=True,
        )
        assert result["matched"] is True
        assert result["route"]["subsystem"] == "tradingview"
        assert result["gateway_result"] is not None
        assert result["gateway_result"]["result"]["integration"] == "tradingview"


if __name__ == "__main__":
    test_open_discord_routes_to_discord()
    test_open_discord_channel_alpha_routes_to_open_channel()
    test_open_tradingview_routes_to_tradingview()
    test_set_tradingview_symbol_routes_to_set_symbol()
    test_execute_false_returns_preview_only()
    test_execute_true_returns_discord_gateway_result()
    test_execute_true_returns_tradingview_gateway_result()
