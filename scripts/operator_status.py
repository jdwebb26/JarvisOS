#!/usr/bin/env python3
"""operator_status — phone-friendly, action-first operator summary.

One command answers: what needs my attention right now?

Usage:
    python3 scripts/operator_status.py              # terminal (narrow-friendly)
    python3 scripts/operator_status.py --discord     # post summary to #jarvis
    python3 scripts/operator_status.py --if-needed   # post only when action needed
    python3 scripts/operator_status.py --json        # machine-readable
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# env loader
# ---------------------------------------------------------------------------

def _load_env() -> None:
    for env_path in [
        Path.home() / ".openclaw" / "secrets.env",
        Path.home() / ".openclaw" / ".env",
    ]:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# data collection
# ---------------------------------------------------------------------------

def _pending_approvals() -> list[dict[str, Any]]:
    """Return pending approvals joined with their task's request text."""
    approvals_dir = ROOT / "state" / "approvals"
    tasks_dir = ROOT / "state" / "tasks"
    results = []
    if not approvals_dir.exists():
        return results
    for p in approvals_dir.glob("apr_*.json"):
        try:
            a = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if a.get("status") != "pending":
            continue
        task_id = a.get("task_id", "")
        request = ""
        task_path = tasks_dir / f"{task_id}.json"
        if task_path.exists():
            try:
                t = json.loads(task_path.read_text(encoding="utf-8"))
                # skip if task is no longer waiting for approval — stale
                if t.get("status") not in ("waiting_approval",):
                    continue
                request = t.get("normalized_request", "")
            except Exception:
                pass
        results.append({
            "approval_id": a.get("approval_id", ""),
            "task_id": task_id,
            "request": request,
        })
    results.sort(key=lambda x: x["approval_id"])
    return results


def _actionable_tasks() -> dict[str, list[dict[str, Any]]]:
    """Return tasks grouped by action needed: queued, blocked, failed."""
    tasks_dir = ROOT / "state" / "tasks"
    queued: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    if not tasks_dir.exists():
        return {"queued": queued, "blocked": blocked, "failed": failed}
    for p in tasks_dir.glob("task_*.json"):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        tid = t.get("task_id", "")
        status = t.get("status", "")
        req = t.get("normalized_request", "")[:55]
        error = t.get("last_error", "")[:55]
        entry = {"task_id": tid, "request": req, "error": error}
        if status == "queued":
            queued.append(entry)
        elif status == "blocked":
            blocked.append(entry)
        elif status == "failed":
            failed.append(entry)
    queued.sort(key=lambda x: x["task_id"])
    blocked.sort(key=lambda x: x["task_id"])
    failed.sort(key=lambda x: x["task_id"])
    return {"queued": queued, "blocked": blocked, "failed": failed}


def _timer_health() -> list[dict[str, Any]]:
    """Check systemd user timers and key services."""
    units = [
        ("openclaw-ralph.timer", "Ralph"),
        ("openclaw-review-poller.timer", "Review poller"),
        ("lobster-todo-intake.timer", "Todo poller"),
        ("openclaw-discord-outbox.timer", "Outbox sender"),
        ("openclaw-gateway.service", "Gateway"),
        ("openclaw-inbound-server.service", "Inbound server"),
    ]
    results = []
    for unit, label in units:
        try:
            r = subprocess.run(
                ["systemctl", "--user", "is-active", unit],
                capture_output=True, text=True, timeout=5,
            )
            active = r.stdout.strip() == "active"
        except Exception:
            active = False
        results.append({"unit": unit, "label": label, "active": active})
    return results


