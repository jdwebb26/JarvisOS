#!/usr/bin/env python3
"""Tests for kitt_quant_workflow.

Unit tests mock external I/O so no live NVIDIA/SearXNG/Bowser calls.
One smoke test verifies the probe function structure.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_nvidia_ok(content: str = "MARKET STATE\nTest content.") -> dict:
    return {
        "status": "completed",
        "content": content,
        "usage": {"total_tokens": 100},
        "request_id": "nvreq_test",
        "result_id": "nvres_test",
        "error": "",
    }


def _fake_search_ok() -> dict:
    return {
        "query_id": "rq_test",
        "status": "ok",
        "results": [
            {"title": "NQ Futures", "url": "https://example.com/nq", "content": "NQ futures analysis."},
        ],
    }


def _fake_browser_ok(full_text: str = "NQ=F price 20000") -> dict:
    return {
        "status": "completed",
        "content": "Extracted text",
        "error": "",
        "execution_backend": "browser_backend",
        "kind": "executed",
        "browser_action_result": {
            "snapshot": {
                "payload": {
                    "snapshot_refs": {"full_text": full_text, "tab_id": "TAB1", "chars": len(full_text)},
                }
            },
            "result": {"outcome_summary": f"Extracted {len(full_text)} chars: {full_text[:100]}"},
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_probe_returns_required_keys():
    """probe_kitt_runtime must return nvidia, searxng, bowser, kitt_ready keys."""
    from runtime.integrations.kitt_quant_workflow import probe_kitt_runtime

    with (
        patch("runtime.integrations.kitt_quant_workflow.load_nvidia_config", return_value={}),
        patch("runtime.integrations.research_backends.SearXNGBackend.healthcheck",
              return_value={"healthy": True, "status": "healthy"}),
        patch("runtime.integrations.bowser_adapter.probe_bowser_runtime",
              return_value={"reachable": True, "version": "0.8.3", "error": None}),
    ):
        result = probe_kitt_runtime()

    assert "nvidia" in result
    assert "searxng" in result
    assert "bowser" in result
    assert "kitt_ready" in result
    assert result["kitt_ready"] is True


def test_brief_with_query_only(tmp_path):
    """With only query, SearXNG is called and nvidia produces a brief."""
    from runtime.integrations.kitt_quant_workflow import run_kitt_quant_brief

    with (
        patch("runtime.integrations.kitt_quant_workflow.searxng_search",
              return_value=_fake_search_ok()) as mock_search,
        patch("runtime.integrations.kitt_quant_workflow.run_bowser_browser_action") as mock_bowser,
        patch("runtime.integrations.kitt_quant_workflow.execute_nvidia_chat",
              return_value=_fake_nvidia_ok()) as mock_nvidia,
        patch("runtime.integrations.kitt_quant_workflow.update_agent_status"),
    ):
        result = run_kitt_quant_brief(
            task_id="test_query_001",
            query="NQ futures regime",
            root=tmp_path,
        )

    mock_search.assert_called_once()
    mock_bowser.assert_not_called()  # no target_url
    mock_nvidia.assert_called_once()

    assert result["status"] == "completed"
    assert result["brief_text"] == "MARKET STATE\nTest content."
    assert len(result["search_results"]) == 1
    assert result["brief_id"].startswith("kitt_brief_")
    assert result["artifact_path"]


def test_brief_with_target_url_extracts_browser_text(tmp_path):
    """With target_url, Bowser is called and browser text feeds the prompt."""
    from runtime.integrations.kitt_quant_workflow import run_kitt_quant_brief

    browser_text = "NQ=F 20100 +0.5% Vol 350K"
    captured_messages = []

    def capture_nvidia(*args, **kwargs):
        captured_messages.extend(kwargs.get("messages", []))
        return _fake_nvidia_ok()

    with (
        patch("runtime.integrations.kitt_quant_workflow.searxng_search") as mock_search,
        patch("runtime.integrations.kitt_quant_workflow.run_bowser_browser_action",
              return_value=_fake_browser_ok(browser_text)) as mock_bowser,
        patch("runtime.integrations.kitt_quant_workflow.execute_nvidia_chat",
              side_effect=capture_nvidia),
        patch("runtime.integrations.kitt_quant_workflow.update_agent_status"),
    ):
        result = run_kitt_quant_brief(
            task_id="test_url_001",
            target_url="https://finance.yahoo.com/quote/NQ=F",
            root=tmp_path,
        )

    mock_search.assert_not_called()  # no query
    mock_bowser.assert_called_once()
    assert result["status"] == "completed"

    # Browser text must appear in the prompt sent to Kimi
    user_msg = next(m["content"] for m in captured_messages if m["role"] == "user")
    assert browser_text in user_msg


def test_brief_with_query_and_url(tmp_path):
    """With both query and target_url, both SearXNG and Bowser are called."""
    from runtime.integrations.kitt_quant_workflow import run_kitt_quant_brief

    with (
        patch("runtime.integrations.kitt_quant_workflow.searxng_search",
              return_value=_fake_search_ok()),
        patch("runtime.integrations.kitt_quant_workflow.run_bowser_browser_action",
              return_value=_fake_browser_ok()),
        patch("runtime.integrations.kitt_quant_workflow.execute_nvidia_chat",
              return_value=_fake_nvidia_ok()),
        patch("runtime.integrations.kitt_quant_workflow.update_agent_status"),
    ):
        result = run_kitt_quant_brief(
            task_id="test_both_001",
            query="NQ regime",
            target_url="https://finance.yahoo.com/quote/NQ=F",
            root=tmp_path,
        )

    assert result["status"] == "completed"
    assert result["brief_id"]
    assert result["artifact_path"]


def test_nvidia_failure_returns_failed_status(tmp_path):
    """If Kimi returns an error, status is failed and error is populated."""
    from runtime.integrations.kitt_quant_workflow import run_kitt_quant_brief

    nvidia_err = {"status": "error", "content": "", "usage": {}, "request_id": None, "result_id": None, "error": "api_error"}

    with (
        patch("runtime.integrations.kitt_quant_workflow.searxng_search",
              return_value=_fake_search_ok()),
        patch("runtime.integrations.kitt_quant_workflow.run_bowser_browser_action"),
        patch("runtime.integrations.kitt_quant_workflow.execute_nvidia_chat",
              return_value=nvidia_err),
        patch("runtime.integrations.kitt_quant_workflow.update_agent_status"),
    ):
        result = run_kitt_quant_brief(
            task_id="test_fail_001",
            query="NQ regime",
            root=tmp_path,
        )

    assert result["status"] == "failed"
    assert "api_error" in result["error"]


def test_brief_artifact_written_to_disk(tmp_path):
    """Artifact JSON must be written to state/kitt_briefs/ and contain the brief."""
    from runtime.integrations.kitt_quant_workflow import run_kitt_quant_brief

    with (
        patch("runtime.integrations.kitt_quant_workflow.searxng_search",
              return_value=_fake_search_ok()),
        patch("runtime.integrations.kitt_quant_workflow.run_bowser_browser_action"),
        patch("runtime.integrations.kitt_quant_workflow.execute_nvidia_chat",
              return_value=_fake_nvidia_ok("Brief content here.")),
        patch("runtime.integrations.kitt_quant_workflow.update_agent_status"),
        patch("runtime.integrations.kitt_quant_workflow._workspace_research_dir",
              return_value=tmp_path / "research"),
    ):
        result = run_kitt_quant_brief(
            task_id="test_artifact_001",
            query="NQ regime",
            root=tmp_path,
        )

    assert result["status"] == "completed"
    p = Path(result["artifact_path"])
    assert p.exists()
    saved = json.loads(p.read_text())
    assert saved["brief_text"] == "Brief content here."
    assert saved["brief_id"] == result["brief_id"]


def test_searxng_failure_is_non_fatal(tmp_path):
    """A SearXNG error should not crash the workflow; nvidia still runs."""
    from runtime.integrations.kitt_quant_workflow import run_kitt_quant_brief

    with (
        patch("runtime.integrations.kitt_quant_workflow.searxng_search",
              side_effect=RuntimeError("searxng_down")),
        patch("runtime.integrations.kitt_quant_workflow.run_bowser_browser_action"),
        patch("runtime.integrations.kitt_quant_workflow.execute_nvidia_chat",
              return_value=_fake_nvidia_ok()),
        patch("runtime.integrations.kitt_quant_workflow.update_agent_status"),
    ):
        result = run_kitt_quant_brief(
            task_id="test_searxng_fail_001",
            query="NQ regime",
            root=tmp_path,
        )

    # Even with SearXNG down, NVIDIA still ran and produced a brief
    assert result["status"] == "completed"
    assert "searxng_error" in result["error"]


def test_bowser_failure_is_non_fatal(tmp_path):
    """A Bowser error should not crash the workflow; nvidia still runs."""
    from runtime.integrations.kitt_quant_workflow import run_kitt_quant_brief

    with (
        patch("runtime.integrations.kitt_quant_workflow.searxng_search"),
        patch("runtime.integrations.kitt_quant_workflow.run_bowser_browser_action",
              side_effect=RuntimeError("bowser_down")),
        patch("runtime.integrations.kitt_quant_workflow.execute_nvidia_chat",
              return_value=_fake_nvidia_ok()),
        patch("runtime.integrations.kitt_quant_workflow.update_agent_status"),
    ):
        result = run_kitt_quant_brief(
            task_id="test_bowser_fail_001",
            target_url="https://finance.yahoo.com/quote/NQ=F",
            root=tmp_path,
        )

    assert result["status"] == "completed"
    assert "bowser_error" in result["error"]


def test_brief_emits_backend_result_and_event(tmp_path):
    """Successful brief writes backend_result and emits kitt_brief_completed event."""
    from runtime.integrations.kitt_quant_workflow import run_kitt_quant_brief

    captured_backend = []
    captured_events = []

    def mock_save_backend(*a, **kw):
        captured_backend.append(kw)
        return {"result_id": "bkres_test"}

    def mock_emit(kind, agent_id, **kw):
        captured_events.append({"kind": kind, "agent_id": agent_id, **kw})
        return {"event_id": "devt_test"}

    with (
        patch("runtime.integrations.kitt_quant_workflow.searxng_search",
              return_value=_fake_search_ok()),
        patch("runtime.integrations.kitt_quant_workflow.run_bowser_browser_action"),
        patch("runtime.integrations.kitt_quant_workflow.execute_nvidia_chat",
              return_value=_fake_nvidia_ok("MARKET STATE\nBrief.")),
        patch("runtime.integrations.kitt_quant_workflow.update_agent_status"),
        patch("runtime.integrations.kitt_quant_workflow.save_backend_result",
              side_effect=mock_save_backend),
        patch("runtime.integrations.kitt_quant_workflow.emit_event",
              side_effect=mock_emit),
    ):
        result = run_kitt_quant_brief(
            task_id="test_emit_001",
            query="NQ regime",
            root=tmp_path,
        )

    assert result["status"] == "completed"

    # Backend result was saved
    assert len(captured_backend) == 1
    bk = captured_backend[0]
    assert bk["agent_id"] == "kitt"
    assert bk["backend"] == "kitt_quant"
    assert bk["status"] == "ok"

    # Event was emitted
    assert len(captured_events) == 1
    ev = captured_events[0]
    assert ev["kind"] == "kitt_brief_completed"
    assert ev["agent_id"] == "kitt"
    assert "kitt_brief_" in ev["detail"]


def test_failed_brief_emits_failed_event(tmp_path):
    """Failed brief emits kitt_brief_failed event."""
    from runtime.integrations.kitt_quant_workflow import run_kitt_quant_brief

    captured_events = []

    def mock_emit(kind, agent_id, **kw):
        captured_events.append({"kind": kind, "agent_id": agent_id, **kw})
        return {"event_id": "devt_test"}

    nvidia_err = {"status": "error", "content": "", "usage": {}, "request_id": None, "result_id": None, "error": "api_error"}

    with (
        patch("runtime.integrations.kitt_quant_workflow.searxng_search",
              return_value=_fake_search_ok()),
        patch("runtime.integrations.kitt_quant_workflow.run_bowser_browser_action"),
        patch("runtime.integrations.kitt_quant_workflow.execute_nvidia_chat",
              return_value=nvidia_err),
        patch("runtime.integrations.kitt_quant_workflow.update_agent_status"),
        patch("runtime.integrations.kitt_quant_workflow.save_backend_result"),
        patch("runtime.integrations.kitt_quant_workflow.emit_event",
              side_effect=mock_emit),
    ):
        result = run_kitt_quant_brief(
            task_id="test_fail_emit_001",
            query="NQ regime",
            root=tmp_path,
        )

    assert result["status"] == "failed"
    assert len(captured_events) == 1
    assert captured_events[0]["kind"] == "kitt_brief_failed"
