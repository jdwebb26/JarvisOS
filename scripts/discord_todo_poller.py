#!/usr/bin/env python3
"""discord_todo_poller — poll Discord #todo for task messages.

Fetches human messages from the #todo channel via Discord REST API,
filters out bot messages, and forwards each new message to submit_todo()
for direct task creation (no Jarvis turn).

Usage:
    python3 scripts/discord_todo_poller.py --once          # single poll
    python3 scripts/discord_todo_poller.py --interval 120  # poll every 2m
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TODO_CHANNEL_ID = "1471188572932673549"
BOT_USER_ID = "1469920721378480192"  # Jarvis bot

TAG = "discord_todo_poller"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _state_path() -> Path:
    d = ROOT / "state" / "discord_todo_poller"
    d.mkdir(parents=True, exist_ok=True)
    return d / "poller_state.json"


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_message_id": None, "processed_message_ids": []}


def _save_state(state: dict[str, Any]) -> None:
    state["processed_message_ids"] = state.get("processed_message_ids", [])[-200:]
    _state_path().write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Discord REST API
# ---------------------------------------------------------------------------

def _discord_request(path: str, bot_token: str) -> Any:
    url = f"https://discord.com/api/v10{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bot {bot_token}",
        "User-Agent": "OpenClaw-TodoPoller/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace") if exc.fp else ""
        print(f"[{TAG}] HTTP {exc.code}: {body[:200]}", flush=True)
        return None
    except Exception as exc:
        print(f"[{TAG}] request error: {exc}", flush=True)
        return None


def fetch_recent_messages(bot_token: str, after: str | None = None, limit: int = 20) -> list[dict]:
    path = f"/channels/{TODO_CHANNEL_ID}/messages?limit={limit}"
    if after:
        path += f"&after={after}"
    result = _discord_request(path, bot_token)
    return result if isinstance(result, list) else []


# ---------------------------------------------------------------------------
# Core poll logic
# ---------------------------------------------------------------------------

def poll_once(bot_token: str, verbose: bool = False) -> dict[str, Any]:
    from scripts.todo_intake import submit_todo

    state = _load_state()
    last_id = state.get("last_message_id")
    processed_ids = set(state.get("processed_message_ids", []))

    messages = fetch_recent_messages(bot_token, after=last_id)
    if not messages:
        if verbose:
            print(f"[{TAG}] no new messages", flush=True)
        return {"ok": True, "new_messages": 0, "processed": 0}

    # Discord returns newest first — reverse to process oldest first
    messages.sort(key=lambda m: m["id"])

    results: list[dict[str, Any]] = []
    for msg in messages:
        msg_id = msg["id"]

        # Skip already-processed
        if msg_id in processed_ids:
            continue

        # Skip bot messages
        author = msg.get("author", {})
        if author.get("bot", False) or author.get("id") == BOT_USER_ID:
            processed_ids.add(msg_id)
            continue

        content = (msg.get("content") or "").strip()
        if not content:
            processed_ids.add(msg_id)
            continue

        username = author.get("username", "unknown")

        if verbose:
            print(f"[{TAG}] processing: {msg_id} by {username}: {content[:60]}", flush=True)

        try:
            result = submit_todo(
                content,
                user=f"discord:{username}",
                lane="jarvis",
                channel="todo",
                message_id=f"discord:{msg_id}",
                root=ROOT,
            )
            results.append({
                "msg_id": msg_id,
                "username": username,
                "content": content[:80],
                "task_created": result.get("task_created", False),
                "task_id": result.get("task_id", ""),
            })
            if verbose:
                tid = result.get("task_id", "?")
                created = result.get("task_created", False)
                print(f"[{TAG}] -> task_created={created} task_id={tid}", flush=True)
        except Exception as exc:
            print(f"[{TAG}] submit_todo failed for {msg_id}: {exc}", flush=True)
            results.append({
                "msg_id": msg_id,
                "username": username,
                "error": str(exc),
            })

        processed_ids.add(msg_id)

    # Update state
    if messages:
        state["last_message_id"] = messages[-1]["id"]
    state["processed_message_ids"] = list(processed_ids)
    _save_state(state)

    return {
        "ok": True,
        "new_messages": len(messages),
        "processed": len(results),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Token loading
# ---------------------------------------------------------------------------

def _load_bot_token() -> str:
    for env_file in [
        Path.home() / ".openclaw" / "secrets.env",
        ROOT / ".env",
        ROOT.parent / ".env",
    ]:
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("DISCORD_BOT_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("DISCORD_BOT_TOKEN not found in secrets.env")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Poll #todo for task messages")
    parser.add_argument("--once", action="store_true", help="Run a single poll cycle and exit")
    parser.add_argument("--interval", type=int, default=120, help="Poll interval in seconds (default 120)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    bot_token = _load_bot_token()

    if args.once:
        result = poll_once(bot_token, verbose=True)
        print(json.dumps(result, indent=2))
        return 0

    print(f"[{TAG}] polling every {args.interval}s", flush=True)
    while True:
        try:
            poll_once(bot_token, verbose=args.verbose)
        except Exception as exc:
            print(f"[{TAG}] poll error: {exc}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
