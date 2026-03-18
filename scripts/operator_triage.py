#!/usr/bin/env python3
"""operator_triage — bucketed backlog view with recommended next actions.

Read-only. Groups actionable items into clear buckets so the operator
can burn down the backlog in priority order.

Usage:
    python3 scripts/operator_triage.py              # full triage
    python3 scripts/operator_triage.py --compact     # counts + top commands only
    python3 scripts/operator_triage.py --json        # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Data collection — reads state files directly
# ---------------------------------------------------------------------------

def _load_tasks(root: Path) -> list[dict[str, Any]]:
    tasks_dir = root / "state" / "tasks"
    rows = []
    if not tasks_dir.exists():
        return rows
    for p in tasks_dir.glob("task_*.json"):
        try:
            rows.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return rows


def _load_approvals(root: Path) -> list[dict[str, Any]]:
    approvals_dir = root / "state" / "approvals"
    rows = []
    if not approvals_dir.exists():
        return rows
    for p in approvals_dir.glob("apr_*.json"):
        try:
            rows.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return rows


def _is_transient(error: str) -> bool:
    """Classify an error string as transient (retryable) or permanent."""
    lower = error.lower()
    return any(kw in lower for kw in [
        "[transient]", "timeout", "timed out", "connection refused",
        "connection error", "nvidia_transient", "read timed out",
        "max retries exceeded", "temporarily unavailable",
    ])


# ---------------------------------------------------------------------------
# Triage buckets
# ---------------------------------------------------------------------------

def triage(root: Path) -> dict[str, Any]:
    """Build triage buckets from live state.

    Returns:
        approvals:          pending approvals with valid tasks
        transient_failures: failed tasks with transient errors (safe to retry)
        permanent_failures: failed tasks with non-transient errors
        blocked:            blocked tasks
        stale_approvals:    pending approvals whose task moved on
        queued:             queued tasks (informational)
    """
    tasks = _load_tasks(root)
    approvals_raw = _load_approvals(root)

    tasks_by_id = {t.get("task_id", ""): t for t in tasks}

    # --- Approvals ---
    valid_approvals: list[dict[str, Any]] = []
    stale_approvals: list[dict[str, Any]] = []

    for a in approvals_raw:
        if a.get("status") != "pending":
            continue
        aid = a.get("approval_id", "")
        tid = a.get("task_id", "")
        summary = a.get("summary", "")[:50]
        task = tasks_by_id.get(tid)

        if task is None:
            stale_approvals.append({"approval_id": aid, "task_id": tid,
                                    "reason": "task missing", "summary": summary})
            continue

        task_status = task.get("status", "")
        if task_status == "waiting_approval":
            req = task.get("normalized_request", "")[:50]
            valid_approvals.append({"approval_id": aid, "task_id": tid, "request": req})
        else:
            stale_approvals.append({"approval_id": aid, "task_id": tid,
                                    "reason": f"task is {task_status}", "summary": summary})

    valid_approvals.sort(key=lambda x: x["approval_id"])
    stale_approvals.sort(key=lambda x: x["approval_id"])

    # --- Failed tasks ---
    transient: list[dict[str, Any]] = []
    permanent: list[dict[str, Any]] = []

    for t in tasks:
        if t.get("status") != "failed":
            continue
        tid = t.get("task_id", "")
        req = t.get("normalized_request", "")[:50]
        error = t.get("last_error", "")
        entry = {"task_id": tid, "request": req, "error": error[:60]}

        if _is_transient(error):
            transient.append(entry)
        else:
            permanent.append(entry)

    transient.sort(key=lambda x: x["task_id"])
    permanent.sort(key=lambda x: x["task_id"])

    # --- Blocked + Queued ---
    blocked = []
    queued = []
    for t in tasks:
        tid = t.get("task_id", "")
        req = t.get("normalized_request", "")[:50]
        error = t.get("last_error", "")[:50]
        if t.get("status") == "blocked":
            blocked.append({"task_id": tid, "request": req, "error": error})
        elif t.get("status") == "queued":
            queued.append({"task_id": tid, "request": req})

    blocked.sort(key=lambda x: x["task_id"])
    queued.sort(key=lambda x: x["task_id"])

    return {
        "approvals": valid_approvals,
        "transient_failures": transient,
        "permanent_failures": permanent,
        "blocked": blocked,
        "stale_approvals": stale_approvals,
        "queued": queued,
    }


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def render_full(data: dict[str, Any]) -> str:
    lines: list[str] = []
    approvals = data["approvals"]
    transient = data["transient_failures"]
    permanent = data["permanent_failures"]
    blocked = data["blocked"]
    stale = data["stale_approvals"]
    queued = data["queued"]

    total_action = len(approvals) + len(transient) + len(permanent) + len(stale)

    lines.append("OPERATOR TRIAGE")
    lines.append(f"  {total_action} items need action | {len(blocked)} blocked | {len(queued)} queued")
    lines.append("")

    # 1. Approvals — highest priority
    if approvals:
        lines.append(f"1. APPROVE ({len(approvals)})")
        for a in approvals:
            lines.append(f"   {a['task_id'][:16]}  {a['request']}")
        lines.append("")

    # 2. Transient failures — safe to retry
    if transient:
        lines.append(f"2. RETRY — transient ({len(transient)})")
        for t in transient:
            lines.append(f"   {t['task_id'][:16]}  {t['error']}")
        lines.append("")

    # 3. Permanent failures — investigate
    if permanent:
        lines.append(f"3. INVESTIGATE — permanent ({len(permanent)})")
        for t in permanent:
            lines.append(f"   {t['task_id'][:16]}  {t['error']}")
        lines.append("")

    # 4. Stale approvals
    if stale:
        lines.append(f"4. RECONCILE — stale approvals ({len(stale)})")
        for s in stale:
            lines.append(f"   {s['approval_id'][:20]}  {s['reason']}")
        lines.append("")

    # 5. Blocked
    if blocked:
        lines.append(f"5. BLOCKED ({len(blocked)})")
        for b in blocked[:5]:
            label = b["error"] or b["request"]
            lines.append(f"   {b['task_id'][:16]}  {label}")
        if len(blocked) > 5:
            lines.append(f"   ... +{len(blocked) - 5} more")
        lines.append("")

    # 6. Queue (informational)
    lines.append(f"QUEUE: {len(queued)} waiting")
    lines.append("")

    # Commands
    lines.append("NEXT ACTIONS:")
    if approvals:
        a = approvals[0]
        lines.append(f"  python3 scripts/run_ralph_v1.py --approve {a['task_id']}")
    if transient:
        t = transient[0]
        lines.append(f"  python3 scripts/run_ralph_v1.py --retry {t['task_id']}")
    if stale:
        lines.append("  python3 scripts/reconcile_approvals.py --apply")
    if permanent:
        lines.append("  python3 scripts/run_ralph_v1.py --status  # then investigate")
    if not (approvals or transient or permanent or stale):
        lines.append("  Nothing to do right now.")

    return "\n".join(lines)


def render_compact(data: dict[str, Any]) -> str:
    lines: list[str] = []
    approvals = data["approvals"]
    transient = data["transient_failures"]
    permanent = data["permanent_failures"]
    blocked = data["blocked"]
    stale = data["stale_approvals"]
    queued = data["queued"]

    parts = []
    if approvals:
        parts.append(f"{len(approvals)} approve")
    if transient:
        parts.append(f"{len(transient)} retry")
    if permanent:
        parts.append(f"{len(permanent)} investigate")
    if stale:
        parts.append(f"{len(stale)} stale")
    if blocked:
        parts.append(f"{len(blocked)} blocked")
    parts.append(f"{len(queued)} queued")

    lines.append("TRIAGE: " + " | ".join(parts))

    if approvals:
        lines.append(f"  approve: python3 scripts/run_ralph_v1.py --approve {approvals[0]['task_id']}")
    if transient:
        lines.append(f"  retry:   python3 scripts/run_ralph_v1.py --retry {transient[0]['task_id']}")
    if stale:
        lines.append("  clean:   python3 scripts/reconcile_approvals.py --apply")
    if not (approvals or transient or permanent or stale):
        lines.append("  Nothing to do.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Bucketed operator triage — what to do next")
    parser.add_argument("--root", default=str(ROOT), help="Project root")
    parser.add_argument("--json", action="store_true", dest="json_out", help="JSON output")
    parser.add_argument("--compact", action="store_true", help="Counts + top commands only")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    data = triage(root)

    if args.json_out:
        print(json.dumps(data, indent=2))
    elif args.compact:
        print(render_compact(data))
    else:
        print(render_full(data))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
