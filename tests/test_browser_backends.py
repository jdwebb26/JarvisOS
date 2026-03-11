from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.browser.backends import PinchTabBackend
from runtime.browser.tracing import (
    browser_snapshots_dir,
    browser_traces_dir,
    load_browser_snapshot,
    load_browser_trace,
    save_browser_snapshot,
    save_browser_trace,
)
from runtime.core.models import BrowserActionRequestRecord, new_id, now_iso


def _request() -> BrowserActionRequestRecord:
    return BrowserActionRequestRecord(
        request_id=new_id("breq"),
        task_id="task_browser_backend",
        created_at=now_iso(),
        updated_at=now_iso(),
        actor="tester",
        lane="tests",
        action_type="navigate_allowlisted_page",
        target_url="https://example.com",
        target_selector="",
        action_params={},
        risk_tier="low",
        review_required=False,
        status="accepted",
        allowlist_ref="browserallow_test",
    )


def test_pinchtab_health_check() -> None:
    backend = PinchTabBackend(config={"enabled": False})
    payload = backend.health_check()
    assert payload["backend"] == "pinchtab"
    assert payload["status"] == "stubbed"
    assert payload["reason"] == "pinchtab_backend_not_connected"


def test_pinchtab_execute_action_returns_stub_result() -> None:
    backend = PinchTabBackend()
    result = backend.execute_action(_request())
    assert result.request_id
    assert result.status == "stubbed"
    assert result.error == "pinchtab_backend_not_connected"


def test_tracing_helpers_create_expected_json_artifacts() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        snapshot = save_browser_snapshot(
            task_id="task_browser_backend",
            actor="tester",
            lane="tests",
            snapshot_kind="dom_capture",
            payload={"url": "https://example.com"},
            request_id="breq_test",
            root=root,
        )
        trace = save_browser_trace(
            task_id="task_browser_backend",
            actor="tester",
            lane="tests",
            trace_kind="browser_action_trace",
            steps=[{"step": "navigate", "status": "stubbed"}],
            request_id="breq_test",
            snapshot_refs={"after": snapshot["snapshot_id"]},
            root=root,
        )
        assert browser_snapshots_dir(root=root).joinpath(f'{snapshot["snapshot_id"]}.json').exists()
        assert browser_traces_dir(root=root).joinpath(f'{trace["trace_id"]}.json').exists()
        assert load_browser_snapshot(snapshot["snapshot_id"], root=root)["payload"]["url"] == "https://example.com"
        assert load_browser_trace(trace["trace_id"], root=root)["steps"][0]["step"] == "navigate"


if __name__ == "__main__":
    test_pinchtab_health_check()
    test_pinchtab_execute_action_returns_stub_result()
    test_tracing_helpers_create_expected_json_artifacts()
