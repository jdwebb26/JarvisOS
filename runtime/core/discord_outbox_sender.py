#!/usr/bin/env python3
"""discord_outbox_sender — consume state/discord_outbox/*.json and deliver via webhook.

Reads pending outbox entries, resolves channel_id → webhook URL, POSTs via
Discord webhook, marks each entry delivered/failed/skipped_no_webhook.
Writes delivery records to state/discord_delivery/.

Channel → env var mapping (set these in ~/.openclaw/secrets.env):
    1478178050133987400  jarvis    → JARVIS_WEBHOOK_URL          (existing)
    1478178150268670212  anton     → COUNCIL_WEBHOOK_URL          (existing)
    1483132981177618482  archimedes→ REVIEW_WEBHOOK_URL           (existing)
    1483539080271761408  bowser    → JARVIS_DISCORD_WEBHOOK_BOWSER (new)
    1483537502152425625  cadence   → JARVIS_DISCORD_WEBHOOK_CADENCE (new)
    1483539374854639761  worklog   → JARVIS_DISCORD_WEBHOOK_WORKLOG (new)
    1483133691969671289  hal       → JARVIS_DISCORD_WEBHOOK_HAL
    1483131531546464336  scout     → JARVIS_DISCORD_WEBHOOK_SCOUT
    1483131437292191945  hermes    → JARVIS_DISCORD_WEBHOOK_HERMES
    1483320979185733722  kitt      → JARVIS_DISCORD_WEBHOOK_KITT
    1483133844663304272  muse      → JARVIS_DISCORD_WEBHOOK_MUSE
    1483131473543303208  qwen      → JARVIS_DISCORD_WEBHOOK_QWEN
    1483916191046041811  sigma     → JARVIS_DISCORD_WEBHOOK_SIGMA  (quant validation)
    1483916149573025793  atlas     → JARVIS_DISCORD_WEBHOOK_ATLAS  (quant discovery)
    1483916169672130754  fish      → JARVIS_DISCORD_WEBHOOK_FISH   (quant scenarios)
    1484083970151813151  ralph     → JARVIS_DISCORD_WEBHOOK_RALPH  (overflow)
    1484324994552172544  vizor     → JARVIS_DISCORD_WEBHOOK_VIZOR  (visual quant)
    1484325009391489064  ict       → JARVIS_DISCORD_WEBHOOK_ICT    (methodology expert)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Reuse the existing webhook utility from scripts/
_SCRIPTS = ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from dispatch_utils import load_webhook_url, post_webhook, send_bot_message
from runtime.core.models import new_id, now_iso


# ---------------------------------------------------------------------------
# Channel → env var mapping (canonical)
# ---------------------------------------------------------------------------

CHANNEL_WEBHOOK_ENV: dict[str, str] = {
    "1478178050133987400": "JARVIS_WEBHOOK_URL",            # jarvis
    "1478178150268670212": "COUNCIL_WEBHOOK_URL",            # anton
    "1483132981177618482": "REVIEW_WEBHOOK_URL",             # archimedes
    "1483539080271761408": "JARVIS_DISCORD_WEBHOOK_BOWSER",  # bowser
    "1483537502152425625": "JARVIS_DISCORD_WEBHOOK_CADENCE", # cadence
    "1483539374854639761": "JARVIS_DISCORD_WEBHOOK_WORKLOG", # worklog
    "1483133691969671289": "JARVIS_DISCORD_WEBHOOK_HAL",     # hal
    "1483131531546464336": "JARVIS_DISCORD_WEBHOOK_SCOUT",   # scout
    "1483131437292191945": "JARVIS_DISCORD_WEBHOOK_HERMES",  # hermes
    "1483320979185733722": "JARVIS_DISCORD_WEBHOOK_KITT",    # kitt
    "1483133844663304272": "JARVIS_DISCORD_WEBHOOK_MUSE",    # muse
    "1483131473543303208": "JARVIS_DISCORD_WEBHOOK_QWEN",    # qwen
    "1483916191046041811": "JARVIS_DISCORD_WEBHOOK_SIGMA",   # sigma (quant validation)
    "1483916149573025793": "JARVIS_DISCORD_WEBHOOK_ATLAS",   # atlas (quant discovery)
    "1483916169672130754": "JARVIS_DISCORD_WEBHOOK_FISH",    # fish (quant scenarios)
    "1484083970151813151": "JARVIS_DISCORD_WEBHOOK_RALPH",   # ralph (overflow)
    "1484088366155698176": "JARVIS_DISCORD_WEBHOOK_PULSE",   # pulse (discretionary alerts)
    "1484324994552172544": "JARVIS_DISCORD_WEBHOOK_VIZOR",   # vizor (visual quant)
    "1484325009391489064": "JARVIS_DISCORD_WEBHOOK_ICT",     # ict (methodology expert)
}


# ---------------------------------------------------------------------------
# State dirs
# ---------------------------------------------------------------------------

def _outbox_dir(root: Path) -> Path:
    d = root / "state" / "discord_outbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _delivery_dir(root: Path) -> Path:
    d = root / "state" / "discord_delivery"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Outbox I/O
# ---------------------------------------------------------------------------

def _load_pending_entries(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Return (path, record) for all pending outbox entries, oldest first."""
    entries = []
    for path in sorted(_outbox_dir(root).glob("outbox_*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            if rec.get("status") == "pending":
                entries.append((path, rec))
        except (json.JSONDecodeError, OSError):
            pass
    return entries


def _mark_outbox_entry(path: Path, status: str, delivery_id: str, error: str = "") -> None:
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
        rec["status"] = status
        rec["delivery_id"] = delivery_id
        rec["delivered_at"] = now_iso()
        if error:
            rec["delivery_error"] = error
        path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    except (json.JSONDecodeError, OSError):
        pass


# ---------------------------------------------------------------------------
# Delivery record
# ---------------------------------------------------------------------------

def _write_delivery_record(
    root: Path,
    *,
    delivery_id: str,
    entry_id: str,
    channel_id: str,
    webhook_env_var: str,
    status: str,
    http_status: Optional[int],
    error: str,
    text_preview: str,
    event_kind: str,
    label: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "delivery_id": delivery_id,
        "created_at": now_iso(),
        "entry_id": entry_id,
        "channel_id": channel_id,
        "webhook_env_var": webhook_env_var,
        "status": status,
        "http_status": http_status,
        "error": error,
        "text_preview": text_preview[:120],
        "event_kind": event_kind,
        "label": label,
    }
    path = _delivery_dir(root) / f"{delivery_id}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


# ---------------------------------------------------------------------------
# Main sender
# ---------------------------------------------------------------------------

def send_pending(
    root: Optional[Path] = None,
    *,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Process all pending outbox entries. Return summary dict."""
    resolved = Path(root or ROOT).resolve()
    entries = _load_pending_entries(resolved)

    delivered = 0
    failed = 0
    skipped = 0

    for path, rec in entries:
        entry_id = rec.get("entry_id", path.stem)
        channel_id = rec.get("channel_id", "")
        text = rec.get("text", "")
        event_kind = rec.get("event_kind", "")
        label = rec.get("label", "")

        env_var = CHANNEL_WEBHOOK_ENV.get(channel_id, "")
        delivery_id = new_id("dlv")

        if not env_var:
            # Unknown channel — skip
            _mark_outbox_entry(path, "skipped_unknown_channel", delivery_id)
            _write_delivery_record(
                resolved, delivery_id=delivery_id, entry_id=entry_id,
                channel_id=channel_id, webhook_env_var="",
                status="skipped_unknown_channel", http_status=None,
                error=f"no env var mapping for channel {channel_id}",
                text_preview=text, event_kind=event_kind, label=label,
            )
            skipped += 1
            if verbose:
                print(f"  SKIP  {entry_id} channel={channel_id} (no env var mapping)")
            continue

        webhook_url = load_webhook_url(env_var, resolved.parent)
        if not webhook_url or webhook_url == "REPLACE_ME":
            _mark_outbox_entry(path, "skipped_no_webhook", delivery_id,
                               error=f"{env_var} not set")
            _write_delivery_record(
                resolved, delivery_id=delivery_id, entry_id=entry_id,
                channel_id=channel_id, webhook_env_var=env_var,
                status="skipped_no_webhook", http_status=None,
                error=f"{env_var} not set or is REPLACE_ME",
                text_preview=text, event_kind=event_kind, label=label,
            )
            skipped += 1
            if verbose:
                print(f"  SKIP  {entry_id} {env_var}=not_set")
            continue

        if dry_run:
            if verbose:
                print(f"  DRY   {entry_id} → {env_var} | {text[:60]}")
            skipped += 1
            continue

        result = post_webhook(webhook_url, text)
        if result.get("ok"):
            _mark_outbox_entry(path, "delivered", delivery_id)
            _write_delivery_record(
                resolved, delivery_id=delivery_id, entry_id=entry_id,
                channel_id=channel_id, webhook_env_var=env_var,
                status="delivered", http_status=result.get("http_status"),
                error="", text_preview=text, event_kind=event_kind, label=label,
            )
            delivered += 1
            if verbose:
                print(f"  OK    {entry_id} → {env_var} [{result.get('http_status')}]")
        else:
            err = result.get("reason", str(result))
            _mark_outbox_entry(path, "failed", delivery_id, error=err)
            _write_delivery_record(
                resolved, delivery_id=delivery_id, entry_id=entry_id,
                channel_id=channel_id, webhook_env_var=env_var,
                status="failed", http_status=result.get("http_status"),
                error=err, text_preview=text, event_kind=event_kind, label=label,
            )
            failed += 1
            if verbose:
                print(f"  FAIL  {entry_id} → {env_var}: {err}")

    return {
        "total": len(entries),
        "delivered": delivered,
        "failed": failed,
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Discord outbox sender")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be sent without posting")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    summary = send_pending(
        Path(args.root).resolve(),
        dry_run=args.dry_run,
        verbose=True,
    )
    print(json.dumps(summary, indent=2))
