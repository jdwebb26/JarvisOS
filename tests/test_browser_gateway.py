from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.browser_control_allowlist import save_browser_control_allowlist
from runtime.core.status import summarize_status
from runtime.core.models import BrowserControlAllowlistRecord, new_id, now_iso
from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.browser.protocol import complete_browser_action
from runtime.gateway.browser_action import cancel_browser_action, handle_browser_action


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
        assert result["request"]["confirmation_required"] is True
        assert result["request"]["confirmation_state"] == "pending_confirmation"


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
        assert result["result"]["trace_refs"]["run_trace_id"] == result["run_trace"]["trace_id"]
        assert result["result"]["evidence_refs"]["after_screenshot_ref"] == result["evidence_snapshot"]["snapshot_id"]


def test_browser_reporting_surfaces_confirmation_and_evidence_summary_consistently() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        handle_browser_action(
            task_id="task_browser_gateway_5",
            actor="tester",
            lane="tests",
            action_type="send_external_message",
            target_url="https://example.com/compose",
            root=root,
        )
        handle_browser_action(
            task_id="task_browser_gateway_6",
            actor="tester",
            lane="tests",
            action_type="navigate_allowlisted_page",
            target_url="https://example.com/home",
            execute=True,
            root=root,
        )

        status = summarize_status(root=root)
        state_export = build_state_export(root)
        snapshot = build_operator_snapshot(root)

        status_summary = status["browser_action_summary"]
        assert status_summary["confirmation_required_count"] >= 1
        assert status_summary["pending_confirmation_count"] >= 1
        assert status_summary["evidence_present_count"] >= 1
        assert status_summary["shared_run_trace_link_count"] >= 1
        assert state_export["browser_action_summary"] == status_summary
        assert snapshot["browser_action_summary"] == status_summary


def test_browser_cancelled_request_stays_non_executable_and_is_reported() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        accepted = handle_browser_action(
            task_id="task_browser_gateway_7",
            actor="tester",
            lane="tests",
            action_type="navigate_allowlisted_page",
            target_url="https://example.com/home",
            execute=False,
            root=root,
        )
        cancellation = cancel_browser_action(
            request_id=accepted["request"]["request_id"],
            actor="tester",
            lane="tests",
            reason="operator_interrupt",
            root=root,
        )

        assert cancellation["kind"] == "cancelled"
        assert cancellation["executed"] is False
        assert cancellation["request"]["status"] == "cancelled"
        assert cancellation["request"]["cancelled_by"] == "tester"
        assert cancellation["request"]["cancel_reason"] == "operator_interrupt"
        assert cancellation["result"]["status"] == "cancelled"
        assert cancellation["result"]["cancelled_by"] == "tester"
        assert cancellation["result"]["cancel_reason"] == "operator_interrupt"

        try:
            complete_browser_action(
                request_id=accepted["request"]["request_id"],
                actor="tester",
                lane="tests",
                status="stubbed",
                outcome_summary="should not execute",
                root=root,
            )
        except ValueError as exc:
            assert "cancelled" in str(exc)
        else:
            raise AssertionError("Cancelled browser request unexpectedly completed.")

        status = summarize_status(root=root)
        state_export = build_state_export(root)
        snapshot = build_operator_snapshot(root)
        status_summary = status["browser_action_summary"]

        assert status_summary["cancelled_request_count"] == 1
        assert status_summary["cancelled_result_count"] == 1
        assert status_summary["request_status_counts"]["cancelled"] == 1
        assert status_summary["result_status_counts"]["cancelled"] == 1
        assert state_export["browser_action_summary"] == status_summary
        assert snapshot["browser_action_summary"] == status_summary


if __name__ == "__main__":
    test_blocked_target_url_returns_blocked_without_execution()
    test_high_risk_action_returns_pending_review_without_execution()
    test_accepted_low_risk_action_with_execute_false_returns_request_only()
    test_accepted_low_risk_action_with_execute_true_returns_stubbed_result_and_trace()
    test_browser_reporting_surfaces_confirmation_and_evidence_summary_consistently()
    test_browser_cancelled_request_stays_non_executable_and_is_reported()
