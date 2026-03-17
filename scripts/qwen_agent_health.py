#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core import qwen_agent_smoke


def _strip(text: str) -> str:
    return qwen_agent_smoke._strip_think_blocks(text)


def _summarize(agent_response: list[Any]) -> list[str]:
    last_answer: str | None = None

    def _consume(payload: Any) -> None:
        nonlocal last_answer
        if isinstance(payload, dict) and payload.get("role") == "assistant":
            content = _strip(str(payload.get("content") or ""))
            if content:
                last_answer = content
        elif isinstance(payload, str):
            trimmed = _strip(payload)
            if trimmed:
                last_answer = trimmed

    for chunk in agent_response:
        if isinstance(chunk, list):
            for entry in chunk:
                _consume(entry)
        else:
            _consume(chunk)

    return [last_answer] if last_answer else []


def _build_bot() -> Any:
    if qwen_agent_smoke.QWEN_AGENT_IMPORT_ERROR:
        raise RuntimeError(
            f"Qwen-Agent import failed: {qwen_agent_smoke.QWEN_AGENT_IMPORT_ERROR}. "
            "Install via `pip install -U qwen-agent json5`."
        )
    return qwen_agent_smoke.build_bot()


def main() -> int:
    parser = argparse.ArgumentParser(description="Qwen-Agent health probe")
    parser.add_argument(
        "--prompt",
        type=str,
        default="Please respond with 'pong' if you can read this.",
        help="Prompt to send to the Qwen-Agent smoke runner",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument(
        "--state",
        action="store_true",
        help="Include exported model/server/flags state in the report",
    )
    args = parser.parse_args()

    try:
        bot = _build_bot()
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 1

    payload = {"prompt": args.prompt, "assistant": "", "chunks": []}

    try:
        for chunk in bot.run(messages=[{"role": "user", "content": args.prompt}]):
            payload["chunks"].append(chunk)
    except Exception as exc:
        payload["error"] = str(exc)
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 2
        print(f"RUN ERROR: {exc}")
        return 2

    answers = _summarize(payload["chunks"])
    payload["assistant"] = "\n".join(answers) or "(no assistant text)"

    if args.state:
        payload["state"] = {
            "workspace": str(qwen_agent_smoke.WORKSPACE),
            "model_server": qwen_agent_smoke.MODEL_SERVER,
            "model": qwen_agent_smoke.MODEL_NAME,
            "enable_thinking": qwen_agent_smoke.ENABLE_THINKING,
            "use_raw_api": qwen_agent_smoke.USE_RAW_API,
            "thought_in_content": qwen_agent_smoke.THOUGHT_IN_CONTENT,
        }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("Qwen-Agent health probe")
        print("Workspace      :", qwen_agent_smoke.WORKSPACE)
        print("Model server   :", qwen_agent_smoke.MODEL_SERVER)
        print("Model          :", qwen_agent_smoke.MODEL_NAME)
        print("Thinking       :", "on" if qwen_agent_smoke.ENABLE_THINKING else "off")
        print("Raw API        :", "on" if qwen_agent_smoke.USE_RAW_API else "off")
        print("Thought in text:", "yes" if qwen_agent_smoke.THOUGHT_IN_CONTENT else "no")
        print()
        print("Prompt:", args.prompt)
        print()
        print("Assistant output:")
        print(payload["assistant"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
