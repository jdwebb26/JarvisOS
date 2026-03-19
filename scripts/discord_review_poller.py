#!/usr/bin/env python3
"""discord_review_poller — poll #review for approval commands and emoji reactions.

Uses the Discord REST API (no WebSocket Gateway) so it does not conflict
with the Node.js openclaw gateway's bot connection.

Supports two operator flows:
  1. **Text commands**: operator types ``approve apr_xxx`` or ``reject apr_xxx reason``
  2. **Emoji reactions**: operator adds ✅ (approve) or ❌ (reject) to an approval message

On match, calls POST /operator/approval on the inbound server (port 18790).

Usage:
    python3 scripts/discord_review_poller.py --once          # single poll
    python3 scripts/discord_review_poller.py --interval 30   # poll every 30s
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REVIEW_CHANNEL_ID = "1483132981177618482"

# Approval ID pattern: apr_ or qpt_ or pulse_ or promo_ followed by identifier chars
APPROVAL_ID_PATTERN = re.compile(r"\b(?:apr|qpt|pulse|promo)_[a-zA-Z0-9_-]{6,}\b")

# Text command patterns (case-insensitive)
# Matches Jarvis (apr_xxx), quant (qpt_xxx), Pulse (pulse_xxx), promotions (promo_xxx)
_ID_GROUP = r"((?:apr|qpt|pulse|promo)_[a-zA-Z0-9_-]+)"
APPROVE_PATTERN = re.compile(
    rf"^\s*(?:approve|approved|yes|lgtm|ship\s*it)\s+{_ID_GROUP}\s*(.*)?$",
    re.IGNORECASE,
)
REJECT_PATTERN = re.compile(
    rf"^\s*(?:reject|rejected|no|nack)\s+{_ID_GROUP}\s*(.*)?$",
    re.IGNORECASE,
)
RERUN_PATTERN = re.compile(
    rf"^\s*(?:rerun|rerun_paper|redo|continue_paper)\s+{_ID_GROUP}\s*(.*)?$",
    re.IGNORECASE,
)

# Emoji → decision mapping
APPROVE_EMOJIS = {"✅", "👍", "🟢", "white_check_mark", "thumbsup"}
REJECT_EMOJIS = {"❌", "👎", "🔴", "x", "thumbsdown"}


# ---------------------------------------------------------------------------
# State file — tracks last processed message to avoid re-processing
# ---------------------------------------------------------------------------

def _state_path() -> Path:
    d = ROOT / "state" / "discord_review_poller"
    d.mkdir(parents=True, exist_ok=True)
    return d / "poller_state.json"


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_message_id": None, "processed_message_ids": [], "processed_reactions": []}


def _save_state(state: dict[str, Any]) -> None:
    # Keep only last 200 processed IDs to prevent unbounded growth
    state["processed_message_ids"] = state.get("processed_message_ids", [])[-200:]
    state["processed_reactions"] = state.get("processed_reactions", [])[-200:]
    _state_path().write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Discord REST API helpers
# ---------------------------------------------------------------------------

def _discord_request(path: str, bot_token: str) -> Any:
    """GET request to Discord REST API."""
    url = f"https://discord.com/api/v10{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bot {bot_token}",
        "User-Agent": "OpenClaw-ReviewPoller/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace") if exc.fp else ""
        print(f"[discord_review_poller] HTTP {exc.code}: {body[:200]}", flush=True)
        return None
    except Exception as exc:
        print(f"[discord_review_poller] request error: {exc}", flush=True)
        return None


def fetch_recent_messages(bot_token: str, after: str | None = None, limit: int = 20) -> list[dict]:
    """Fetch recent messages from #review channel."""
    path = f"/channels/{REVIEW_CHANNEL_ID}/messages?limit={limit}"
    if after:
        path += f"&after={after}"
    result = _discord_request(path, bot_token)
    if isinstance(result, list):
        return result
    return []


def fetch_reactions(bot_token: str, message_id: str, emoji: str) -> list[dict]:
    """Fetch users who reacted with a specific emoji on a message."""
    encoded = urllib.request.quote(emoji, safe="")
    path = f"/channels/{REVIEW_CHANNEL_ID}/messages/{message_id}/reactions/{encoded}"
    result = _discord_request(path, bot_token)
    if isinstance(result, list):
        return result
    return []


# ---------------------------------------------------------------------------
# Gateway API call
# ---------------------------------------------------------------------------

