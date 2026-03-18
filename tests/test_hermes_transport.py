#!/usr/bin/env python3
"""Tests for hermes_transport — LM Studio Qwen transport for Hermes."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import new_id, now_iso
from runtime.core.models import HermesTaskRequestRecord as HermesTaskRequest
from runtime.integrations.hermes_adapter import HermesTransportUnreachableError
from runtime.integrations.hermes_transport import (
    _parse_structured_content,
    lmstudio_transport,
)


def _make_request(objective: str = "Test research task") -> HermesTaskRequest:
    return HermesTaskRequest(
        request_id=new_id("hermesreq"),
        task_id=new_id("task"),
        created_at=now_iso(),
        requested_by="test",
        lane="hermes",
        objective=objective,
        timeout_seconds=30,
        execution_backend="hermes_adapter",
        sandbox_class="bounded",
        allowed_tools=["candidate_artifact_write", "bounded_research_synthesis"],
        model_override_policy={"allowed_families": ["qwen3.5"], "provider_policy": "qwen_only"},
        return_format="candidate_artifact",
        capability_declaration={"task_type": "research", "required_capabilities": []},
        callback_contract={"kind": "task_event", "task_id": "test", "lane": "hermes"},
    )


def test_parse_structured_json():
    raw = json.dumps({
        "title": "Test Title",
        "summary": "Test summary.",
        "content": "Full report content here.",
        "citations": [{"url": "https://example.com", "title": "Example"}],
        "proposed_next_actions": [{"action": "check", "reason": "verification"}],
    })
    result = _parse_structured_content(raw)
    assert result["title"] == "Test Title"
    assert result["summary"] == "Test summary."
    assert result["content"] == "Full report content here."
    assert len(result["citations"]) == 1
    assert len(result["proposed_next_actions"]) == 1


def test_parse_structured_json_with_fences():
    raw = "```json\n" + json.dumps({
        "title": "Fenced",
        "summary": "Summary.",
        "content": "Content.",
        "citations": [],
        "proposed_next_actions": [],
    }) + "\n```"
    result = _parse_structured_content(raw)
    assert result["title"] == "Fenced"


def test_parse_fallback_unstructured():
    raw = "# My Report\n\nThis is free-form text without JSON."
    result = _parse_structured_content(raw)
    assert result["title"] == "My Report"
    assert "free-form text" in result["content"]
    assert result["citations"] == []


def test_transport_connection_error():
    request = _make_request()
    mock_resp = MagicMock()
    with patch("runtime.integrations.hermes_transport._requests") as mock_requests:
        mock_requests.exceptions.ConnectionError = ConnectionError
        mock_requests.exceptions.Timeout = TimeoutError
        mock_requests.post.side_effect = ConnectionError("refused")
        with pytest.raises(HermesTransportUnreachableError, match="unreachable"):
            lmstudio_transport(request)


def test_transport_success_mock():
    request = _make_request()
    api_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "title": "Mock Report",
                        "summary": "Mock summary.",
                        "content": "Mock content.",
                        "citations": [],
                        "proposed_next_actions": [],
                    })
                }
            }
        ],
        "model": "qwen3.5-35b-a3b",
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = api_response
    with patch("runtime.integrations.hermes_transport._requests") as mock_requests:
        mock_requests.post.return_value = mock_resp
        result = lmstudio_transport(request)

    assert result["title"] == "Mock Report"
    assert result["family"] == "qwen3.5"
    assert result["model_name"] == "qwen3.5-35b-a3b"
    assert result["token_usage"]["total_tokens"] == 30


def test_backend_dispatch_hermes_wired():
    from runtime.executor.backend_dispatch import (
        BACKEND_ADAPTERS,
        KNOWN_BUT_UNWIRED,
        has_backend_adapter,
        is_known_backend,
    )
    assert "hermes_adapter" in BACKEND_ADAPTERS
    assert "hermes_adapter" not in KNOWN_BUT_UNWIRED
    assert has_backend_adapter("hermes_adapter")
    assert is_known_backend("hermes_adapter")
