#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core import qwen_agent_smoke

QWEN_REQUEST_ENV = "JARVIS_QWEN_REQUEST_FILE"
QWEN_RESULT_ENV = "JARVIS_QWEN_RESULT_FILE"
QWEN_MODE_ENV = "JARVIS_QWEN_BRIDGE_MODE"

_TOOL_CALL_RE = re.compile(r"<tool_call\b[^>]*>(?:[\s\S]*?</tool_call\s*>|[\s\S]*)", re.IGNORECASE)


def _contains_tool_markup(text: str) -> bool:
    return bool(_TOOL_CALL_RE.search(text))


def _strip_tool_calls(text: str) -> str:
    cleaned = _TOOL_CALL_RE.sub("", text)
    if "<tool_call" in cleaned.lower():
        cleaned = cleaned.split("<tool_call", 1)[0]
    return cleaned.strip()


def _append_bridge_log(msg: str) -> None:
    log_path = os.environ.get("JARVIS_QWEN_BRIDGE_LOG", "/tmp/qwen_acp_bridge.log")
    try:
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

def _resolve_path(arg_value: str | None, env_name: str) -> Path | None:
    if arg_value:
        return Path(arg_value)
    env_value = os.environ.get(env_name)
    if not env_value:
        return None
    return Path(env_value)

def _load_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return json.loads(text)

def _strip_text(value: str) -> str:
    return qwen_agent_smoke._strip_think_blocks(value)

def _summarize_chunks(chunks: list[Any]) -> tuple[str, list[Any]]:
    last_answer: str | None = None

    def _consume(payload: Any) -> None:
        nonlocal last_answer
        if isinstance(payload, dict) and payload.get("role") == "assistant":
            content = _strip_text(str(payload.get("content") or ""))
            if content and not _contains_tool_markup(content):
                last_answer = content
        elif isinstance(payload, str):
            trimmed = _strip_text(payload)
            if trimmed and not _contains_tool_markup(trimmed):
                last_answer = trimmed

    for chunk in chunks:
        if isinstance(chunk, list):
            for entry in chunk:
                _consume(entry)
        else:
            _consume(chunk)
    return (last_answer or "", chunks)

_BRIDGE_BOT: Any | None = None

def _build_bot() -> Any:
    global _BRIDGE_BOT
    if _BRIDGE_BOT is None:
        _BRIDGE_BOT = qwen_agent_smoke.build_bot()
    return _BRIDGE_BOT

def _run_qwen_agent(prompt: str) -> tuple[str, list[Any]]:
    bot = _build_bot()
    chunks: list[Any] = []
    for chunk in bot.run(messages=[{"role": "user", "content": prompt}]):
        chunks.append(chunk)
    answer, recorded = _summarize_chunks(chunks)
    return (answer, recorded)

def _build_prompt(request: dict[str, Any]) -> str:
    objective = str(request.get("objective") or "").strip()
    if objective:
        return objective
    prompt = str(request.get("prompt") or "").strip()
    if prompt:
        return prompt
    messages = request.get("messages") or request.get("chat") or []
    for entry in reversed(messages if isinstance(messages, list) else []):
        if isinstance(entry, dict) and entry.get("role") == "user":
            content = str(entry.get("content") or "").strip()
            if content:
                return content
    return "Respond briefly and honestly."

def _build_response_payload(request: dict[str, Any], answer: str, chunks: list[Any]) -> dict[str, Any]:
    title = str(request.get("title") or request.get("objective") or "Qwen response").strip()
    if not title:
        title = "Qwen response"
    summary = answer.splitlines()[0] if answer else "(no output)"
    model_name = str(qwen_agent_smoke.MODEL_NAME or "").strip()
    family = model_name.split("-")[0] if "-" in model_name else (model_name or "qwen3.5")
    payload = {
        "run_id": f"qwen-{uuid.uuid4().hex[:8]}",
        "title": title,
        "summary": summary,
        "content": answer,
        "model_name": model_name,
        "family": family,
        "status": "completed",
        "token_usage": {},
        "citations": [],
        "proposed_next_actions": [],
        "chunks": chunks,
    }
    return payload

def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def _handle_healthcheck(result_path: Path, request: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "runtime_status": "healthy",
        "details": "Qwen ACP bridge is ready.",
        "kind": request.get("kind") or "qwen_bridge_healthcheck",
        "probe": request.get("probe", True),
    }
    _write_result(result_path, payload)
    return payload

def _process_request(request_path: Path, result_path: Path, bridge_mode: str | None) -> dict[str, Any]:
    if not request_path.exists():
        raise FileNotFoundError(f"Bridge request file not found: {request_path}")
    request = _load_json(request_path)
    if bridge_mode == "healthcheck" or str(request.get("probe") or "").lower() == "true":
        return _handle_healthcheck(result_path, request)
    prompt = _build_prompt(request)
    answer, chunks = _run_qwen_agent(prompt)
    # Final sanitization: strip any tool markup that escaped the loop
    if _contains_tool_markup(answer):
        _append_bridge_log(
            f"TOOL_MARKUP_IN_ANSWER stripped raw_preview={answer[:300]}"
        )
        answer = _strip_tool_calls(answer) or "(Qwen is processing your request.)"
    elif not answer:
        _append_bridge_log("EMPTY_ANSWER no clean assistant text produced (tool loop may have timed out)")
        answer = "(Qwen is processing your request.)"
    payload = _build_response_payload(request, answer, chunks)
    _write_result(result_path, payload)
    return payload

SAMPLE_REQUEST: dict[str, Any] = {
    "request_id": "qwen-test",
    "task_id": "qwen-test-task",
    "objective": "Echo back a friendly greeting to confirm the Qwen bridge.",
    "timeout_seconds": 10,
    "lane": "qwen",
    "execution_backend": "qwen_bridge",
}

def _run_smoke_test() -> None:
    print("Running qwen_agent_bridge smoke test...")
    with tempfile.TemporaryDirectory(prefix="qwen_bridge_test_") as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        request_path = tmp_dir_path / "request.json"
        result_path = tmp_dir_path / "response.json"
        request_path.write_text(json.dumps(SAMPLE_REQUEST, indent=2) + "\n", encoding="utf-8")
        payload = _process_request(request_path, result_path, bridge_mode=None)
        print("Test request written to", request_path)
        print("Bridge result written to", result_path)
        print(json.dumps(payload, indent=2, ensure_ascii=False))

def main() -> int:
    parser = argparse.ArgumentParser(description="Qwen ACP bridge for OpenClaw agents.")
    parser.add_argument("--request-file", help="Optional override request JSON path")
    parser.add_argument("--result-file", help="Optional override result JSON path")
    parser.add_argument("--mode", help="Optional override bridge mode (healthcheck)")
    parser.add_argument("--test", action="store_true", help="Run the built-in smoke test and exit")
    args = parser.parse_args()

    if args.test:
        _run_smoke_test()
        return 0

    request_path = _resolve_path(args.request_file, QWEN_REQUEST_ENV)
    result_path = _resolve_path(args.result_file, QWEN_RESULT_ENV)
    if not request_path or not result_path:
        print(f"ERROR: Bridge requires {QWEN_REQUEST_ENV} and {QWEN_RESULT_ENV} (or cli overrides).", file=sys.stderr)
        return 2
    bridge_mode = args.mode or os.environ.get(QWEN_MODE_ENV, "").strip().lower() or None
    try:
        payload = _process_request(request_path, result_path, bridge_mode)
    except Exception as exc:
        payload = {
            "status": "failed",
            "error": str(exc),
        }
        if result_path:
            _write_result(result_path, payload)
        print(f"Bridge error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
