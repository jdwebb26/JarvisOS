#!/usr/bin/env python3
"""operator_next — what is the single best next action right now?

Priority policy (highest wins):
  1. Infra breakage   — critical unit down, gateway unreachable
  2. Stale cleanup    — orphaned/stale approvals or reviews
  3. Pending approval — oldest waiting_approval task
  4. Transient failure — oldest retryable failed task
  5. Blocked backlog  — blocked tasks needing investigation
  6. Queue progressing — nothing to do, queue is moving

Tie-break within a tier: oldest item first (by task_id or record_id).

Usage:
    python3 scripts/operator_next.py              # one action
    python3 scripts/operator_next.py --top 3      # top 3 actions
    python3 scripts/operator_next.py --compact    # one-liner
    python3 scripts/operator_next.py --json       # structured
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Data collection (lightweight, no heavy imports at module level)
# ---------------------------------------------------------------------------

def _is_unit_active(unit: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


def _http_ok(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception:
        return False


def _check_infra() -> list[dict[str, Any]]:
    """Return infra issues as action items (empty = healthy)."""
    issues: list[dict[str, Any]] = []

    critical_units = [
        ("openclaw-gateway.service", "Gateway"),
        ("openclaw-inbound-server.service", "Inbound server"),
        ("openclaw-ralph.timer", "Ralph timer"),
        ("openclaw-review-poller.timer", "Review poller"),
        ("lobster-todo-intake.timer", "Todo poller"),
        ("openclaw-discord-outbox.timer", "Outbox sender"),
    ]
    for unit, label in critical_units:
        if not _is_unit_active(unit):
            issues.append({
                "priority": 1,
                "category": "infra",
                "summary": f"{label} is down",
                "command": f"systemctl --user start {unit}",
                "detail": f"Unit {unit} is not active",
            })

    if not _http_ok("http://127.0.0.1:18789/health"):
        # Only flag if the service unit IS active (avoids double-reporting)
        if _is_unit_active("openclaw-gateway.service"):
            issues.append({
                "priority": 1,
                "category": "infra",
                "summary": "Gateway :18789 unreachable",
                "command": "python3 scripts/runtime_doctor.py",
                "detail": "Gateway service active but /health failed",
            })

    return issues


def _check_stale_state() -> list[dict[str, Any]]:
    """Check for stale approvals/reviews needing cleanup."""
    issues: list[dict[str, Any]] = []

    from scripts.reconcile_approvals import scan_approvals
    apr_scan = scan_approvals(root=ROOT)
    stale_apr = len(apr_scan["stale"]) + len(apr_scan["orphaned"]) + len(apr_scan["duplicates"])
    if stale_apr:
        issues.append({
            "priority": 2,
            "category": "cleanup",
            "summary": f"{stale_apr} stale/orphaned approvals",
            "command": "python3 scripts/reconcile_approvals.py --apply",
            "detail": f"stale={len(apr_scan['stale'])} orphaned={len(apr_scan['orphaned'])} dupes={len(apr_scan['duplicates'])}",
        })

    from scripts.reconcile_reviews import scan_reviews
    rev_scan = scan_reviews(root=ROOT)
    stale_rev = len(rev_scan["stale"]) + len(rev_scan["orphaned"]) + len(rev_scan["duplicates"])
    if stale_rev:
        issues.append({
            "priority": 2,
            "category": "cleanup",
            "summary": f"{stale_rev} stale/orphaned reviews",
            "command": "python3 scripts/reconcile_reviews.py --apply",
            "detail": f"stale={len(rev_scan['stale'])} orphaned={len(rev_scan['orphaned'])} dupes={len(rev_scan['duplicates'])}",
        })

    return issues


def _check_approvals() -> list[dict[str, Any]]:
    """Return pending approvals as action items, oldest first."""
    approvals_dir = ROOT / "state" / "approvals"
    tasks_dir = ROOT / "state" / "tasks"
    items: list[dict[str, Any]] = []

    if not approvals_dir.exists():
        return items

    for p in sorted(approvals_dir.glob("apr_*.json")):
        try:
            a = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if a.get("status") != "pending":
            continue
        task_id = a.get("task_id", "")
        approval_id = a.get("approval_id", "")
        task_path = tasks_dir / f"{task_id}.json"
        if not task_path.exists():
            continue
        try:
            t = json.loads(task_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if t.get("status") != "waiting_approval":
            continue

        req = t.get("normalized_request", "")[:55]
        items.append({
            "priority": 3,
            "category": "approval",
            "summary": f"approve {task_id} — {req}",
            "command": f"python3 scripts/run_ralph_v1.py --approve {task_id}",
            "detail": f"approval_id={approval_id}",
            "task_id": task_id,
            "approval_id": approval_id,
        })

    return items


def _check_failed_tasks() -> list[dict[str, Any]]:
    """Return failed tasks, split into transient (retryable) vs permanent."""
    tasks_dir = ROOT / "state" / "tasks"
    transient: list[dict[str, Any]] = []
    permanent: list[dict[str, Any]] = []

    if not tasks_dir.exists():
        return []

    transient_keywords = {"timeout", "connection", "tab_open_failed", "nvidia_error", "subtasks failed"}

    for p in sorted(tasks_dir.glob("task_*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if t.get("status") != "failed":
            continue
        tid = t.get("task_id", "")
        err = t.get("last_error", "")[:55]
        req = t.get("normalized_request", "")[:55]
        label = err or req

        is_transient = any(kw in (err + req).lower() for kw in transient_keywords)

        entry = {
            "priority": 4 if is_transient else 5,
            "category": "transient_failure" if is_transient else "permanent_failure",
            "summary": f"retry {tid} — {label}" if is_transient else f"investigate {tid} — {label}",
            "command": f"python3 scripts/run_ralph_v1.py --retry {tid}" if is_transient else f"python3 scripts/explain_task_progress.py --task-id {tid}",
            "detail": err,
            "task_id": tid,
        }
        if is_transient:
            transient.append(entry)
        else:
            permanent.append(entry)

    return transient + permanent


def _check_blocked() -> list[dict[str, Any]]:
    """Return blocked tasks as low-priority items."""
    tasks_dir = ROOT / "state" / "tasks"
    items: list[dict[str, Any]] = []

    if not tasks_dir.exists():
        return items

    count = 0
    for p in sorted(tasks_dir.glob("task_*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if t.get("status") == "blocked":
            count += 1

    if count:
        items.append({
            "priority": 6,
            "category": "blocked",
            "summary": f"{count} blocked tasks — review backlog",
            "command": "python3 scripts/operator_triage.py --compact",
            "detail": f"{count} tasks in blocked state",
        })

    return items


def _check_queue() -> list[dict[str, Any]]:
    """Return queue status as lowest-priority fallback."""
    tasks_dir = ROOT / "state" / "tasks"
    count = 0
    if tasks_dir.exists():
        for p in tasks_dir.glob("task_*.json"):
            try:
                t = json.loads(p.read_text(encoding="utf-8"))
                if t.get("status") == "queued":
                    count += 1
            except Exception:
                continue

    if count:
        return [{
            "priority": 7,
            "category": "queue",
            "summary": f"{count} tasks queued — Ralph is processing",
            "command": "python3 scripts/run_ralph_v1.py" if count > 5 else "python3 scripts/run_ralph_v1.py --status",
            "detail": "Run Ralph manually to accelerate" if count > 5 else "Queue is progressing normally",
        }]
    return []


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def compute_actions() -> list[dict[str, Any]]:
    """Collect all candidate actions, sorted by priority then position."""
    actions: list[dict[str, Any]] = []
    actions.extend(_check_infra())
    actions.extend(_check_stale_state())
    actions.extend(_check_approvals())
    actions.extend(_check_failed_tasks())
    actions.extend(_check_blocked())
    actions.extend(_check_queue())

    # Stable sort: priority first, then original order (oldest first within tier)
    actions.sort(key=lambda a: a["priority"])
    return actions


def no_action_item() -> dict[str, Any]:
    return {
        "priority": 99,
        "category": "clear",
        "summary": "no operator action needed",
        "command": "python3 scripts/runtime_doctor.py",
        "detail": "All queues empty, services healthy",
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_default(actions: list[dict[str, Any]], top: int = 1) -> str:
    if not actions:
        a = no_action_item()
        return f"NEXT: {a['summary']}\n  {a['command']}"

    lines: list[str] = []
    for i, a in enumerate(actions[:top]):
        prefix = "NEXT:" if i == 0 else f"  {i + 1}."
        lines.append(f"{prefix} {a['summary']}")
        lines.append(f"  {a['command']}")
    return "\n".join(lines)


def render_compact(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return "NEXT: clear"
    a = actions[0]
    return f"NEXT: {a['summary']}"


def render_json(actions: list[dict[str, Any]], top: int = 1) -> str:
    items = actions[:top] if actions else [no_action_item()]
    return json.dumps({"actions": items, "total_candidates": len(actions)}, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="What should the operator do next?")
    parser.add_argument("--top", type=int, default=1, help="Show top N actions (default 1)")
    parser.add_argument("--compact", action="store_true", help="One-line output")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    actions = compute_actions()

    if args.json:
        print(render_json(actions, top=args.top))
    elif args.compact:
        print(render_compact(actions))
    else:
        print(render_default(actions, top=args.top))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
