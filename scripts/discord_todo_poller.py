#!/usr/bin/env python3
"""discord_todo_poller — poll Discord #todo for task messages.

Fetches human messages from the #todo channel via Discord REST API,
filters out bot/webhook/system messages and noise, and forwards each
new message to submit_todo() for direct task creation.

First-run safety: if no state exists, seeds last_message_id to the
newest channel message without processing anything. Use --backfill
to explicitly ingest historical messages.

Usage:
    python3 scripts/discord_todo_poller.py --once          # single poll
    python3 scripts/discord_todo_poller.py --dry-run       # show what would be ingested
    python3 scripts/discord_todo_poller.py --interval 120  # poll every 2m
    python3 scripts/discord_todo_poller.py --backfill 5    # ingest last 5 human msgs
"""
from __future__ import annotations

import argparse
import json
import re
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

# Discord message types — only DEFAULT (0) and REPLY (19) are real user text.
_USER_MESSAGE_TYPES = {0, 19}

# Patterns that should not become tasks.
_NOISE_RE = re.compile(
    r"^("
    r"/\w"            # slash commands
    r"|https?://\S+$" # bare URL with nothing else
    r"|<:\w+:\d+>$"   # single custom emoji
    r"|\W{0,3}$"      # <=3 non-word chars (reactions, punctuation)
    r")",
    re.IGNORECASE,
)


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
    state["processed_message_ids"] = state.get("processed_message_ids", [])[-500:]
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
# Message filtering
# ---------------------------------------------------------------------------

def is_eligible_message(msg: dict) -> tuple[bool, str]:
    """Return (eligible, reason) for a Discord message.

    Only DEFAULT (0) and REPLY (19) messages from non-bot human users
    with meaningful text content are eligible.
    """
    # System messages (joins, pins, boosts, etc.)
    msg_type = msg.get("type", 0)
    if msg_type not in _USER_MESSAGE_TYPES:
        return False, f"system_message_type_{msg_type}"

    # Bot or webhook
    author = msg.get("author", {})
    if author.get("bot", False):
        return False, "bot"
    if msg.get("webhook_id"):
        return False, "webhook"

    # Known bot user ID
    if author.get("id") == BOT_USER_ID:
        return False, "jarvis_bot"

    # Empty content
    content = (msg.get("content") or "").strip()
    if not content:
        return False, "empty"

    # Noise patterns
    if _NOISE_RE.match(content):
        return False, "noise"

    return True, "ok"


# ---------------------------------------------------------------------------
# Task-level deduplication by source_message_id
# ---------------------------------------------------------------------------

def _task_exists_for_message_id(message_id: str) -> bool:
    """Check if a task with this source_message_id already exists."""
    tasks_dir = ROOT / "state" / "tasks"
    if not tasks_dir.exists():
        return False
    for p in tasks_dir.glob("task_*.json"):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
            if t.get("source_message_id") == message_id:
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# First-run seed
# ---------------------------------------------------------------------------

def _seed_state(bot_token: str) -> dict[str, Any]:
    """Seed state to newest channel message without processing anything."""
    messages = fetch_recent_messages(bot_token, limit=1)
    if messages:
        newest_id = messages[0]["id"]
        print(f"[{TAG}] first run: seeding last_message_id={newest_id} (no backfill)", flush=True)
        state = {"last_message_id": newest_id, "processed_message_ids": []}
    else:
        print(f"[{TAG}] first run: channel empty, seeding with no cursor", flush=True)
        state = {"last_message_id": "0", "processed_message_ids": []}
    _save_state(state)
    return state


# ---------------------------------------------------------------------------
# Core poll logic
# ---------------------------------------------------------------------------

