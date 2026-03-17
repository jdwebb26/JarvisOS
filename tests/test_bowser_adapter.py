"""Tests for runtime/integrations/bowser_adapter.py

Covers:
- Invalid spec in messages → INVALID_REQUEST_STATUS
- Blocked URL (not in allowlist) → FAILED_STATUS, kind=blocked
- Accepted action (execute=False) → SUCCESS_STATUS, kind=accepted
- Direct API run_bowser_browser_action mirrors messages path
- dispatch_to_backend routes browser_backend to bowser adapter
"""
from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.browser_control_allowlist import save_browser_control_allowlist
from runtime.core.models import BrowserControlAllowlistRecord, new_id, now_iso
from runtime.integrations.bowser_adapter import (
    FAILED_STATUS,
    INVALID_REQUEST_STATUS,
    SUCCESS_STATUS,
    execute_bowser_action,
    run_bowser_browser_action,
    probe_bowser_runtime,
)
from runtime.executor.backend_dispatch import dispatch_to_backend, has_backend_adapter


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


# ---------------------------------------------------------------------------
# Spec parsing
# ---------------------------------------------------------------------------

def test_missing_spec_returns_invalid_request() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        result = execute_bowser_action(
            task_id="ba_test_1",
            actor="tester",
            lane="tests",
            messages=[{"role": "user", "content": "just plain text, no json"}],
            root=root,
        )
        assert result["status"] == INVALID_REQUEST_STATUS
        assert result["dispatched"] is True
        assert "action_type" in result["error"]


def test_json_spec_in_messages_is_parsed() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        spec = json.dumps({"action_type": "navigate_allowlisted_page", "target_url": "https://example.com/", "execute": False})
        result = execute_bowser_action(
            task_id="ba_test_2",
            actor="tester",
            lane="tests",
            messages=[{"role": "user", "content": spec}],
            root=root,
        )
        assert result["status"] == SUCCESS_STATUS
        assert result["kind"] == "accepted"


def test_json_in_markdown_code_block_is_parsed() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        spec_body = json.dumps({"action_type": "navigate_allowlisted_page", "target_url": "https://example.com/", "execute": False})
        content = f"Navigate here:\n```json\n{spec_body}\n```"
        result = execute_bowser_action(
            task_id="ba_test_3",
            actor="tester",
            lane="tests",
            messages=[{"role": "user", "content": content}],
            root=root,
        )
        assert result["status"] == SUCCESS_STATUS
        assert result["kind"] == "accepted"


# ---------------------------------------------------------------------------
# Policy gating
# ---------------------------------------------------------------------------

def test_blocked_url_returns_failed_with_blocked_kind() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        result = run_bowser_browser_action(
            task_id="ba_test_4",
            actor="tester",
            lane="tests",
            action_type="navigate",
            target_url="https://notallowed.tld/",
            execute=False,
            root=root,
        )
        assert result["status"] == FAILED_STATUS
        assert result["kind"] == "blocked"
        assert "blocked" in result["error"]


def test_accepted_action_execute_false_succeeds() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        result = run_bowser_browser_action(
            task_id="ba_test_5",
            actor="tester",
            lane="tests",
            action_type="navigate_allowlisted_page",
            target_url="https://example.com/home",
            execute=False,
            root=root,
        )
        assert result["status"] == SUCCESS_STATUS
        assert result["kind"] == "accepted"
        assert result["request_id"] is not None


# ---------------------------------------------------------------------------
# backend_dispatch integration
# ---------------------------------------------------------------------------

def test_browser_backend_is_registered_in_dispatch() -> None:
    assert has_backend_adapter("browser_backend"), (
        "browser_backend must be wired in BACKEND_ADAPTERS"
    )


def test_dispatch_to_browser_backend_routes_correctly() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)
        spec = json.dumps({"action_type": "navigate_allowlisted_page", "target_url": "https://example.com/", "execute": False})
        result = dispatch_to_backend(
            task_id="ba_test_6",
            actor="tester",
            lane="tests",
            execution_backend="browser_backend",
            messages=[{"role": "user", "content": spec}],
            root=root,
        )
        assert result["execution_backend"] == "browser_backend"
        assert result["dispatched"] is True
        assert result["status"] == SUCCESS_STATUS


# ---------------------------------------------------------------------------
# Probe (live, no side-effects)
# ---------------------------------------------------------------------------

def test_probe_bowser_runtime_returns_reachability_info() -> None:
    result = probe_bowser_runtime()
    assert "reachable" in result
    assert "status" in result
    # If PinchTab is running we expect reachable=True; if not, we expect an error field
    if result["reachable"]:
        assert result["status"] == "ok"
    else:
        assert result["error"] is not None


if __name__ == "__main__":
    test_missing_spec_returns_invalid_request()
    test_json_spec_in_messages_is_parsed()
    test_json_in_markdown_code_block_is_parsed()
    test_blocked_url_returns_failed_with_blocked_kind()
    test_accepted_action_execute_false_succeeds()
    test_browser_backend_is_registered_in_dispatch()
    test_dispatch_to_browser_backend_routes_correctly()
    test_probe_bowser_runtime_returns_reachability_info()
    print("All bowser_adapter tests passed.")
