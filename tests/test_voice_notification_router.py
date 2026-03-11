from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.gateway.voice_command import handle_voice_command
from runtime.voice.router import classify_voice_route, maybe_route_voice_command


def test_classify_notify_dashboard_routes_to_notification() -> None:
    route = classify_voice_route("notify dashboard check the latest status")
    assert route["matched"] is True
    assert route["subsystem"] == "notification"
    assert route["intent"] == "notify_operator"
    assert route["query"] == "check the latest status"
    assert route["target"] == "dashboard"


def test_classify_notify_voice_routes_to_notification() -> None:
    route = classify_voice_route("notify voice approval required")
    assert route["matched"] is True
    assert route["subsystem"] == "notification"
    assert route["intent"] == "notify_operator"
    assert route["query"] == "approval required"
    assert route["target"] == "voice"


def test_preview_only_behavior_when_execute_false() -> None:
    result = maybe_route_voice_command(
        "notify mobile task finished",
        actor="tester",
        lane="voice",
        task_id="task_notify_preview",
        execute=False,
    )
    assert result["matched"] is True
    assert result["routed"] is False
    assert result["route_reason"] == "route_preview_only"
    assert result["gateway_result"] is None


def test_execute_true_returns_notification_gateway_result() -> None:
    result = maybe_route_voice_command(
        "notify dashboard build complete",
        actor="tester",
        lane="voice",
        task_id="task_notify_execute",
        execute=True,
    )
    assert result["matched"] is True
    assert result["routed"] is True
    assert result["route_reason"] == "notification_gateway_invoked"
    assert result["gateway_result"]["kind"] == "accepted"
    assert result["gateway_result"]["result"]["integration"] == "notification"
    assert result["gateway_result"]["result"]["channel"] == "dashboard"


def test_unsupported_phrase_stays_no_route() -> None:
    result = maybe_route_voice_command(
        "tell everyone hello",
        actor="tester",
        lane="voice",
        task_id="task_notify_unknown",
        execute=False,
    )
    assert result["matched"] is False
    assert result["route"]["reason"] == "no_voice_route_match"


def test_voice_gateway_notification_route_preview_stays_explicit() -> None:
    preview = handle_voice_command(
        "Jarvis notify dashboard build finished",
        voice_session_id="voice_notify_preview",
        actor="tester",
        lane="voice",
        route=True,
    )
    assert preview["kind"] == "accepted"
    assert preview["route_preview"]["matched"] is True
    assert preview["route_preview"]["route_reason"] == "route_preview_only"
    assert preview["route_result"] is None
    assert preview["routed"] is False


if __name__ == "__main__":
    test_classify_notify_dashboard_routes_to_notification()
    test_classify_notify_voice_routes_to_notification()
    test_preview_only_behavior_when_execute_false()
    test_execute_true_returns_notification_gateway_result()
    test_unsupported_phrase_stays_no_route()
    test_voice_gateway_notification_route_preview_stays_explicit()
