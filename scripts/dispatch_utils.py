"""Shared utilities for Discord webhook dispatch scripts."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def load_sent(sent_log: Path) -> set[str]:
    if sent_log.exists():
        try:
            return set(json.loads(sent_log.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_sent(sent_log: Path, sent: set[str]) -> None:
    sent_log.parent.mkdir(parents=True, exist_ok=True)
    sent_log.write_text(json.dumps(sorted(sent), indent=2) + "\n", encoding="utf-8")


def post_webhook(url: str, content: "str | dict[str, Any]") -> dict[str, Any]:
    if not url.startswith("https://discord.com/api/webhooks/"):
        return {"ok": False, "reason": "missing_or_invalid_webhook_url"}
    # Accept either a plain string or a pre-shaped dict payload
    if isinstance(content, dict):
        body = content
    else:
        body = {"content": str(content)[:1900]}
    payload = json.dumps(body).encode("utf-8")
    # Append ?wait=true so Discord returns the created message (and gives 200 not 204)
    post_url = url if "?" in url else url + "?wait=true"
    req = urllib.request.Request(
        post_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Non-default User-Agent — Python-urllib/3.x is blocked by Cloudflare (error 1010)
            "User-Agent": "OpenClaw/1.0 (webhook-sender; +https://github.com/openclaw)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"ok": True, "http_status": resp.status}
    except urllib.error.HTTPError as e:
        return {"ok": False, "http_status": e.code, "reason": e.reason}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def send_bot_message(channel_id: str, content: str) -> dict[str, Any]:
    """Send a message to a Discord channel using the bot token (REST API).

    Use this when a webhook is unavailable or bound to the wrong channel.
    """
    bot_token = load_webhook_url("DISCORD_BOT_TOKEN", Path.home() / ".openclaw")
    if not bot_token:
        return {"ok": False, "reason": "DISCORD_BOT_TOKEN not found"}

    payload = json.dumps({"content": str(content)[:1900]}).encode("utf-8")
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=payload,
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "OpenClaw/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"ok": True, "http_status": resp.status}
    except urllib.error.HTTPError as e:
        return {"ok": False, "http_status": e.code, "reason": e.reason}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def load_webhook_url(env_var: str, root: Path) -> str:
    """Load webhook URL from env var, falling back to secrets.env / .env files.

    Search order:
    1. Shell environment variable
    2. ~/.openclaw/secrets.env
    3. ~/.openclaw/.env
    """
    url = os.environ.get(env_var, "").strip()
    if url:
        return url
    openclaw_root = Path.home() / ".openclaw"
    for env_path in [
        openclaw_root / "secrets.env",
        openclaw_root / ".env",
    ]:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(f"{env_var}="):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        if url:
            break
    return url