def poll_once(
    bot_token: str,
    *,
    verbose: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    state = _load_state()
    last_id = state.get("last_message_id")

    # First-run safety: seed to newest message, do not backfill.
    if last_id is None:
        state = _seed_state(bot_token)
        return {"ok": True, "new_messages": 0, "processed": 0, "seeded": True}

    processed_ids = set(state.get("processed_message_ids", []))

    messages = fetch_recent_messages(bot_token, after=last_id)
    if not messages:
        if verbose:
            print(f"[{TAG}] no new messages", flush=True)
        return {"ok": True, "new_messages": 0, "processed": 0}

    # Discord returns newest first — reverse to process oldest first
    messages.sort(key=lambda m: m["id"])

    if dry_run:
        # Lazy import only when needed
        from scripts.todo_intake import submit_todo  # noqa: F401 — validates import

    results: list[dict[str, Any]] = []
    for msg in messages:
        msg_id = msg["id"]

        # Skip already-processed
        if msg_id in processed_ids:
            continue

        # Eligibility filter
        eligible, reason = is_eligible_message(msg)
        if not eligible:
            if verbose:
                print(f"[{TAG}] skip {msg_id}: {reason}", flush=True)
            processed_ids.add(msg_id)
            continue

        content = msg["content"].strip()
        username = msg.get("author", {}).get("username", "unknown")
        discord_msg_id = f"discord:{msg_id}"

        # Task-level dedup
        if _task_exists_for_message_id(discord_msg_id):
            if verbose:
                print(f"[{TAG}] skip {msg_id}: task already exists for this message", flush=True)
            processed_ids.add(msg_id)
            continue

        if dry_run:
            print(f"[{TAG}] WOULD ingest: {msg_id} by {username}: {content[:60]}", flush=True)
            results.append({
                "msg_id": msg_id,
                "username": username,
                "content": content[:80],
                "dry_run": True,
            })
            continue

        if verbose:
            print(f"[{TAG}] processing: {msg_id} by {username}: {content[:60]}", flush=True)

        try:
            from scripts.todo_intake import submit_todo

            result = submit_todo(
                content,
                user=f"discord:{username}",
                lane="jarvis",
                channel="todo",
                message_id=discord_msg_id,
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

    # Update state (skip on dry_run so it can be re-run)
    if not dry_run:
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


def backfill(bot_token: str, count: int = 5) -> dict[str, Any]:
    """Explicitly ingest the last N human messages from #todo.

    Resets the cursor and processes the specified count of eligible messages.
    """
    from scripts.todo_intake import submit_todo

    messages = fetch_recent_messages(bot_token, limit=min(count * 3, 50))
    if not messages:
        return {"ok": True, "processed": 0}

    messages.sort(key=lambda m: m["id"])

    state = _load_state()
    processed_ids = set(state.get("processed_message_ids", []))

    results: list[dict[str, Any]] = []
    for msg in messages:
        if len(results) >= count:
            break
        msg_id = msg["id"]
        if msg_id in processed_ids:
            continue

        eligible, reason = is_eligible_message(msg)
        if not eligible:
            processed_ids.add(msg_id)
            continue

        content = msg["content"].strip()
        username = msg.get("author", {}).get("username", "unknown")
        discord_msg_id = f"discord:{msg_id}"

        if _task_exists_for_message_id(discord_msg_id):
            processed_ids.add(msg_id)
            continue

        print(f"[{TAG}] backfill: {msg_id} by {username}: {content[:60]}", flush=True)

        try:
            result = submit_todo(
                content,
                user=f"discord:{username}",
                lane="jarvis",
                channel="todo",
                message_id=discord_msg_id,
                root=ROOT,
            )
            results.append({
                "msg_id": msg_id,
                "username": username,
                "content": content[:80],
                "task_created": result.get("task_created", False),
                "task_id": result.get("task_id", ""),
            })
        except Exception as exc:
            print(f"[{TAG}] backfill error {msg_id}: {exc}", flush=True)
            results.append({"msg_id": msg_id, "error": str(exc)})

        processed_ids.add(msg_id)

    # Advance cursor to newest fetched message
    if messages:
        state["last_message_id"] = messages[-1]["id"]
    state["processed_message_ids"] = list(processed_ids)
    _save_state(state)

    return {"ok": True, "processed": len(results), "results": results}


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
    parser.add_argument("--once", action="store_true", help="Single poll cycle")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be ingested without creating tasks")
    parser.add_argument("--backfill", type=int, metavar="N",
                        help="Explicitly ingest last N human messages")
    parser.add_argument("--interval", type=int, default=120,
                        help="Poll interval in seconds (default 120)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    bot_token = _load_bot_token()

    if args.backfill is not None:
        result = backfill(bot_token, count=args.backfill)
        print(json.dumps(result, indent=2))
        return 0

    if args.dry_run:
        result = poll_once(bot_token, verbose=True, dry_run=True)
        print(json.dumps(result, indent=2))
        return 0

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
