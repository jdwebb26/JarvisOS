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


def post_webhook(url: str, content: str) -> dict[str, Any]:
    if not url.startswith("https://discord.com/api/webhooks/"):
        return {"ok": False, "reason": "missing_or_invalid_webhook_url"}
    payload = json.dumps({"content": content[:1900]}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"ok": True, "http_status": resp.status}
    except urllib.error.HTTPError as e:
        return {"ok": False, "http_status": e.code, "reason": e.reason}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def load_webhook_url(env_var: str, root: Path) -> str:
    """Load webhook URL from env var, falling back to secrets.env / .env files."""
    url = os.environ.get(env_var, "").strip()
    if url:
        return url
    for env_path in [
        root.parent.parent / ".openclaw" / "secrets.env",
        root.parent.parent / ".openclaw" / ".env",
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
