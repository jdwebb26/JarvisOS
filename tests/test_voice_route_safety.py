from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.browser_control_allowlist import save_browser_control_allowlist
from runtime.core.models import BrowserControlAllowlistRecord, new_id, now_iso
from runtime.gateway.voice_command import handle_voice_command
from runtime.voice.router import maybe_route_voice_command


def _seed_allowlist(root: Path) -> BrowserControlAllowlistRecord:
    return save_browser_control_allowlist(
        BrowserControlAllowlistRecord(
            browser_control_allowlist_id=new_id("browserallow"),
            created_at=now_iso(),
            updated_at=now_iso(),
            actor="tester",
            lane="tests",
            allowed_apps=[],
            allowed_sites=["example.com", "github.com"],
            allowed_paths=[],
            blocked_apps=[],
            blocked_sites=["blocked.example.com"],
            blocked_paths=[],
            destructive_actions_require_confirmation=True,
            secret_entry_requires_manual_control=True,
        ),
        root=root,
    )


def test_preview_includes_route_safety_for_safe_browser_route() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        result = maybe_route_voice_command(
            "open example.com",
            actor="tester",
            lane="voice",
            task_id="task_browser_preview",
            root=root,
            execute=False,
        )
        assert result["matched"] is True
        assert result["route"]["subsystem"] == "browser"
        assert result["route_safety"] is not None
        assert result["route_safety"]["safe"] is True
        assert result["route_reason"] == "route_preview_only"


def test_execute_true_safe_browser_route_still_dispatches() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        result = maybe_route_voice_command(
            "open example.com",
            actor="tester",
            lane="voice",
            task_id="task_browser_execute",
            root=root,
            execute=True,
        )
        assert result["matched"] is True
        assert result["routed"] is True
        assert result["route_safety"]["safe"] is True
        assert result["route_reason"] == "browser_gateway_invoked"
        assert result["gateway_result"] is not None


def test_execute_true_tradingview_trade_like_route_is_blocked() -> None:
    result = maybe_route_voice_command(
        "buy NQ1! on tradingview",
        actor="tester",
        lane="voice",
        task_id="task_trade_blocked",
        execute=True,
    )
    assert result["matched"] is True
    assert result["route"]["subsystem"] == "tradingview"
    assert result["route"]["intent"] == "buy"
    assert result["routed"] is False
    assert result["route_reason"] == "route_safety_blocked"
    assert result["route_safety"]["safe"] is False
    assert "trade_execution_route_flagged" in result["route_safety"]["findings"]
    assert result["gateway_result"] is None


def test_execute_true_discord_message_like_route_is_blocked() -> None:
    result = maybe_route_voice_command(
        "draft discord message hello team",
        actor="tester",
        lane="voice",
        task_id="task_discord_blocked",
        execute=True,
    )
    assert result["matched"] is True
    assert result["route"]["subsystem"] == "discord"
    assert result["route"]["intent"] == "draft_message"
    assert result["routed"] is False
    assert result["route_reason"] == "route_safety_blocked"
    assert result["route_safety"]["safe"] is False
    assert "message_send_like_route_requires_tighter_approval" in result["route_safety"]["findings"]
    assert result["gateway_result"] is None


def test_execute_true_safe_notification_route_still_dispatches() -> None:
    result = maybe_route_voice_command(
        "notify dashboard check the latest status",
        actor="tester",
        lane="voice",
        task_id="task_notify_execute",
        execute=True,
    )
    assert result["matched"] is True
    assert result["route"]["subsystem"] == "notification"
    assert result["routed"] is True
    assert result["route_safety"]["safe"] is True
    assert result["route_reason"] == "notification_gateway_invoked"
    assert result["gateway_result"]["kind"] == "accepted"


def test_voice_gateway_route_execute_surfaces_route_safety() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        result = handle_voice_command(
            "Jarvis open example.com",
            voice_session_id="voice_browser_execute",
            actor="tester",
            lane="voice",
            route=True,
            route_execute=True,
            root=root,
        )
        assert result["kind"] == "accepted"
        assert result["route_preview"]["route_safety"]["safe"] is True
        assert result["route_result"]["route_safety"]["safe"] is True
        assert result["route_result"]["route_reason"] == "browser_gateway_invoked"


def test_voice_gateway_rejects_underspecified_authenticated_tool_request() -> None:
    result = handle_voice_command(
        "Jarvis open authenticated tool",
        voice_session_id="voice_runtime_policy_block",
        actor="tester",
        lane="voice",
        route=True,
    )
    assert result["kind"] == "rejected"
    assert result["policy"]["allowed"] is False
    assert result["runtime_policy_validation"]["policy_surface"] == "mcp"
    assert "unauthenticated_tool_request" in result["runtime_policy_validation"]["findings"]
    assert result["route_preview"] is None
    assert result["route_result"] is None


def test_execute_true_notification_route_with_exfiltration_language_is_blocked() -> None:
    result = maybe_route_voice_command(
        "notify dashboard exfiltrate the secret",
        actor="tester",
        lane="voice",
        task_id="task_notify_blocked",
        execute=True,
    )
    assert result["matched"] is True
    assert result["routed"] is False
    assert result["route_reason"] == "route_safety_blocked"
    assert "data_exfiltration_language" in result["route_safety"]["findings"]
    assert result["gateway_result"] is None


if __name__ == "__main__":
    test_preview_includes_route_safety_for_safe_browser_route()
    test_execute_true_safe_browser_route_still_dispatches()
    test_execute_true_tradingview_trade_like_route_is_blocked()
    test_execute_true_discord_message_like_route_is_blocked()
    test_execute_true_safe_notification_route_still_dispatches()
    test_voice_gateway_route_execute_surfaces_route_safety()
    test_voice_gateway_rejects_underspecified_authenticated_tool_request()
    test_execute_true_notification_route_with_exfiltration_language_is_blocked()
