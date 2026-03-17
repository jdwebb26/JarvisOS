#!/usr/bin/env python3
"""nvidia_executor — Python-track adapter for NVIDIA's OpenAI-compatible API.

Executes chat completion requests against https://integrate.api.nvidia.com/v1
(or NVIDIA_API_BASE_URL override) using the NVIDIA_API_KEY secret.

Fail-closed: missing key or API errors produce a structured error result and
never silently fall through.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

try:
    import requests as _requests
except Exception:
    _requests = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.execution_contracts import (
    record_backend_execution_request,
    record_backend_execution_result,
)
from runtime.core.models import new_id, now_iso

# ---------------------------------------------------------------------------
# Configuration — mirrors the pattern used by qwen_candidate_writer et al.
# ---------------------------------------------------------------------------

NVIDIA_BACKEND_ID = "nvidia_executor"

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "moonshotai/kimi-k2.5"
DEFAULT_TIMEOUT = (10, 120)  # (connect, read) seconds


class NvidiaConfigError(Exception):
    """Raised when the adapter cannot be configured (e.g. missing API key)."""


class NvidiaAPIError(Exception):
    """Raised when the NVIDIA API returns an error or is unreachable."""

    def __init__(self, message: str, *, status_code: int | None = None, response_body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_nvidia_config(*, override: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the runtime config dict from env vars + optional overrides.

    Returns dict with keys: base_url, api_key, model, timeout.
    Raises NvidiaConfigError if NVIDIA_API_KEY is not set.
    """
    ov = dict(override or {})
    api_key = str(ov.get("api_key") or os.environ.get("NVIDIA_API_KEY", "")).strip()
    if not api_key:
        raise NvidiaConfigError(
            "NVIDIA_API_KEY is not set. "
            "Set it in the environment or pass override={'api_key': ...}."
        )
    base_url = str(
        ov.get("base_url") or os.environ.get("NVIDIA_API_BASE_URL", DEFAULT_BASE_URL)
    ).strip().rstrip("/")
    model = str(ov.get("model") or os.environ.get("NVIDIA_MODEL", DEFAULT_MODEL)).strip()
    timeout_raw = ov.get("timeout")
    if timeout_raw is None:
        timeout = DEFAULT_TIMEOUT
    elif isinstance(timeout_raw, (list, tuple)) and len(timeout_raw) == 2:
        timeout = (float(timeout_raw[0]), float(timeout_raw[1]))
    else:
        timeout = (10, float(timeout_raw))

    return {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "timeout": timeout,
    }


# ---------------------------------------------------------------------------
# Core chat completion call
# ---------------------------------------------------------------------------