def _load_gateway_token() -> str:
    """Load the gateway API token."""
    for env_file in [ROOT.parent / ".env", Path.home() / ".openclaw" / ".env"]:
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("OPENCLAW_GATEWAY_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"')
    # Try openclaw.json
    config = Path.home() / ".openclaw" / "openclaw.json"
    if config.exists():
        try:
            data = json.loads(config.read_text())
            return data["gateway"]["auth"]["token"]
        except (KeyError, json.JSONDecodeError):
            pass
    raise RuntimeError("No gateway token found")


def _handle_quant_approval(
    approval_ref: str,
    decision: str,
) -> dict[str, Any]:
    """Handle a quant lane paper/live trade approval locally.

    Quant approvals (qpt_xxx) are handled directly via the quant approval
    bridge, not through the Jarvis /operator/approval endpoint.

    Routes based on approval_type:
      - paper_trade → approve_paper_trade() → PAPER_QUEUED
      - live_trade  → approve_live_trade() (validates only, no state change)
    """
    try:
        from workspace.quant.shared.registries.approval_registry import get_approval
        approval = get_approval(ROOT, approval_ref)
        if approval is None:
            return {"ok": False, "error": f"quant approval {approval_ref} not found"}
        if decision == "approved":
            if approval.approval_type == "live_trade":
                from workspace.quant.shared.approval_bridge import approve_live_trade
                result = approve_live_trade(ROOT, approval.strategy_id, approval_ref=approval_ref)
                if result["error"]:
                    return {"ok": False, "error": result["error"]}
                return {"ok": True, "approval_id": approval_ref, "strategy_id": approval.strategy_id,
                        "decision": "approved", "approval_type": "live_trade"}
            else:
                from workspace.quant.shared.approval_bridge import approve_paper_trade
                result = approve_paper_trade(ROOT, approval.strategy_id, approval_ref=approval_ref)
                if result["error"]:
                    return {"ok": False, "error": result["error"]}
                return {"ok": True, "approval_id": approval_ref, "strategy_id": approval.strategy_id,
                        "decision": "approved", "strategy_state": result["strategy_state"]}
        elif decision == "rejected":
            from workspace.quant.shared.registries.approval_registry import revoke_approval
            revoke_approval(ROOT, approval_ref)
            return {"ok": True, "approval_id": approval_ref, "strategy_id": approval.strategy_id,
                    "decision": "rejected", "approval_type": approval.approval_type}
        else:
            return {"ok": False, "error": f"unsupported decision: {decision}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _handle_pulse_approval(
    approval_ref: str,
    decision: str,
) -> dict[str, Any]:
    """Handle a Pulse downstream proposal approval/rejection.

    pulse_xxx IDs are Pulse review proposals — approving releases a downstream
    packet into the target quant lane. Rejecting prevents release.
    """
    try:
        from workspace.quant.pulse.alert_lane import handle_pulse_review
        return handle_pulse_review(ROOT, approval_ref, decision)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _handle_promotion_approval(
    approval_ref: str,
    decision: str,
    reason: str = "",
) -> dict[str, Any]:
    """Handle a promotion review decision (promo_xxx IDs).

    Maps review poller decisions to handle_promotion_decision():
      approved    → "approved"    → PAPER_REVIEW → LIVE_QUEUED
      rejected    → "rejected"    → PAPER_REVIEW → PAPER_KILLED
      rerun_paper → "rerun_paper" → PAPER_REVIEW → ITERATE
    """
    try:
        from workspace.quant.executor.executor_lane import handle_promotion_decision
        return handle_promotion_decision(ROOT, approval_ref, decision, reason)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def call_approval_endpoint(
    approval_id: str,
    decision: str,
    actor: str = "operator",
    reason: str = "",
    port: int = 18790,
) -> dict[str, Any]:
    """Route approval to the correct handler.

    - pulse_xxx: Pulse proposal (handled locally via Pulse lane)
    - qpt_xxx: quant lane approval (handled locally)
    - promo_xxx: promotion review (handled locally via executor lane)
    - apr_xxx: Jarvis approval (handled via inbound server)
    """
    if approval_id.startswith("pulse_"):
        return _handle_pulse_approval(approval_id, decision)
    if approval_id.startswith("qpt_"):
        return _handle_quant_approval(approval_id, decision)
    if approval_id.startswith("promo_"):
        return _handle_promotion_approval(approval_id, decision, reason)

    token = _load_gateway_token()
    payload = json.dumps({
        "approval_id": approval_id,
        "decision": decision,
        "actor": actor,
        "reason": reason,
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/operator/approval",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace") if exc.fp else ""
        return {"ok": False, "error": f"HTTP {exc.code}: {body[:200]}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Discord webhook confirmation
# ---------------------------------------------------------------------------

def _post_review_confirmation(text: str) -> None:
    """Post a confirmation message to #review via bot token."""
    try:
        _scripts = ROOT / "scripts"
        if str(_scripts) not in sys.path:
            sys.path.insert(0, str(_scripts))
        from dispatch_utils import send_bot_message
        send_bot_message(REVIEW_CHANNEL_ID, text)
    except Exception as exc:
        print(f"[discord_review_poller] confirmation send failed: {exc}", flush=True)


def _format_approve_confirm(approval_id: str, result: dict, author: str) -> str:
    """Format approval confirmation with type-aware context."""
    atype = result.get("approval_type", "")
    sid = result.get("strategy_id", "")
    if atype == "live_trade":
        return (f"\u2705 **Live trade approved** `{approval_id}` (by {author})\n"
                f"Strategy `{sid}` ready for `execute-live {sid}`")
    if approval_id.startswith("promo_"):
        ns = result.get("new_state", "?")
        return (f"\u2705 **Promotion approved** `{approval_id}` (by {author})\n"
                f"Strategy `{sid}` \u2192 {ns}")
    ss = result.get("strategy_state", "")
    if ss:
        return f"\u2705 Approved `{approval_id}` (by {author}) \u2192 {ss}"
    return f"\u2705 Approved `{approval_id}` (by {author})"


def _format_reject_confirm(approval_id: str, result: dict, author: str, reason: str) -> str:
    """Format rejection confirmation with type-aware context."""
    atype = result.get("approval_type", "")
    sid = result.get("strategy_id", "")
    if atype == "live_trade":
        base = f"\u274c **Live trade rejected** `{approval_id}` (by {author})"
        if sid:
            base += f" | strategy `{sid}`"
        if reason:
            base += f"\n> {reason}"
        return base
    if approval_id.startswith("promo_"):
        ns = result.get("new_state", "?")
        base = f"\u274c **Promotion rejected** `{approval_id}` (by {author})"
        if sid:
            base += f" | `{sid}` \u2192 {ns}"
        if reason:
            base += f"\n> {reason}"
        return base
    if reason:
        return f"\u274c Rejected `{approval_id}` (by {author}): {reason}"
    return f"\u274c Rejected `{approval_id}` (by {author})"


# ---------------------------------------------------------------------------
# Process messages
# ---------------------------------------------------------------------------

def _process_text_command(msg: dict, state: dict) -> bool:
    """Check if message is an approve/reject text command. Returns True if processed."""
    msg_id = msg["id"]
    if msg_id in state.get("processed_message_ids", []):
        return False

    content = msg.get("content", "").strip()
    if not content:
        return False

    # Try approve pattern
    m = APPROVE_PATTERN.match(content)
    if m:
        approval_id = m.group(1)
        reason = (m.group(2) or "").strip()
        author = msg.get("author", {}).get("username", "operator")
        print(f"[discord_review_poller] text APPROVE {approval_id} by {author}", flush=True)
        result = call_approval_endpoint(approval_id, "approved", actor=f"operator:{author}", reason=reason)
        state.setdefault("processed_message_ids", []).append(msg_id)
        if result.get("ok"):
            _post_review_confirmation(_format_approve_confirm(approval_id, result, author))
        else:
            _post_review_confirmation(f"\u26a0\ufe0f Approval failed for `{approval_id}`: {result.get('error', 'unknown')}")
        return True

    # Try reject pattern
    m = REJECT_PATTERN.match(content)
    if m:
        approval_id = m.group(1)
        reason = (m.group(2) or "").strip()
        author = msg.get("author", {}).get("username", "operator")
        print(f"[discord_review_poller] text REJECT {approval_id} by {author}", flush=True)
        result = call_approval_endpoint(approval_id, "rejected", actor=f"operator:{author}", reason=reason)
        state.setdefault("processed_message_ids", []).append(msg_id)
        if result.get("ok"):
            _post_review_confirmation(_format_reject_confirm(approval_id, result, author, reason))
        else:
            _post_review_confirmation(f"\u26a0\ufe0f Rejection failed for `{approval_id}`: {result.get('error', 'unknown')}")
        return True

    # Try rerun pattern (promotion reviews only)
    m = RERUN_PATTERN.match(content)
    if m:
        approval_id = m.group(1)
        reason = (m.group(2) or "").strip()
        author = msg.get("author", {}).get("username", "operator")
        print(f"[discord_review_poller] text RERUN {approval_id} by {author}", flush=True)
        result = call_approval_endpoint(approval_id, "rerun_paper", actor=f"operator:{author}", reason=reason)
        state.setdefault("processed_message_ids", []).append(msg_id)
        if result.get("ok"):
            _post_review_confirmation(f"\U0001f504 Rerun `{approval_id}` (by {author}): {reason}" if reason else f"\U0001f504 Rerun `{approval_id}` (by {author})")
        else:
            _post_review_confirmation(f"\u26a0\ufe0f Rerun failed for `{approval_id}`: {result.get('error', 'unknown')}")
        return True

    return False


def _process_reactions(msg: dict, bot_token: str, state: dict) -> bool:
    """Check if message has approval emoji reactions. Returns True if processed."""
    msg_id = msg["id"]
    content = msg.get("content", "")

    # Only process messages that contain an approval ID
    approval_ids = APPROVAL_ID_PATTERN.findall(content)
    if not approval_ids:
        return False

    approval_id = approval_ids[0]  # Use the first approval_id found
    reactions = msg.get("reactions", [])
    if not reactions:
        return False

    for reaction in reactions:
        emoji_name = reaction.get("emoji", {}).get("name", "")
        reaction_key = f"{msg_id}:{emoji_name}"

        if reaction_key in state.get("processed_reactions", []):
            continue

        decision = None
        if emoji_name in APPROVE_EMOJIS or emoji_name == "\u2705":
            decision = "approved"
        elif emoji_name in REJECT_EMOJIS or emoji_name == "\u274c":
            decision = "rejected"

        if decision is None:
            continue

        # Fetch who reacted to get the actor name
        reactors = fetch_reactions(bot_token, msg_id, emoji_name)
        # Filter out bots
        human_reactors = [r for r in reactors if not r.get("bot", False)]
        if not human_reactors:
            continue

        actor_name = human_reactors[0].get("username", "operator")
        print(f"[discord_review_poller] emoji {emoji_name} -> {decision} {approval_id} by {actor_name}", flush=True)

        result = call_approval_endpoint(approval_id, decision, actor=f"operator:{actor_name}")
        state.setdefault("processed_reactions", []).append(reaction_key)

        if result.get("ok"):
            emoji_confirm = "\u2705" if decision == "approved" else "\u274c"
            _post_review_confirmation(f"{emoji_confirm} {decision.title()} `{approval_id}` (by {actor_name} via reaction)")
        else:
            _post_review_confirmation(f"\u26a0\ufe0f {decision.title()} failed for `{approval_id}`: {result.get('error', 'unknown')}")
        return True

    return False


def poll_once(bot_token: str, verbose: bool = False) -> dict[str, Any]:
    """Run a single poll cycle. Returns summary."""
    state = _load_state()
    messages = fetch_recent_messages(bot_token, after=state.get("last_message_id"), limit=20)
    if not messages:
        if verbose:
            print("[discord_review_poller] no new messages", flush=True)
        return {"ok": True, "new_messages": 0, "processed": 0}

    # Messages come newest-first from Discord API; process oldest first
    messages.sort(key=lambda m: m["id"])

    processed = 0
    for msg in messages:
        # Skip bot messages for text commands (but still check reactions on bot messages)
        is_bot = msg.get("author", {}).get("bot", False)

        if not is_bot and _process_text_command(msg, state):
            processed += 1

        if _process_reactions(msg, bot_token, state):
            processed += 1

    # Update last_message_id to the newest message
    if messages:
        newest_id = max(m["id"] for m in messages)
        state["last_message_id"] = newest_id

    _save_state(state)

    if verbose:
        print(f"[discord_review_poller] {len(messages)} messages, {processed} processed", flush=True)
    return {"ok": True, "new_messages": len(messages), "processed": processed}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_bot_token() -> str:
    """Load the Discord bot token from secrets.env."""
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll #review for approval commands and emoji reactions")
    parser.add_argument("--once", action="store_true", help="Run a single poll cycle and exit")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval in seconds (default 30)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    bot_token = _load_bot_token()

    if args.once:
        result = poll_once(bot_token, verbose=True)
        print(json.dumps(result, indent=2))
        return 0

    print(f"[discord_review_poller] starting continuous poll (interval={args.interval}s)", flush=True)
    while True:
        try:
            poll_once(bot_token, verbose=args.verbose)
        except KeyboardInterrupt:
            print("[discord_review_poller] stopped.", flush=True)
            return 0
        except Exception as exc:
            print(f"[discord_review_poller] poll error: {exc}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
