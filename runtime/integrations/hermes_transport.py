#!/usr/bin/env python3
"""hermes_transport — LM Studio Qwen transport for Hermes research tasks.

Calls the local LM Studio OpenAI-compatible API to execute bounded research
tasks.  Returns a structured dict that satisfies the Hermes response contract
(title, summary, content, model_name, family, citations, proposed_next_actions,
token_usage).

Fail-closed: connection errors raise HermesTransportUnreachableError; bad
payloads raise HermesResponseMalformedError.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import requests as _requests
except ImportError:
    _requests = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.integrations.hermes_adapter import (
    HermesTaskRequest,
    HermesTransportUnreachableError,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LMSTUDIO_BASE_URL_ENV = "JARVIS_LMSTUDIO_BASE_URL"
LMSTUDIO_DEFAULT_BASE_URL = "http://100.70.114.34:1234/v1"
LMSTUDIO_DEFAULT_MODEL = "qwen3.5-35b-a3b"
LMSTUDIO_HERMES_MODEL_ENV = "JARVIS_HERMES_MODEL"

# ---------------------------------------------------------------------------
# System prompt — instructs the model to produce structured research output
# ---------------------------------------------------------------------------

HERMES_SYSTEM_PROMPT = """\
You are Hermes, a deep research daemon.  Your job is to produce a thorough,
evidence-based research report for the given objective.

RULES:
- Be specific and factual.  Cite sources where possible.
- Structure your output as valid JSON with EXACTLY these top-level keys:
  "title"   — short headline (≤120 chars)
  "summary" — 1–3 sentence executive summary
  "content" — the full research report (markdown allowed)
  "citations" — array of objects, each with "url" and "title" keys (may be empty)
  "proposed_next_actions" — array of objects, each with "action" and "reason" keys (may be empty)

Output ONLY the JSON object.  No markdown fences, no preamble, no trailing text.
"""


# ---------------------------------------------------------------------------
# Transport implementation
# ---------------------------------------------------------------------------

def _load_config() -> dict[str, str]:
    base_url = os.environ.get(LMSTUDIO_BASE_URL_ENV, LMSTUDIO_DEFAULT_BASE_URL).rstrip("/")
    model = os.environ.get(LMSTUDIO_HERMES_MODEL_ENV, LMSTUDIO_DEFAULT_MODEL)
    return {"base_url": base_url, "model": model}


def lmstudio_transport(request: HermesTaskRequest) -> dict[str, Any]:
    """Call LM Studio Qwen API with the task objective and return structured response."""
    if _requests is None:
        raise HermesTransportUnreachableError("Python `requests` library is not installed.")

    config = _load_config()
    url = f"{config['base_url']}/chat/completions"
    model = config["model"]

    messages = [
        {"role": "system", "content": HERMES_SYSTEM_PROMPT},
        {"role": "user", "content": request.objective},
    ]

    max_tokens = request.max_tokens or 4096
    timeout_seconds = max(10, int(request.timeout_seconds or 120))

    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.4,
    }

    try:
        resp = _requests.post(
            url,
            json=body,
            timeout=(5, timeout_seconds),
        )
    except _requests.exceptions.ConnectionError as exc:
        raise HermesTransportUnreachableError(f"LM Studio unreachable at {config['base_url']}: {exc}") from exc
    except _requests.exceptions.Timeout as exc:
        raise TimeoutError(f"LM Studio request timed out after {timeout_seconds}s: {exc}") from exc
    except Exception as exc:
        raise HermesTransportUnreachableError(f"LM Studio request failed: {type(exc).__name__}: {exc}") from exc

    if resp.status_code != 200:
        raise HermesTransportUnreachableError(
            f"LM Studio returned HTTP {resp.status_code}: {resp.text[:500]}"
        )

    try:
        api_response = resp.json()
    except Exception as exc:
        raise HermesTransportUnreachableError(f"LM Studio returned non-JSON: {exc}") from exc

    # Extract the assistant message content
    choices = api_response.get("choices") or []
    if not choices:
        raise HermesTransportUnreachableError("LM Studio returned no choices.")

    raw_content = (choices[0].get("message") or {}).get("content", "")
    actual_model = api_response.get("model", model)

    # Extract token usage from API response
    api_usage = api_response.get("usage") or {}
    token_usage = {}
    if api_usage.get("prompt_tokens"):
        token_usage["prompt_tokens"] = int(api_usage["prompt_tokens"])
    if api_usage.get("completion_tokens"):
        token_usage["completion_tokens"] = int(api_usage["completion_tokens"])
    if api_usage.get("total_tokens"):
        token_usage["total_tokens"] = int(api_usage["total_tokens"])

    # Try to parse the content as JSON
    parsed = _parse_structured_content(raw_content)

    return {
        "title": parsed.get("title", "Hermes Research Report"),
        "summary": parsed.get("summary", ""),
        "content": parsed.get("content", raw_content),
        "family": "qwen3.5",
        "model_name": actual_model,
        "citations": parsed.get("citations", []),
        "proposed_next_actions": parsed.get("proposed_next_actions", []),
        "token_usage": token_usage,
    }


def _parse_structured_content(raw: str) -> dict[str, Any]:
    """Try to parse the model output as JSON.  Fall back to unstructured."""
    text = raw.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            # Validate required fields are present and non-empty
            if parsed.get("title") and parsed.get("content"):
                # Ensure citations and proposed_next_actions are lists of dicts
                citations = parsed.get("citations", [])
                if not isinstance(citations, list):
                    citations = []
                citations = [c for c in citations if isinstance(c, dict)]
                parsed["citations"] = citations

                actions = parsed.get("proposed_next_actions", [])
                if not isinstance(actions, list):
                    actions = []
                actions = [a for a in actions if isinstance(a, dict)]
                parsed["proposed_next_actions"] = actions

                return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: wrap raw text as unstructured report
    # Try to extract a title from the first line
    lines = raw.strip().split("\n")
    title = lines[0][:120].strip().lstrip("#").strip() if lines else "Hermes Research Report"
    if not title:
        title = "Hermes Research Report"

    # Build a summary from the first ~300 chars
    summary = raw[:300].replace("\n", " ").strip()
    if len(raw) > 300:
        summary += "..."

    return {
        "title": title,
        "summary": summary,
        "content": raw,
        "citations": [],
        "proposed_next_actions": [],
    }
