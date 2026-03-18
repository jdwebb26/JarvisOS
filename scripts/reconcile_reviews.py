#!/usr/bin/env python3
"""reconcile_reviews — detect and fix stale/orphaned/duplicate pending reviews.

Scans state/reviews/ for pending reviews whose tasks have moved on,
gone missing, or accumulated duplicates. Default mode is dry-run (report
only). Use --apply to mark stale reviews as cancelled.

Usage:
    python3 scripts/reconcile_reviews.py              # dry-run report
    python3 scripts/reconcile_reviews.py --apply       # fix stale reviews
    python3 scripts/reconcile_reviews.py --json        # machine-readable
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

# Task statuses where a pending review is valid.
# waiting_review is the only state where a review is genuinely pending.
_REVIEW_VALID_TASK_STATUSES = {"waiting_review"}


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def scan_reviews(root: Optional[Path] = None) -> dict[str, Any]:
    """Scan all reviews and classify pending ones.

    Returns:
        {
            "total": int,
            "by_status": {status: count},
            "valid": [...],
            "stale": [...],
            "orphaned": [...],
            "duplicates": [...],
        }
    """
    resolved = Path(root or ROOT).resolve()
    reviews_dir = resolved / "state" / "reviews"
    tasks_dir = resolved / "state" / "tasks"

    total = 0
    by_status: dict[str, int] = {}
    valid: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    orphaned: list[dict[str, Any]] = []
    pending_by_task: dict[str, list[dict[str, Any]]] = {}

    if not reviews_dir.exists():
        return {
            "total": 0, "by_status": {}, "valid": [], "stale": [],
            "orphaned": [], "duplicates": [],
        }

    for p in sorted(reviews_dir.glob("rev_*.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        total += 1
        status = r.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1

        if status != "pending":
            continue

        review_id = r.get("review_id", "")
        task_id = r.get("task_id", "")
        summary = r.get("summary", "")[:60]
        requested_at = r.get("requested_at", "")

        entry: dict[str, Any] = {
            "review_id": review_id,
            "task_id": task_id,
            "summary": summary,
            "requested_at": requested_at,
        }

        pending_by_task.setdefault(task_id, []).append(entry)

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

        if task_status in _REVIEW_VALID_TASK_STATUSES:
            valid.append(entry)
        else:
            entry["reason"] = f"task_status={task_status}"
            stale.append(entry)

    # Duplicates: >1 pending review for the same task
    duplicates: list[dict[str, Any]] = []
    for task_id, entries in pending_by_task.items():
        if len(entries) > 1:
            # Sort by requested_at descending — keep the newest
            sorted_entries = sorted(
                entries,
                key=lambda e: e.get("requested_at", ""),
                reverse=True,
            )
            kept = sorted_entries[0]["review_id"]
            extras = [e["review_id"] for e in sorted_entries[1:]]
            duplicates.append({
                "task_id": task_id,
                "kept": kept,
                "cancel": extras,
                "count": len(entries),
            })

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

def cancel_review(review_id: str, reason: str, *, root: Optional[Path] = None) -> bool:
    """Mark a pending review as cancelled. Returns True if updated."""
    resolved = Path(root or ROOT).resolve()
    path = resolved / "state" / "reviews" / f"{review_id}.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if data.get("status") != "pending":
        return False
    data["status"] = "cancelled"
    data["verdict_reason"] = f"[reconcile] {reason}"
    data["updated_at"] = now_iso()
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def apply_reconciliation(scan: dict[str, Any], *, root: Optional[Path] = None) -> dict[str, Any]:
    """Cancel stale, orphaned, and duplicate reviews. Returns summary."""
    cancelled = 0
    errors = 0

    for entry in scan["stale"]:
        reason = entry.get("reason", "stale")
        if cancel_review(entry["review_id"], reason, root=root):
            cancelled += 1
        else:
            errors += 1

    for entry in scan["orphaned"]:
        reason = entry.get("reason", "orphaned")
        if cancel_review(entry["review_id"], reason, root=root):
            cancelled += 1
        else:
            errors += 1

    for dup in scan["duplicates"]:
        for rid in dup["cancel"]:
            if cancel_review(rid, f"duplicate for task {dup['task_id']}", root=root):
                cancelled += 1
            else:
                errors += 1

    return {"cancelled": cancelled, "errors": errors}


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def render_report(scan: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Review Reconciliation Report")
    lines.append(f"  Total reviews: {scan['total']}")
    lines.append(f"  By status: {json.dumps(scan['by_status'])}")
    lines.append(f"  Valid pending: {len(scan['valid'])}")
    lines.append(f"  Stale:         {len(scan['stale'])}")
    lines.append(f"  Orphaned:      {len(scan['orphaned'])}")
    lines.append(f"  Duplicates:    {len(scan['duplicates'])}")
    lines.append("")

    if scan["stale"]:
        lines.append("STALE (task moved on):")
        for e in scan["stale"]:
            lines.append(f"  {e['review_id'][:18]}  task={e['task_id'][:18]}  {e.get('reason','')}")
        lines.append("")

    if scan["orphaned"]:
        lines.append("ORPHANED (task missing):")
        for e in scan["orphaned"]:
            lines.append(f"  {e['review_id'][:18]}  task={e['task_id'][:18]}  {e.get('reason','')}")
        lines.append("")

    if scan["duplicates"]:
        lines.append("DUPLICATES:")
        for d in scan["duplicates"]:
            lines.append(f"  task={d['task_id'][:18]}  count={d['count']}  keep={d['kept'][:18]}  cancel={d['cancel']}")
        lines.append("")

    if not scan["stale"] and not scan["orphaned"] and not scan["duplicates"]:
        lines.append("No problems found.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect and fix stale/orphaned/duplicate pending reviews",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Cancel stale/orphaned/duplicate reviews (default: dry-run)")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON")
    parser.add_argument("--root", default=None, help="Override project root")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else None
    scan = scan_reviews(root=root)

    if args.json:
        output: dict[str, Any] = {"scan": scan}
        if args.apply:
            result = apply_reconciliation(scan, root=root)
            output["apply"] = result
        print(json.dumps(output, indent=2))
        return 0

    print(render_report(scan))

    if args.apply:
        problems = len(scan["stale"]) + len(scan["orphaned"]) + len(scan["duplicates"])
        if problems == 0:
            print("Nothing to apply.")
        else:
            result = apply_reconciliation(scan, root=root)
            print(f"Applied: {result['cancelled']} cancelled, {result['errors']} errors")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
