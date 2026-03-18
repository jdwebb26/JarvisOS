#!/usr/bin/env python3
"""Tests for openai_executor adapter.

Covers:
- Config present / missing (with ChatGPT billing warning)
- Successful request shape
- API error handling (HTTP errors, timeouts, connection errors)
- Provenance record creation
- extract_content / extract_usage helpers
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestLoadOpenAIConfig:
    def test_config_from_env(self, monkeypatch):
        from runtime.integrations.openai_executor import load_openai_config

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-123")
        monkeypatch.delenv("OPENAI_API_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_MODEL", raising=False)

        cfg = load_openai_config()
        assert cfg["api_key"] == "sk-test-key-123"
        assert cfg["base_url"] == "https://api.openai.com/v1"
        assert cfg["model"] == "gpt-4.1-mini"
        assert cfg["timeout"] == (10, 120)

    def test_config_from_override(self, monkeypatch):
        from runtime.integrations.openai_executor import load_openai_config

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg = load_openai_config(override={
            "api_key": "override-key",
            "base_url": "https://custom.openai.api/v1/",
            "model": "gpt-4o",
            "timeout": [5, 60],
        })
        assert cfg["api_key"] == "override-key"
        assert cfg["base_url"] == "https://custom.openai.api/v1"  # trailing slash stripped
        assert cfg["model"] == "gpt-4o"
        assert cfg["timeout"] == (5.0, 60.0)

    def test_config_missing_key_raises(self, monkeypatch):
        from runtime.integrations.openai_executor import OpenAIConfigError, load_openai_config

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(OpenAIConfigError, match="OPENAI_API_KEY is not set"):
            load_openai_config()

    def test_config_missing_key_mentions_chatgpt_billing(self, monkeypatch):
        from runtime.integrations.openai_executor import OpenAIConfigError, load_openai_config

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(OpenAIConfigError, match="ChatGPT subscription does NOT fund API"):
            load_openai_config()

    def test_env_override_base_url(self, monkeypatch):
        from runtime.integrations.openai_executor import load_openai_config

        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setenv("OPENAI_API_BASE_URL", "http://localhost:8080/v1")
        cfg = load_openai_config()
        assert cfg["base_url"] == "http://localhost:8080/v1"

    def test_env_override_model(self, monkeypatch):
        from runtime.integrations.openai_executor import load_openai_config

        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
        cfg = load_openai_config()
        assert cfg["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# Chat completion tests
# ---------------------------------------------------------------------------


def _fake_response(content="Hello", usage=None, status_code=200, model="gpt-4.1-mini"):
    """Build a mock requests.Response for a successful chat completion."""
    body = {
        "id": "chatcmpl-test-openai-123",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = json.dumps(body)
    resp.raise_for_status.return_value = None
    return resp


class TestOpenAIChatCompletion:
    def test_successful_call(self, monkeypatch):
        from runtime.integrations.openai_executor import openai_chat_completion

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        mock_resp = _fake_response(content="Test response")

        with patch("runtime.integrations.openai_executor._requests") as mock_requests:
            mock_requests.post.return_value = mock_resp
            mock_requests.Timeout = Exception
            mock_requests.HTTPError = Exception
            mock_requests.ConnectionError = Exception
            mock_requests.RequestException = Exception

            result = openai_chat_completion(
                [{"role": "user", "content": "Hello"}],
                temperature=0.1,
                max_tokens=100,
            )

        assert result["choices"][0]["message"]["content"] == "Test response"
        call_args = mock_requests.post.call_args
        assert "/chat/completions" in call_args[0][0]
        payload = call_args[1]["json"]
        assert payload["model"] == "gpt-4.1-mini"
        assert payload["temperature"] == 0.1
        assert payload["max_tokens"] == 100
        assert payload["messages"] == [{"role": "user", "content": "Hello"}]
        assert "Bearer sk-test-key" in call_args[1]["headers"]["Authorization"]

    def test_timeout_raises_openai_api_error(self, monkeypatch):
        from runtime.integrations.openai_executor import OpenAIAPIError, openai_chat_completion

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        with patch("runtime.integrations.openai_executor._requests") as mock_requests:
            mock_requests.Timeout = type("Timeout", (Exception,), {})
            mock_requests.HTTPError = type("HTTPError", (Exception,), {})
            mock_requests.ConnectionError = type("ConnectionError", (Exception,), {})
            mock_requests.RequestException = type("RequestException", (Exception,), {})
            mock_requests.post.side_effect = mock_requests.Timeout("timed out")

            with pytest.raises(OpenAIAPIError, match="timeout"):
                openai_chat_completion([{"role": "user", "content": "Hello"}])

    def test_http_error_includes_status_code(self, monkeypatch):
        from runtime.integrations.openai_executor import OpenAIAPIError, openai_chat_completion

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        with patch("runtime.integrations.openai_executor._requests") as mock_requests:
            http_error_cls = type("HTTPError", (Exception,), {})
            mock_requests.Timeout = type("Timeout", (Exception,), {})
            mock_requests.HTTPError = http_error_cls
            mock_requests.ConnectionError = type("ConnectionError", (Exception,), {})
            mock_requests.RequestException = type("RequestException", (Exception,), {})

            err_response = MagicMock()
            err_response.status_code = 429
            err_response.text = "rate limited"
            http_err = http_error_cls("429 Too Many Requests")
            http_err.response = err_response

            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = http_err
            mock_requests.post.return_value = mock_resp

            with pytest.raises(OpenAIAPIError) as exc_info:
                openai_chat_completion([{"role": "user", "content": "Hello"}])
            assert exc_info.value.status_code == 429
            assert exc_info.value.response_body == "rate limited"

    def test_connection_error(self, monkeypatch):
        from runtime.integrations.openai_executor import OpenAIAPIError, openai_chat_completion

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        with patch("runtime.integrations.openai_executor._requests") as mock_requests:
            conn_error_cls = type("ConnectionError", (Exception,), {})
            mock_requests.Timeout = type("Timeout", (Exception,), {})
            mock_requests.HTTPError = type("HTTPError", (Exception,), {})
            mock_requests.ConnectionError = conn_error_cls
            mock_requests.RequestException = type("RequestException", (Exception,), {})
            mock_requests.post.side_effect = conn_error_cls("connection refused")

            with pytest.raises(OpenAIAPIError, match="connection error"):
                openai_chat_completion([{"role": "user", "content": "Hello"}])

    def test_requests_not_installed(self, monkeypatch):
        from runtime.integrations import openai_executor

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        original = openai_executor._requests
        openai_executor._requests = None
        try:
            with pytest.raises(RuntimeError, match="requests"):
                openai_executor.openai_chat_completion([{"role": "user", "content": "Hello"}])
        finally:
            openai_executor._requests = original


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestExtractHelpers:
    def test_extract_content_normal(self):
        from runtime.integrations.openai_executor import extract_content

        resp = _fake_response(content="Hello world").json()
        assert extract_content(resp) == "Hello world"

    def test_extract_content_empty_choices(self):
        from runtime.integrations.openai_executor import extract_content

        assert extract_content({"choices": []}) == ""
        assert extract_content({}) == ""

    def test_extract_usage(self):
        from runtime.integrations.openai_executor import extract_usage

        resp = _fake_response(usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}).json()
        usage = extract_usage(resp)
        assert usage == {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}

    def test_extract_usage_missing(self):
        from runtime.integrations.openai_executor import extract_usage

        usage = extract_usage({})
        assert usage == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


# ---------------------------------------------------------------------------
# Provenance-tracked execution tests
# ---------------------------------------------------------------------------


class TestExecuteOpenAIChat:
    def test_successful_execution_records_provenance(self, tmp_path, monkeypatch):
        from runtime.integrations.openai_executor import execute_openai_chat

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        with patch("runtime.integrations.openai_executor._requests") as mock_requests:
            mock_requests.post.return_value = _fake_response(content="provenance test")
            mock_requests.Timeout = Exception
            mock_requests.HTTPError = Exception
            mock_requests.ConnectionError = Exception
            mock_requests.RequestException = Exception

            result = execute_openai_chat(
                task_id="task_openai_test_001",
                actor="hal",
                lane="work",
                messages=[{"role": "user", "content": "Hello"}],
                root=tmp_path,
            )

        assert result["status"] == "completed"
        assert result["content"] == "provenance test"
        assert result["usage"]["total_tokens"] == 15
        assert result["request_id"] is not None
        assert result["result_id"] is not None
        assert result["error"] == ""

        # Verify provenance files were written
        req_dir = tmp_path / "state" / "backend_execution_requests"
        res_dir = tmp_path / "state" / "backend_execution_results"
        assert any(req_dir.glob("*.json"))
        assert any(res_dir.glob("*.json"))

        req_files = list(req_dir.glob("*.json"))
        req_data = json.loads(req_files[0].read_text())
        assert req_data["provider_id"] == "openai"
        assert req_data["execution_backend"] == "openai_executor"

    def test_missing_key_returns_config_error(self, tmp_path, monkeypatch):
        from runtime.integrations.openai_executor import execute_openai_chat

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        result = execute_openai_chat(
            task_id="task_openai_test_002",
            actor="hal",
            lane="work",
            messages=[{"role": "user", "content": "Hello"}],
            root=tmp_path,
        )

        assert result["status"] == "config_error"
        assert "OPENAI_API_KEY" in result["error"]
        assert "ChatGPT subscription" in result["error"]
        assert result["content"] == ""
        assert result["request_id"] is None

    def test_api_error_records_failure_provenance(self, tmp_path, monkeypatch):
        from runtime.integrations.openai_executor import execute_openai_chat

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        with patch("runtime.integrations.openai_executor._requests") as mock_requests:
            timeout_cls = type("Timeout", (Exception,), {})
            mock_requests.Timeout = timeout_cls
            mock_requests.HTTPError = type("HTTPError", (Exception,), {})
            mock_requests.ConnectionError = type("ConnectionError", (Exception,), {})
            mock_requests.RequestException = type("RequestException", (Exception,), {})
            mock_requests.post.side_effect = timeout_cls("timed out")

            result = execute_openai_chat(
                task_id="task_openai_test_003",
                actor="hal",
                lane="work",
                messages=[{"role": "user", "content": "Hello"}],
                root=tmp_path,
            )

        assert result["status"] == "transient_error"
        assert result["transient"] is True
        assert "timeout" in result["error"].lower()
        assert result["request_id"] is not None
        assert result["result_id"] is None

        # Verify error provenance was recorded
        res_dir = tmp_path / "state" / "backend_execution_results"
        res_files = list(res_dir.glob("*.json"))
        assert len(res_files) == 1
        res_data = json.loads(res_files[0].read_text())
        assert res_data["status"] == "transient_error"
        assert res_data["error"]

    def test_override_config(self, tmp_path, monkeypatch):
        from runtime.integrations.openai_executor import execute_openai_chat

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with patch("runtime.integrations.openai_executor._requests") as mock_requests:
            mock_requests.post.return_value = _fake_response(content="override test")
            mock_requests.Timeout = Exception
            mock_requests.HTTPError = Exception
            mock_requests.ConnectionError = Exception
            mock_requests.RequestException = Exception

            result = execute_openai_chat(
                task_id="task_openai_test_004",
                actor="hal",
                lane="work",
                messages=[{"role": "user", "content": "Hello"}],
                override={"api_key": "sk-override-key", "model": "gpt-4o"},
                root=tmp_path,
            )

        assert result["status"] == "completed"
        call_payload = mock_requests.post.call_args[1]["json"]
        assert call_payload["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# BackendRuntime enum test
# ---------------------------------------------------------------------------


class TestBackendRuntimeEnum:
    def test_openai_executor_in_enum(self):
        from runtime.core.models import BackendRuntime

        assert hasattr(BackendRuntime, "OPENAI_EXECUTOR")
        assert BackendRuntime.OPENAI_EXECUTOR.value == "openai_executor"


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
