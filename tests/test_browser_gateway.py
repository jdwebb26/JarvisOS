from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.browser_control_allowlist import save_browser_control_allowlist
from runtime.core.models import BrowserControlAllowlistRecord, new_id, now_iso
from runtime.gateway.browser_action import handle_browser_action


def _seed_allowlist(root: Path) -> None:
    save_browser_control_allowlist(
        BrowserControlAllowlistRecord(
            browser_control_allowlist_id=new_id("browserallow"),
            created_at=now_iso(),
            updated_at=now_iso(),
            actor="tester",
            lane="tests",
            allowed_apps=[],
            allowed_sites=["example.com"],
            allowed_paths=[],
            blocked_apps=[],
            blocked_sites=[],
            blocked_paths=[],
            destructive_actions_require_confirmation=True,
            secret_entry_requires_manual_control=True,
        ),
        root=root,
    )


def test_blocked_target_url_returns_blocked_without_execution() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        result = handle_browser_action(
            task_id="task_browser_gateway_1",
            actor="tester",
            lane="tests",
            action_type="inspect_page",
            target_url="https://not-allowed.example.org",
            root=root,
        )
        assert result["kind"] == "blocked"
        assert result["executed"] is False
        assert result["policy"]["allowed"] is False


def test_high_risk_action_returns_pending_review_without_execution() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        result = handle_browser_action(
            task_id="task_browser_gateway_2",
            actor="tester",
            lane="tests",
            action_type="send_external_message",
            target_url="https://example.com/compose",
            root=root,
        )
        assert result["kind"] == "pending_review"
        assert result["executed"] is False
        assert result["request"]["status"] == "pending_review"


def test_accepted_low_risk_action_with_execute_false_returns_request_only() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        result = handle_browser_action(
            task_id="task_browser_gateway_3",
            actor="tester",
            lane="tests",
            action_type="navigate_allowlisted_page",
            target_url="https://example.com/home",
            execute=False,
            root=root,
        )
        assert result["kind"] == "accepted"
        assert result["executed"] is False
        assert result["request"]["status"] == "accepted"


def test_accepted_low_risk_action_with_execute_true_returns_stubbed_result_and_trace() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        result = handle_browser_action(
            task_id="task_browser_gateway_4",
            actor="tester",
            lane="tests",
            action_type="navigate_allowlisted_page",
            target_url="https://example.com/home",
            execute=True,
            root=root,
        )
        assert result["kind"] == "executed"
        assert result["executed"] is True
        assert result["result"]["status"] == "stubbed"
        assert result["trace"]["trace_id"]
        assert result["result"]["trace_refs"]["trace_id"] == result["trace"]["trace_id"]


if __name__ == "__main__":
    test_blocked_target_url_returns_blocked_without_execution()
    test_high_risk_action_returns_pending_review_without_execution()
    test_accepted_low_risk_action_with_execute_false_returns_request_only()
    test_accepted_low_risk_action_with_execute_true_returns_stubbed_result_and_trace()
