from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.browser.protocol import complete_browser_action, request_browser_action
from runtime.core.browser_control_allowlist import save_browser_control_allowlist
from runtime.core.models import BrowserControlAllowlistRecord, new_id, now_iso


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


def test_protocol_request_creation() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        payload = request_browser_action(
            task_id="task_browser_1",
            actor="tester",
            lane="tests",
            action_type="navigate_allowlisted_page",
            target_url="https://example.com/home",
            root=root,
        )
        assert payload["request"]["task_id"] == "task_browser_1"
        assert payload["request"]["status"] == "accepted"
        assert payload["policy"]["allowed"] is True


def test_protocol_completion_creation() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        request_payload = request_browser_action(
            task_id="task_browser_2",
            actor="tester",
            lane="tests",
            action_type="navigate_allowlisted_page",
            target_url="https://example.com/home",
            root=root,
        )
        completion = complete_browser_action(
            request_id=request_payload["request"]["request_id"],
            actor="tester",
            lane="tests",
            status="completed",
            outcome_summary="navigation recorded",
            snapshot_refs={"before": "snap_before"},
            trace_refs={"trace_id": "trace_browser"},
            root=root,
        )
        assert completion["result"]["status"] == "completed"
        assert completion["result"]["outcome_summary"] == "navigation recorded"
        assert completion["request"]["status"] == "completed"


if __name__ == "__main__":
    test_protocol_request_creation()
    test_protocol_completion_creation()
