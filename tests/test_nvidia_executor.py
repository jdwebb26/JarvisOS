#!/usr/bin/env python3
"""Tests for nvidia_executor adapter.

Covers:
- Config present / missing
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
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestLoadNvidiaConfig:
    def test_config_from_env(self, monkeypatch):
        from runtime.integrations.nvidia_executor import load_nvidia_config

        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key-123")
        monkeypatch.delenv("NVIDIA_API_BASE_URL", raising=False)
        monkeypatch.delenv("NVIDIA_MODEL", raising=False)

        cfg = load_nvidia_config()
        assert cfg["api_key"] == "nvapi-test-key-123"
        assert cfg["base_url"] == "https://integrate.api.nvidia.com/v1"
        assert cfg["model"] == "moonshotai/kimi-k2.5"
        assert cfg["timeout"] == (10, 180)

    def test_config_from_override(self, monkeypatch):
        from runtime.integrations.nvidia_executor import load_nvidia_config

        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        cfg = load_nvidia_config(override={
            "api_key": "override-key",
            "base_url": "https://custom.nvidia.api/v1/",
            "model": "custom-model",
            "timeout": [5, 60],
        })
        assert cfg["api_key"] == "override-key"
        assert cfg["base_url"] == "https://custom.nvidia.api/v1"  # trailing slash stripped
        assert cfg["model"] == "custom-model"
        assert cfg["timeout"] == (5.0, 60.0)

    def test_config_missing_key_raises(self, monkeypatch):
        from runtime.integrations.nvidia_executor import NvidiaConfigError, load_nvidia_config

        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        with pytest.raises(NvidiaConfigError, match="NVIDIA_API_KEY is not set"):
            load_nvidia_config()

    def test_env_override_base_url(self, monkeypatch):
        from runtime.integrations.nvidia_executor import load_nvidia_config

        monkeypatch.setenv("NVIDIA_API_KEY", "k")
        monkeypatch.setenv("NVIDIA_API_BASE_URL", "http://localhost:9999/v1")
        cfg = load_nvidia_config()
        assert cfg["base_url"] == "http://localhost:9999/v1"

    def test_env_override_model(self, monkeypatch):
        from runtime.integrations.nvidia_executor import load_nvidia_config

        monkeypatch.setenv("NVIDIA_API_KEY", "k")
        monkeypatch.setenv("NVIDIA_MODEL", "other-model")
        cfg = load_nvidia_config()
        assert cfg["model"] == "other-model"


# ---------------------------------------------------------------------------
# Chat completion tests
# ---------------------------------------------------------------------------


def _fake_response(content="Hello", usage=None, status_code=200, model="moonshotai/kimi-k2.5"):
    """Build a mock requests.Response for a successful chat completion."""
    body = {
        "id": "chatcmpl-test-123",
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


class TestNvidiaChatCompletion:
    def test_successful_call(self, monkeypatch):
        from runtime.integrations.nvidia_executor import nvidia_chat_completion

        monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
        mock_resp = _fake_response(content="Test response")

        with patch("runtime.integrations.nvidia_executor._requests") as mock_requests:
            mock_requests.post.return_value = mock_resp
            mock_requests.Timeout = Exception
            mock_requests.HTTPError = Exception
            mock_requests.ConnectionError = Exception
            mock_requests.RequestException = Exception

            result = nvidia_chat_completion(
                [{"role": "user", "content": "Hello"}],
                temperature=0.1,
                max_tokens=100,
            )

        assert result["choices"][0]["message"]["content"] == "Test response"
        call_args = mock_requests.post.call_args
        assert "/chat/completions" in call_args[0][0]
        payload = call_args[1]["json"]
        assert payload["model"] == "moonshotai/kimi-k2.5"
        assert payload["temperature"] == 0.1
        assert payload["max_tokens"] == 100
        assert payload["messages"] == [{"role": "user", "content": "Hello"}]
        assert "Bearer test-key" in call_args[1]["headers"]["Authorization"]

    def test_timeout_raises_nvidia_api_error(self, monkeypatch):
        from runtime.integrations.nvidia_executor import NvidiaAPIError, nvidia_chat_completion

        monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

        with patch("runtime.integrations.nvidia_executor._requests") as mock_requests:
            mock_requests.Timeout = type("Timeout", (Exception,), {})
            mock_requests.HTTPError = type("HTTPError", (Exception,), {})
            mock_requests.ConnectionError = type("ConnectionError", (Exception,), {})
            mock_requests.RequestException = type("RequestException", (Exception,), {})
            mock_requests.post.side_effect = mock_requests.Timeout("timed out")

            with pytest.raises(NvidiaAPIError, match="timeout"):
                nvidia_chat_completion([{"role": "user", "content": "Hello"}])

    def test_http_error_includes_status_code(self, monkeypatch):
        from runtime.integrations.nvidia_executor import NvidiaAPIError, nvidia_chat_completion

        monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

        with patch("runtime.integrations.nvidia_executor._requests") as mock_requests:
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

            with pytest.raises(NvidiaAPIError) as exc_info:
                nvidia_chat_completion([{"role": "user", "content": "Hello"}])
            assert exc_info.value.status_code == 429
            assert exc_info.value.response_body == "rate limited"

    def test_connection_error(self, monkeypatch):
        from runtime.integrations.nvidia_executor import NvidiaAPIError, nvidia_chat_completion

        monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

        with patch("runtime.integrations.nvidia_executor._requests") as mock_requests:
            conn_error_cls = type("ConnectionError", (Exception,), {})
            mock_requests.Timeout = type("Timeout", (Exception,), {})
            mock_requests.HTTPError = type("HTTPError", (Exception,), {})
            mock_requests.ConnectionError = conn_error_cls
            mock_requests.RequestException = type("RequestException", (Exception,), {})
            mock_requests.post.side_effect = conn_error_cls("connection refused")

            with pytest.raises(NvidiaAPIError, match="connection error"):
                nvidia_chat_completion([{"role": "user", "content": "Hello"}])

    def test_requests_not_installed(self, monkeypatch):
        from runtime.integrations import nvidia_executor

        monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
        original = nvidia_executor._requests
        nvidia_executor._requests = None
        try:
            with pytest.raises(RuntimeError, match="requests"):
                nvidia_executor.nvidia_chat_completion([{"role": "user", "content": "Hello"}])
        finally:
            nvidia_executor._requests = original


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestExtractHelpers:
    def test_extract_content_normal(self):
        from runtime.integrations.nvidia_executor import extract_content

        resp = _fake_response(content="Hello world").json()
        assert extract_content(resp) == "Hello world"

    def test_extract_content_empty_choices(self):
        from runtime.integrations.nvidia_executor import extract_content

        assert extract_content({"choices": []}) == ""
        assert extract_content({}) == ""

    def test_extract_usage(self):
        from runtime.integrations.nvidia_executor import extract_usage

        resp = _fake_response(usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}).json()
        usage = extract_usage(resp)
        assert usage == {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}

    def test_extract_usage_missing(self):
        from runtime.integrations.nvidia_executor import extract_usage

        usage = extract_usage({})
        assert usage == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


# ---------------------------------------------------------------------------
# Provenance-tracked execution tests
# ---------------------------------------------------------------------------


class TestExecuteNvidiaChat:
    def test_successful_execution_records_provenance(self, tmp_path, monkeypatch):
        from runtime.integrations.nvidia_executor import execute_nvidia_chat

        monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

        with patch("runtime.integrations.nvidia_executor._requests") as mock_requests:
            mock_requests.post.return_value = _fake_response(content="provenance test")
            mock_requests.Timeout = Exception
            mock_requests.HTTPError = Exception
            mock_requests.ConnectionError = Exception
            mock_requests.RequestException = Exception

            result = execute_nvidia_chat(
                task_id="task_nvidia_test_001",
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
        assert req_data["provider_id"] == "nvidia"
        assert req_data["execution_backend"] == "nvidia_executor"

    def test_missing_key_returns_config_error(self, tmp_path, monkeypatch):
        from runtime.integrations.nvidia_executor import execute_nvidia_chat

        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

        result = execute_nvidia_chat(
            task_id="task_nvidia_test_002",
            actor="hal",
            lane="work",
            messages=[{"role": "user", "content": "Hello"}],
            root=tmp_path,
        )

        assert result["status"] == "config_error"
        assert "NVIDIA_API_KEY" in result["error"]
        assert result["content"] == ""
        assert result["request_id"] is None

    def test_api_error_records_failure_provenance(self, tmp_path, monkeypatch):
        from runtime.integrations.nvidia_executor import execute_nvidia_chat

        monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

        with patch("runtime.integrations.nvidia_executor._requests") as mock_requests:
            timeout_cls = type("Timeout", (Exception,), {})
            mock_requests.Timeout = timeout_cls
            mock_requests.HTTPError = type("HTTPError", (Exception,), {})
            mock_requests.ConnectionError = type("ConnectionError", (Exception,), {})
            mock_requests.RequestException = type("RequestException", (Exception,), {})
            mock_requests.post.side_effect = timeout_cls("timed out")

            result = execute_nvidia_chat(
                task_id="task_nvidia_test_003",
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
        from runtime.integrations.nvidia_executor import execute_nvidia_chat

        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

        with patch("runtime.integrations.nvidia_executor._requests") as mock_requests:
            mock_requests.post.return_value = _fake_response(content="override test")
            mock_requests.Timeout = Exception
            mock_requests.HTTPError = Exception
            mock_requests.ConnectionError = Exception
            mock_requests.RequestException = Exception

            result = execute_nvidia_chat(
                task_id="task_nvidia_test_004",
                actor="hal",
                lane="work",
                messages=[{"role": "user", "content": "Hello"}],
                override={"api_key": "override-key", "model": "custom-model"},
                root=tmp_path,
            )

        assert result["status"] == "completed"
        call_payload = mock_requests.post.call_args[1]["json"]
        assert call_payload["model"] == "custom-model"


# ---------------------------------------------------------------------------
# BackendRuntime enum test
# ---------------------------------------------------------------------------


class TestBackendRuntimeEnum:
    def test_nvidia_executor_in_enum(self):
        from runtime.core.models import BackendRuntime

        assert hasattr(BackendRuntime, "NVIDIA_EXECUTOR")
        assert BackendRuntime.NVIDIA_EXECUTOR.value == "nvidia_executor"


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
