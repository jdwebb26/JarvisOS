from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.gateway.tradingview_command import handle_tradingview_command
from runtime.integrations.tradingview_adapter import TradingViewAdapter


def test_tradingview_health_check() -> None:
    result = TradingViewAdapter().health_check()
    assert result["integration"] == "tradingview"
    assert result["status"] == "stubbed"


def test_set_symbol_accepted_as_bounded_stub() -> None:
    result = TradingViewAdapter().handle_command("set_symbol", query="NQ1!", actor="tester", lane="tests")
    assert result["status"] == "accepted"
    assert result["intent"] == "set_symbol"


def test_trade_like_intent_rejected() -> None:
    with TemporaryDirectory() as tmp:
        result = handle_tradingview_command(
            "buy",
            query="NQ1!",
            actor="tester",
            lane="tests",
            root=Path(tmp),
        )
        assert result["kind"] == "rejected"
        assert result["result"]["reason"] == "trade_execution_not_allowed_in_slice"


def test_gateway_wrapper_stable_result() -> None:
    with TemporaryDirectory() as tmp:
        result = handle_tradingview_command(
            "set_timeframe",
            query="5m",
            actor="tester",
            lane="tests",
            root=Path(tmp),
        )
        assert result["kind"] == "accepted"
        assert result["result"]["integration"] == "tradingview"


if __name__ == "__main__":
    test_tradingview_health_check()
    test_set_symbol_accepted_as_bounded_stub()
    test_trade_like_intent_rejected()
    test_gateway_wrapper_stable_result()
