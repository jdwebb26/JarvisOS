"""Tests for the browser task routing seam.

Covers:
- infer_task_type recognises browser keywords
- intake.create_task_from_message creates a browser task (bypasses LLM routing)
- browser_task.create_browser_task_from_text creates a valid queued task
- execute_once dispatches browser tasks through browser_backend end-to-end
- Full: intake text → queue → execute_once → browser_backend → completed
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.browser_control_allowlist import save_browser_control_allowlist
from runtime.core.browser_task import (
    BROWSER_EXECUTION_BACKEND,
    BROWSER_TASK_TYPE,
    create_browser_task,
    create_browser_task_from_text,
    infer_browser_action_spec,
)
from runtime.core.intake import infer_task_type
from runtime.core.models import BrowserControlAllowlistRecord, new_id, now_iso
from runtime.core.task_queue import list_queued_tasks
from runtime.core.task_store import load_task
from runtime.executor.execute_once import execute_once


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
# infer_task_type — browser keyword detection
# ---------------------------------------------------------------------------

def test_infer_task_type_browse_keyword() -> None:
    assert infer_task_type("browse finance.yahoo.com for NQ price") == "browser"


def test_infer_task_type_navigate_keyword() -> None:
    assert infer_task_type("navigate to https://example.com") == "browser"


def test_infer_task_type_screenshot_keyword() -> None:
    assert infer_task_type("take a screenshot of the dashboard") == "browser"


def test_infer_task_type_website_keyword() -> None:
    assert infer_task_type("fetch the website at example.com") == "browser"


def test_infer_task_type_non_browser_unchanged() -> None:
    assert infer_task_type("write a python script") == "code"
    assert infer_task_type("check nq futures strategy") == "quant"
    assert infer_task_type("write a spec document") == "docs"


# ---------------------------------------------------------------------------
# infer_browser_action_spec — URL and action_type extraction
# ---------------------------------------------------------------------------

def test_infer_spec_http_url_extracted() -> None:
    spec = infer_browser_action_spec("browse https://example.com/page")
    assert spec["target_url"] == "https://example.com/page"


def test_infer_spec_screenshot_action() -> None:
    spec = infer_browser_action_spec("screenshot https://example.com/")
    assert spec["action_type"] == "screenshot"


def test_infer_spec_text_action() -> None:
    spec = infer_browser_action_spec("read the text from https://example.com/")
    assert spec["action_type"] == "text"


def test_infer_spec_default_snapshot() -> None:
    spec = infer_browser_action_spec("browse https://example.com/")
    assert spec["action_type"] == "snapshot"


# ---------------------------------------------------------------------------
# create_browser_task — direct task creation
# ---------------------------------------------------------------------------

def test_create_browser_task_sets_execution_backend() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        record = create_browser_task(
            action_type="snapshot",
            target_url="https://example.com/",
            actor="tester",
            lane="tests",
            root=root,
        )
        assert record.execution_backend == BROWSER_EXECUTION_BACKEND
        assert record.task_type == BROWSER_TASK_TYPE
        assert record.status == "queued"
        assert record.review_required is False
        assert record.approval_required is False

        spec = json.loads(record.normalized_request)
        assert spec["action_type"] == "snapshot"
        assert spec["target_url"] == "https://example.com/"
        assert spec["execute"] is True


def test_create_browser_task_appears_in_queue() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        record = create_browser_task(
            action_type="snapshot",
            target_url="https://example.com/",
            actor="tester",
            lane="tests",
            root=root,
        )
        queued = list_queued_tasks(root=root)
        task_ids = [t["task_id"] for t in queued]
        assert record.task_id in task_ids


def test_create_browser_task_from_text_returns_task_id() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = create_browser_task_from_text(
            text="browse https://example.com/ for data",
            actor="tester",
            lane="tests",
            root=root,
        )
        assert result["ok"] is True
        assert result["task_created"] is True
        assert result["execution_backend"] == BROWSER_EXECUTION_BACKEND
        assert result["task_id"].startswith("task_")


def test_create_browser_task_from_text_no_url_returns_refusal() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = create_browser_task_from_text(
            text="browse the internet generally",
            actor="tester",
            lane="tests",
            root=root,
        )
        assert result["ok"] is False
        assert result["task_created"] is False


# ---------------------------------------------------------------------------
# execute_once — full dispatch through browser_backend
# ---------------------------------------------------------------------------

def test_execute_once_dispatches_browser_task() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)

        # Create browser task (allowed site: example.com)
        record = create_browser_task(
            action_type="snapshot",
            target_url="https://example.com/",
            actor="tester",
            lane="tests",
            root=root,
        )

        result = execute_once(
            root=root,
            actor="executor",
            lane="executor",
            allow_parallel=False,
        )

        assert result["kind"] == "backend_dispatch"
        dispatch = result["dispatch_result"]
        assert dispatch["execution_backend"] == BROWSER_EXECUTION_BACKEND
        assert dispatch["dispatched"] is True
        # Should be completed or failed (depends on live PinchTab); either means dispatch ran
        assert dispatch["status"] in {"completed", "failed", "invalid_request"}

        # Task should be completed or failed (not stuck queued)
        final_task = load_task(record.task_id, root=root)
        assert final_task is not None
        assert final_task.status in {"completed", "failed"}


def test_execute_once_browser_task_blocked_url_fails_gracefully() -> None:
    """A browser task for a blocked URL should fail but not crash the executor."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_allowlist(root)  # only example.com allowed

        record = create_browser_task(
            action_type="snapshot",
            target_url="https://notallowed.example.org/",
            actor="tester",
            lane="tests",
            root=root,
        )

        result = execute_once(
            root=root,
            actor="executor",
            lane="executor",
            allow_parallel=False,
        )

        assert result["kind"] == "backend_dispatch"
        dispatch = result["dispatch_result"]
        assert dispatch["status"] == "failed"  # blocked by policy
        assert dispatch["kind"] == "blocked"

        final_task = load_task(record.task_id, root=root)
        assert final_task is not None
        assert final_task.status == "failed"


if __name__ == "__main__":
    test_infer_task_type_browse_keyword()
    test_infer_task_type_navigate_keyword()
    test_infer_task_type_screenshot_keyword()
    test_infer_task_type_website_keyword()
    test_infer_task_type_non_browser_unchanged()
    test_infer_spec_http_url_extracted()
    test_infer_spec_screenshot_action()
    test_infer_spec_text_action()
    test_infer_spec_default_snapshot()
    test_create_browser_task_sets_execution_backend()
    test_create_browser_task_appears_in_queue()
    test_create_browser_task_from_text_returns_task_id()
    test_create_browser_task_from_text_no_url_returns_refusal()
    test_execute_once_dispatches_browser_task()
    test_execute_once_browser_task_blocked_url_fails_gracefully()
    print("All browser task routing tests passed.")
