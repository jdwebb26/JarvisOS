#!/usr/bin/env python3
"""reconcile_approvals — detect and fix stale/orphaned pending approvals.

Scans state/approvals/ for pending approvals whose tasks have moved on,
gone missing, or accumulated duplicates. Default mode is dry-run (report
only). Use --apply to mark stale approvals as cancelled.

Usage:
    python3 scripts/reconcile_approvals.py              # dry-run report
    python3 scripts/reconcile_approvals.py --apply       # fix stale approvals
    python3 scripts/reconcile_approvals.py --json        # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import now_iso


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def scan_approvals(root: Optional[Path] = None) -> dict[str, Any]:
    """Scan all pending approvals and classify them.

    Returns:
        {
            "total": int,
            "by_status": {status: count},
            "valid": [...],      # pending + task is waiting_approval
            "stale": [...],      # pending + task exists but not waiting_approval
            "orphaned": [...],   # pending + task file missing
            "duplicates": [...], # >1 pending approval for same task
        }
    """
    resolved = Path(root or ROOT).resolve()
    approvals_dir = resolved / "state" / "approvals"
    tasks_dir = resolved / "state" / "tasks"

    total = 0
    by_status: dict[str, int] = {}
    valid: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    orphaned: list[dict[str, Any]] = []
    pending_by_task: dict[str, list[str]] = {}

    if not approvals_dir.exists():
        return {
            "total": 0, "by_status": {}, "valid": [], "stale": [],
            "orphaned": [], "duplicates": [],
        }

    for p in sorted(approvals_dir.glob("apr_*.json")):
        try:
            a = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        total += 1
        status = a.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1

        if status != "pending":
            continue

        approval_id = a.get("approval_id", "")
        task_id = a.get("task_id", "")
        summary = a.get("summary", "")[:60]
        requested_at = a.get("requested_at", "")

        entry = {
            "approval_id": approval_id,
            "task_id": task_id,
            "summary": summary,
            "requested_at": requested_at,
        }

        pending_by_task.setdefault(task_id, []).append(approval_id)

        task_path = tasks_dir / f"{task_id}.json"
        if not task_path.exists():
            entry["reason"] = "task_missing"
            orphaned.append(entry)
            continue

        try:
            t = json.loads(task_path.read_text(encoding="utf-8"))
        except Exception:
            entry["reason"] = "task_unreadable"
            orphaned.append(entry)
            continue

        task_status = t.get("status", "unknown")
        entry["task_status"] = task_status

        if task_status == "waiting_approval":
            valid.append(entry)
        else:
            entry["reason"] = f"task_status={task_status}"
            stale.append(entry)

    # Find duplicates: >1 pending approval for the same task
    duplicates: list[dict[str, Any]] = []
    for task_id, aids in pending_by_task.items():
        if len(aids) > 1:
            duplicates.append({"task_id": task_id, "approval_ids": aids, "count": len(aids)})

    return {
        "total": total,
        "by_status": by_status,
        "valid": valid,
        "stale": stale,
        "orphaned": orphaned,
        "duplicates": duplicates,
    }


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def cancel_approval(approval_id: str, reason: str, *, root: Optional[Path] = None) -> bool:
    """Mark a pending approval as cancelled. Returns True if updated."""
    resolved = Path(root or ROOT).resolve()
    path = resolved / "state" / "approvals" / f"{approval_id}.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if data.get("status") != "pending":
        return False
    data["status"] = "cancelled"
    data["decision_reason"] = f"[reconcile] {reason}"
    data["updated_at"] = now_iso()
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def apply_reconciliation(scan: dict[str, Any], *, root: Optional[Path] = None) -> dict[str, Any]:
    """Cancel stale and orphaned approvals. Returns summary."""
    cancelled = 0
    errors = 0

    for entry in scan["stale"]:
        reason = entry.get("reason", "stale")
        if cancel_approval(entry["approval_id"], reason, root=root):
            cancelled += 1
        else:
            errors += 1

    for entry in scan["orphaned"]:
        reason = entry.get("reason", "orphaned")
        if cancel_approval(entry["approval_id"], reason, root=root):
            cancelled += 1
        else:
            errors += 1

    # For duplicates: cancel all but the newest (by requested_at or alphabetical ID)
    resolved = Path(root or ROOT).resolve()
    for dup in scan["duplicates"]:
        aids = sorted(dup["approval_ids"])
        # Keep the last one (newest by ID sort), cancel the rest
        for aid in aids[:-1]:
            if cancel_approval(aid, f"duplicate for task {dup['task_id']}", root=root):
                cancelled += 1
            else:
                errors += 1

    return {"cancelled": cancelled, "errors": errors}


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def render_report(scan: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"Approval Reconciliation Report")
    lines.append(f"  Total approvals: {scan['total']}")
    lines.append(f"  By status: {json.dumps(scan['by_status'])}")
    lines.append(f"  Valid pending: {len(scan['valid'])}")
    lines.append(f"  Stale:         {len(scan['stale'])}")
    lines.append(f"  Orphaned:      {len(scan['orphaned'])}")
    lines.append(f"  Duplicates:    {len(scan['duplicates'])}")
    lines.append("")

    if scan["stale"]:
        lines.append("STALE (task moved on):")
        for e in scan["stale"]:
            lines.append(f"  {e['approval_id']}  task={e['task_id'][:16]}  {e.get('reason', '')}")
        lines.append("")

    if scan["orphaned"]:
        lines.append("ORPHANED (task missing):")
        for e in scan["orphaned"]:
            lines.append(f"  {e['approval_id']}  task={e['task_id'][:16]}")
        lines.append("")

    if scan["duplicates"]:
        lines.append("DUPLICATES (multiple pending for same task):")
        for d in scan["duplicates"]:
            lines.append(f"  task={d['task_id'][:16]}  count={d['count']}  ids={d['approval_ids']}")
        lines.append("")

    issues = len(scan["stale"]) + len(scan["orphaned"]) + len(scan["duplicates"])
    if issues == 0:
        lines.append("No issues found. All pending approvals are valid.")
    else:
        lines.append(f"{issues} issue(s) found. Run with --apply to fix.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Detect and fix stale/orphaned pending approvals")
    parser.add_argument("--root", default=str(ROOT), help="Project root")
    parser.add_argument("--apply", action="store_true", help="Cancel stale/orphaned approvals")
    parser.add_argument("--json", action="store_true", dest="json_out", help="JSON output")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    scan = scan_approvals(root=root)

    if args.json_out:
        print(json.dumps(scan, indent=2))
        return 0

    print(render_report(scan))

    if args.apply:
        issues = len(scan["stale"]) + len(scan["orphaned"]) + len(scan["duplicates"])
        if issues == 0:
            print("\nNothing to apply.")
            return 0
        result = apply_reconciliation(scan, root=root)
        print(f"\nApplied: {result['cancelled']} cancelled, {result['errors']} errors.")
        # Re-scan to confirm
        after = scan_approvals(root=root)
        remaining = len(after["stale"]) + len(after["orphaned"]) + len(after["duplicates"])
        print(f"Remaining issues: {remaining}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