def _outbox_health() -> dict[str, int]:
    """Count pending/failed outbox entries."""
    outbox_dir = ROOT / "state" / "discord_outbox"
    pending = failed = 0
    if not outbox_dir.exists():
        return {"pending": pending, "failed": failed}
    for p in outbox_dir.glob("outbox_*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            s = d.get("status", "")
            if s == "pending":
                pending += 1
            elif s in ("failed", "error"):
                failed += 1
        except Exception:
            pass
    return {"pending": pending, "failed": failed}


def collect() -> dict[str, Any]:
    approvals = _pending_approvals()
    tasks = _actionable_tasks()
    timers = _timer_health()
    outbox = _outbox_health()
    return {
        "ts": datetime.now(tz=timezone.utc).isoformat()[:19] + "Z",
        "approvals": approvals,
        "queued": tasks["queued"],
        "blocked": tasks["blocked"],
        "failed": tasks["failed"],
        "timers": timers,
        "outbox": outbox,
    }


# ---------------------------------------------------------------------------
# terminal renderer (narrow / phone-friendly)
# ---------------------------------------------------------------------------

def render_terminal(data: dict[str, Any]) -> str:
    lines: list[str] = []
    ts = data["ts"][:16].replace("T", " ")

    # Header with summary counts
    approvals = data["approvals"]
    failed = data["failed"]
    blocked = data["blocked"]
    queued = data["queued"]
    action_count = len(approvals) + len(failed)

    lines.append(f"=== OpenClaw Status  {ts} UTC ===")
    parts = []
    if approvals:
        parts.append(f"{len(approvals)} approvals")
    if failed:
        parts.append(f"{len(failed)} failed")
    if blocked:
        parts.append(f"{len(blocked)} blocked")
    parts.append(f"{len(queued)} queued")
    lines.append("  " + " | ".join(parts))
    lines.append("")

    # 1. Needs action
    if action_count == 0 and not blocked:
        lines.append("  Nothing needs attention right now.")
        lines.append("")
    else:
        if approvals:
            lines.append(f"APPROVALS ({len(approvals)} waiting)")
            for a in approvals:
                tid_short = a["task_id"][:16]
                req = a["request"][:48]
                lines.append(f"  {tid_short}  {req}")
                lines.append(f"    --approve {a['task_id']}")
            lines.append("")

        if failed:
            lines.append(f"FAILED ({len(failed)} retryable)")
            for t in failed:
                tid_short = t["task_id"][:16]
                err = t["error"] or t["request"][:48]
                lines.append(f"  {tid_short}  {err}")
                lines.append(f"    --retry {t['task_id']}")
            lines.append("")

        if blocked:
            lines.append(f"BLOCKED ({len(blocked)})")
            for t in blocked:
                tid_short = t["task_id"][:16]
                label = t["error"][:48] if t["error"] else t["request"][:48]
                lines.append(f"  {tid_short}  {label}")
                lines.append(f"    --retry {t['task_id']}")
            lines.append("")

    # 2. Queue
    queued = data["queued"]
    lines.append(f"QUEUE: {len(queued)} tasks waiting")
    if queued:
        for t in queued[:5]:
            lines.append(f"  {t['task_id'][:16]}  {t['request'][:48]}")
        if len(queued) > 5:
            lines.append(f"  ... +{len(queued) - 5} more")
    lines.append("")

    # 3. Timers/services
    timers = data["timers"]
    down = [t for t in timers if not t["active"]]
    if down:
        lines.append("SERVICES")
        for t in timers:
            mark = "OK" if t["active"] else "DOWN"
            lines.append(f"  {mark:4}  {t['label']}")
        lines.append("")
    else:
        lines.append(f"SERVICES: all {len(timers)} OK")

    # 4. Outbox
    outbox = data["outbox"]
    if outbox["failed"] > 0:
        lines.append(f"OUTBOX: {outbox['failed']} failed deliveries")
    lines.append("")

    # Quick commands
    if approvals or failed:
        lines.append("COMMANDS (from jarvis-v5/):")
        if approvals:
            lines.append("  Approve all:")
            for a in approvals[:3]:
                lines.append(f"    python3 scripts/run_ralph_v1.py --approve {a['task_id']}")
            if len(approvals) > 3:
                lines.append(f"    ... +{len(approvals) - 3} more")
        if failed:
            lines.append("  Retry failed:")
            for t in failed[:3]:
                lines.append(f"    python3 scripts/run_ralph_v1.py --retry {t['task_id']}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# discord renderer
# ---------------------------------------------------------------------------

def render_discord(data: dict[str, Any]) -> str:
    lines: list[str] = []
    ts = data["ts"][:16].replace("T", " ")

    approvals = data["approvals"]
    failed = data["failed"]
    blocked = data["blocked"]
    queued = data["queued"]
    timers = data["timers"]
    outbox = data["outbox"]

    down = [t for t in timers if not t["active"]]

    # Header with counts
    lines.append(f"\U0001f4cb **Operator Status** — {ts} UTC")

    # Services
    if down:
        names = ", ".join(t["label"] for t in down)
        lines.append(f"\u26a0\ufe0f Services: **{len(down)} down** ({names})")
    else:
        lines.append(f"\u2705 All {len(timers)} services/timers OK")

    # Action items
    if not approvals and not failed and not blocked:
        lines.append("\u2705 Nothing needs attention")
    else:
        if approvals:
            lines.append(f"\n\U0001f514 **{len(approvals)} pending approvals**")
            for a in approvals[:5]:
                req = a["request"][:45]
                lines.append(f"> `{a['task_id'][:16]}` {req}")
            if len(approvals) > 5:
                lines.append(f"> +{len(approvals) - 5} more")

        if failed:
            lines.append(f"\n\u274c **{len(failed)} failed** (retryable)")
            for t in failed[:3]:
                err = t["error"][:40] or t["request"][:40]
                lines.append(f"> `{t['task_id'][:16]}` {err}")

        if blocked:
            lines.append(f"\n\U0001f6ab **{len(blocked)} blocked**")

    # Queue
    lines.append(f"\n\U0001f4e5 **{len(queued)} queued**")

    # Outbox
    if outbox["failed"] > 0:
        lines.append(f"\u26a0\ufe0f Outbox: {outbox['failed']} failed deliveries")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def needs_attention(data: dict[str, Any]) -> bool:
    """Return True if there are actionable items or service problems."""
    if data["approvals"] or data["failed"]:
        return True
    down = [t for t in data["timers"] if not t["active"]]
    if down:
        return True
    if data["outbox"]["failed"] > 0:
        return True
    return False


def _fingerprint(data: dict[str, Any]) -> str:
    """Stable hash of the actionable content — used to suppress duplicate posts.

    Only hashes the items that matter for operator action: approval IDs,
    failed task IDs, down service names, and outbox failure count.
    Changes to queue depth alone do NOT change the fingerprint.
    """
    import hashlib
    parts: list[str] = []
    for a in data.get("approvals", []):
        parts.append(f"apr:{a['approval_id']}")
    for t in data.get("failed", []):
        parts.append(f"fail:{t['task_id']}")
    for t in data.get("blocked", []):
        parts.append(f"block:{t['task_id']}")
    for s in data.get("timers", []):
        if not s["active"]:
            parts.append(f"down:{s['unit']}")
    if data.get("outbox", {}).get("failed", 0) > 0:
        parts.append(f"outbox_fail:{data['outbox']['failed']}")
    return hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()[:16]


def _state_dir() -> Path:
    d = ROOT / "state" / "operator_status"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _is_duplicate(fp: str) -> bool:
    """True if the last posted fingerprint matches."""
    path = _state_dir() / "last_fingerprint.txt"
    if path.exists():
        try:
            return path.read_text(encoding="utf-8").strip() == fp
        except Exception:
            pass
    return False


def _save_fingerprint(fp: str) -> None:
    (_state_dir() / "last_fingerprint.txt").write_text(fp + "\n", encoding="utf-8")


def _post_discord(data: dict[str, Any]) -> str:
    """Post status to #jarvis. Returns event_id or raises."""
    text = render_discord(data)
    from runtime.core.discord_event_router import emit_event
    result = emit_event(
        "cockpit_status", "jarvis",
        detail=text,
        root=ROOT,
    )
    return result.get("event_id", "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phone-friendly operator status")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON")
    parser.add_argument("--discord", action="store_true", help="Post to #jarvis Discord")
    parser.add_argument("--if-needed", action="store_true",
                        help="Post to Discord only when action needed (for timer use)")
    args = parser.parse_args()

    _load_env()
    data = collect()

    if args.json:
        print(json.dumps(data, indent=2))
        return 0

    if args.if_needed:
        if not needs_attention(data):
            print("Nothing needs attention — skipping.")
            return 0
        fp = _fingerprint(data)
        if _is_duplicate(fp):
            print(f"Duplicate ({fp}) — skipping repeat post.")
            return 0
        try:
            eid = _post_discord(data)
            _save_fingerprint(fp)
            print(render_terminal(data))
            print(f"Posted to Discord ({eid})")
        except Exception as exc:
            print(f"Discord post failed: {exc}", file=sys.stderr)
            return 1
        return 0

    print(render_terminal(data))

    if args.discord:
        try:
            eid = _post_discord(data)
            print(f"Posted to Discord ({eid})")
        except Exception as exc:
            print(f"Discord post failed: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
