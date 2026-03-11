from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.gateway.notify_operator import handle_operator_notification
from runtime.integrations.notification_adapter import NotificationAdapter


def test_notification_adapter_health_check() -> None:
    adapter = NotificationAdapter()
    result = adapter.health_check()
    assert result["integration"] == "notification"
    assert result["status"] == "stubbed"
    assert result["reason"] == "notification_delivery_not_connected"


def test_supported_channel_returns_stubbed_accepted_result() -> None:
    adapter = NotificationAdapter()
    result = adapter.send_notification("voice", "Hello operator", actor="tester", lane="notify")
    assert result["integration"] == "notification"
    assert result["channel"] == "voice"
    assert result["status"] == "accepted"
    assert result["reason"] == "notification_adapter_stubbed"


def test_unsupported_channel_returns_rejected_result() -> None:
    adapter = NotificationAdapter()
    result = adapter.send_notification("email", "Hello operator", actor="tester", lane="notify")
    assert result["channel"] == "email"
    assert result["status"] == "rejected"
    assert result["reason"] == "unsupported_notification_channel"


def test_gateway_wrapper_returns_stable_result_for_supported_channel() -> None:
    result = handle_operator_notification(
        "dashboard",
        "Check the latest status",
        actor="tester",
        lane="notify",
    )
    assert result["kind"] == "accepted"
    assert result["policy"]["risk_tier"] in {"low", "medium"}
    assert result["result"]["integration"] == "notification"
    assert result["result"]["channel"] == "dashboard"
    assert result["result"]["status"] == "accepted"


def test_gateway_wrapper_returns_stable_rejected_result_for_unsupported_channel() -> None:
    result = handle_operator_notification(
        "email",
        "Hello operator",
        actor="tester",
        lane="notify",
    )
    assert result["kind"] == "rejected"
    assert result["result"]["integration"] == "notification"
    assert result["result"]["channel"] == "email"
    assert result["result"]["status"] == "rejected"
    assert result["result"]["reason"] == "unsupported_notification_channel"


if __name__ == "__main__":
    test_notification_adapter_health_check()
    test_supported_channel_returns_stubbed_accepted_result()
    test_unsupported_channel_returns_rejected_result()
    test_gateway_wrapper_returns_stable_result_for_supported_channel()
    test_gateway_wrapper_returns_stable_rejected_result_for_unsupported_channel()