def nvidia_chat_completion(
    messages: list[dict[str, str]],
    *,
    config: dict[str, Any] | None = None,
    override: dict[str, Any] | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Send a chat completion request to the NVIDIA API.

    Args:
        messages: OpenAI-format message list.
        config: Pre-built config dict (from load_nvidia_config). If None, built from env.
        override: Passed to load_nvidia_config when config is None.
        temperature: Sampling temperature.
        max_tokens: Max tokens in the completion.

    Returns:
        The full parsed JSON response from the API.

    Raises:
        NvidiaConfigError: If NVIDIA_API_KEY is missing.
        NvidiaAPIError: If the API returns an error or is unreachable.
        RuntimeError: If the requests library is not available.
    """
    if _requests is None:
        raise RuntimeError("The 'requests' library is required for nvidia_executor but is not installed.")

    cfg = config or load_nvidia_config(override=override)

    url = f"{cfg['base_url']}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}",
    }
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        resp = _requests.post(url, headers=headers, json=payload, timeout=cfg["timeout"])
        resp.raise_for_status()
        return resp.json()
    except _requests.Timeout as exc:
        raise NvidiaAPIError(f"NVIDIA API timeout: {exc}") from exc
    except _requests.HTTPError as exc:
        body = ""
        if getattr(exc, "response", None) is not None:
            body = exc.response.text or ""
        raise NvidiaAPIError(
            f"NVIDIA API HTTP error: {exc}",
            status_code=getattr(exc.response, "status_code", None),
            response_body=body,
        ) from exc
    except _requests.ConnectionError as exc:
        raise NvidiaAPIError(f"NVIDIA API connection error: {exc}") from exc
    except _requests.RequestException as exc:
        raise NvidiaAPIError(f"NVIDIA API request error: {exc}") from exc


def extract_content(response: dict[str, Any]) -> str:
    """Extract the assistant content string from a chat completion response."""
    choices = response.get("choices") or []
    if not choices:
        return ""
    return str((choices[0].get("message") or {}).get("content") or "")


def extract_usage(response: dict[str, Any]) -> dict[str, int]:
    """Extract token usage from a chat completion response."""
    usage = response.get("usage") or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


# ---------------------------------------------------------------------------
# Provenance-tracked execution entry point
# ---------------------------------------------------------------------------

def execute_nvidia_chat(
    *,
    task_id: str,
    actor: str,
    lane: str,
    messages: list[dict[str, str]],
    request_kind: str = "chat_completion",
    routing_decision_id: str | None = None,
    override: dict[str, Any] | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    root: Path | None = None,
) -> dict[str, Any]:
    """Execute a chat completion against NVIDIA API with full provenance tracking.

    Records a BackendExecutionRequest before the call and a
    BackendExecutionResult after (success or failure).

    Returns a dict with keys: status, content, usage, request_id, result_id, error.
    """
    # Load config early so we fail-closed before recording the request.
    try:
        cfg = load_nvidia_config(override=override)
    except NvidiaConfigError as exc:
        return {
            "status": "config_error",
            "content": "",
            "usage": {},
            "request_id": None,
            "result_id": None,
            "error": str(exc),
        }

    backend_run_id = new_id("nvrun")
    req_record = record_backend_execution_request(
        task_id=task_id,
        actor=actor,
        lane=lane,
        request_kind=request_kind,
        execution_backend=NVIDIA_BACKEND_ID,
        provider_id="nvidia",
        model_name=cfg["model"],
        routing_decision_id=routing_decision_id,
        backend_run_id=backend_run_id,
        input_summary=f"nvidia chat_completion ({len(messages)} messages)",
        status="pending",
        root=root,
    )

    try:
        response = nvidia_chat_completion(
            messages,
            config=cfg,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except (NvidiaAPIError, RuntimeError) as exc:
        record_backend_execution_result(
            backend_execution_request_id=req_record.backend_execution_request_id,
            task_id=task_id,
            actor=actor,
            lane=lane,
            request_kind=request_kind,
            execution_backend=NVIDIA_BACKEND_ID,
            provider_id="nvidia",
            model_name=cfg["model"],
            status="error",
            backend_run_id=backend_run_id,
            outcome_summary="NVIDIA API call failed",
            error=str(exc),
            metadata={
                "error_type": type(exc).__name__,
                "status_code": getattr(exc, "status_code", None),
            },
            root=root,
        )
        return {
            "status": "error",
            "content": "",
            "usage": {},
            "request_id": req_record.backend_execution_request_id,
            "result_id": None,
            "error": str(exc),
        }

    content = extract_content(response)
    usage = extract_usage(response)

    res_record = record_backend_execution_result(
        backend_execution_request_id=req_record.backend_execution_request_id,
        task_id=task_id,
        actor=actor,
        lane=lane,
        request_kind=request_kind,
        execution_backend=NVIDIA_BACKEND_ID,
        provider_id="nvidia",
        model_name=cfg["model"],
        status="completed",
        backend_run_id=backend_run_id,
        outcome_summary=f"nvidia chat_completion ok ({usage.get('total_tokens', 0)} tokens)",
        metadata={
            "usage": usage,
            "model": cfg["model"],
            "response_id": response.get("id"),
        },
        root=root,
    )

    return {
        "status": "completed",
        "content": content,
        "usage": usage,
        "request_id": req_record.backend_execution_request_id,
        "result_id": res_record.backend_execution_result_id,
        "error": "",
    }
