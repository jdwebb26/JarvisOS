from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.browser_control_allowlist import save_browser_control_allowlist
from runtime.core.models import BrowserControlAllowlistRecord, new_id, now_iso
from runtime.gateway.voice_command import handle_voice_command
from runtime.voice.router import classify_voice_route, maybe_route_voice_command


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


def test_classify_open_github_as_browser_navigate_route() -> None:
    route = classify_voice_route("open github.com")
    assert route["matched"] is True
    assert route["subsystem"] == "browser"
    assert route["intent"] == "navigate_allowlisted_page"
    assert route["target"] == "github.com"


def test_classify_inspect_github_as_browser_inspect_route() -> None:
    route = classify_voice_route("inspect github.com")
    assert route["matched"] is True
    assert route["subsystem"] == "browser"
    assert route["intent"] == "inspect_page"
    assert route["target"] == "github.com"


def test_unknown_non_site_phrase_stays_no_route() -> None:
    route = classify_voice_route("open project dashboard")
    assert route["matched"] is False
    assert route["reason"] == "no_voice_route_match"


def test_execute_false_returns_preview_only() -> None:
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
        assert result["routed"] is False
        assert result["route_reason"] == "route_preview_only"
        assert result["gateway_result"] is None


def test_execute_true_returns_wrapped_browser_gateway_result() -> None:
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
        assert result["route_reason"] == "browser_gateway_invoked"
        assert result["gateway_result"]["kind"] in {"accepted", "executed"}


def test_blocked_non_allowlisted_site_returns_blocked_gateway_result() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        result = maybe_route_voice_command(
            "open blocked.example.com",
            actor="tester",
            lane="voice",
            task_id="task_browser_blocked",
            root=root,
            execute=True,
        )
        assert result["matched"] is True
        assert result["routed"] is True
        assert result["gateway_result"]["kind"] == "blocked"


def test_voice_gateway_route_execute_is_explicit_and_preview_first() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        preview = handle_voice_command(
            "Jarvis open example.com",
            voice_session_id="voice_preview",
            actor="tester",
            lane="voice",
            route=True,
            root=root,
        )
        assert preview["kind"] == "accepted"
        assert preview["route_preview"]["matched"] is True
        assert preview["route_result"] is None
        assert preview["routed"] is False

        executed = handle_voice_command(
            "Jarvis open example.com",
            voice_session_id="voice_execute",
            actor="tester",
            lane="voice",
            route=True,
            route_execute=True,
            root=root,
        )
        assert executed["kind"] == "accepted"
        assert executed["route_preview"]["matched"] is True
        assert executed["route_result"]["route_reason"] == "browser_gateway_invoked"
        assert executed["routed"] is True


if __name__ == "__main__":
    test_classify_open_github_as_browser_navigate_route()
    test_classify_inspect_github_as_browser_inspect_route()
    test_unknown_non_site_phrase_stays_no_route()
    test_execute_false_returns_preview_only()
    test_execute_true_returns_wrapped_browser_gateway_result()
    test_blocked_non_allowlisted_site_returns_blocked_gateway_result()
    test_voice_gateway_route_execute_is_explicit_and_preview_first()
