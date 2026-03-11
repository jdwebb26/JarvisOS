from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import DesktopActionRequestRecord, now_iso
from runtime.desktop.executor import execute_desktop_action
from runtime.gateway.desktop_action import handle_desktop_action


def test_stub_executor_returns_structured_result() -> None:
    with TemporaryDirectory() as tmp:
        request = DesktopActionRequestRecord(
            request_id="dreq_test_1",
            task_id="task_test_1",
            created_at=now_iso(),
            updated_at=now_iso(),
            actor="tester",
            lane="tests",
            action_type="open_app",
            target_app="Spotify",
        )
        result = execute_desktop_action(request, root=Path(tmp))
        assert result.status == "stubbed"
        assert result.error == "desktop_executor_not_connected"
        assert "Desktop action stubbed" in result.outcome_summary


def test_gateway_accepted_path() -> None:
    with TemporaryDirectory() as tmp:
        result = handle_desktop_action(
            task_id="task_test_2",
            actor="tester",
            lane="tests",
            action_type="open_app",
            target_app="Spotify",
            execute=False,
            root=Path(tmp),
        )
        assert result["kind"] == "accepted"
        assert result["request"]["risk_tier"] == "low"
        assert result["executed"] is False


def test_gateway_pending_review_path() -> None:
    with TemporaryDirectory() as tmp:
        result = handle_desktop_action(
            task_id="task_test_3",
            actor="tester",
            lane="tests",
            action_type="bounded_shell",
            action_params={"command": "ls"},
            execute=True,
            root=Path(tmp),
        )
        assert result["kind"] == "pending_review"
        assert result["request"]["review_required"] is True
        assert result["executed"] is False


if __name__ == "__main__":
    test_stub_executor_returns_structured_result()
    test_gateway_accepted_path()
    test_gateway_pending_review_path()
