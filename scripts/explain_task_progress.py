#!/usr/bin/env python3
"""explain_task_progress — tell the operator why a task hasn't been picked up yet.

Shows task state, Ralph queue position, what's ahead, and what to do next.

Usage:
    python3 scripts/explain_task_progress.py --task-id task_xxx
    python3 scripts/explain_task_progress.py --latest-todo
    python3 scripts/explain_task_progress.py --task-id task_xxx --json
    python3 scripts/explain_task_progress.py --task-id task_xxx --compact
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Ralph constants (mirrored from runtime/ralph/agent_loop.py)
ELIGIBLE_BACKENDS = frozenset({"ralph_adapter", "qwen_executor", "qwen_planner", "unassigned"})
BLOCKED_TASK_TYPES = frozenset({"deploy"})
BLOCKED_RISK_LEVELS = frozenset({"high_stakes"})
STEAL_AFTER_SECONDS = 3600


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_task(task_id: str, root: Path = ROOT) -> Optional[dict[str, Any]]:
    p = root / "state" / "tasks" / f"{task_id}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _load_all_tasks(root: Path = ROOT) -> list[dict[str, Any]]:
    tasks_dir = root / "state" / "tasks"
    results = []
    if not tasks_dir.exists():
        return results
    for p in tasks_dir.glob("task_*.json"):
        try:
            results.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return results


def _latest_review_for_task(task_id: str, root: Path = ROOT) -> Optional[dict[str, Any]]:
    reviews_dir = root / "state" / "reviews"
    if not reviews_dir.exists():
        return None
    candidates = []
    for p in reviews_dir.glob("rev_*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("task_id") == task_id:
                candidates.append(d)
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x.get("requested_at", ""), reverse=True)
    return candidates[0]


def _latest_approval_for_task(task_id: str, root: Path = ROOT) -> Optional[dict[str, Any]]:
    approvals_dir = root / "state" / "approvals"
    if not approvals_dir.exists():
        return None
    candidates = []
    for p in approvals_dir.glob("apr_*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("task_id") == task_id:
                candidates.append(d)
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x.get("requested_at", ""), reverse=True)
    return candidates[0]


def _find_latest_todo_task(root: Path = ROOT) -> Optional[dict[str, Any]]:
    tasks = _load_all_tasks(root)
    todo = [t for t in tasks if t.get("source_channel") == "todo"]
    if not todo:
        return None
    todo.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return todo[0]


def _find_latest_by_status(status: str, root: Path = ROOT) -> Optional[dict[str, Any]]:
    tasks = _load_all_tasks(root)
    matched = [t for t in tasks if t.get("status") == status]
    if not matched:
        return None
    matched.sort(key=lambda t: t.get("updated_at", t.get("created_at", "")), reverse=True)
    return matched[0]


# ---------------------------------------------------------------------------
# Task age
# ---------------------------------------------------------------------------

def _age_str(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        now = datetime.now(tz=timezone.utc)
        secs = (now - dt).total_seconds()
        if secs < 120:
            return f"{int(secs)}s ago"
        if secs < 3600:
            return f"{int(secs / 60)}m ago"
        if secs < 86400:
            return f"{int(secs / 3600)}h ago"
        return f"{int(secs / 86400)}d ago"
    except Exception:
        return iso_ts[:19]


def _task_age_secs(task: dict) -> float:
    try:
        dt = datetime.fromisoformat(task["created_at"].replace("Z", "+00:00"))
        return (datetime.now(tz=timezone.utc) - dt).total_seconds()
    except Exception:
        return 9999.0


# ---------------------------------------------------------------------------
# Ralph eligibility check (mirrors agent_loop._is_eligible_queued)
# ---------------------------------------------------------------------------

def _is_ralph_eligible(task: dict) -> tuple[bool, str]:
    if task.get("status") != "queued":
        return False, f"status is {task.get('status')}, not queued"
    if task.get("task_type") in BLOCKED_TASK_TYPES:
        return False, f"task_type={task['task_type']} blocked by Ralph"
    if task.get("risk_level") in BLOCKED_RISK_LEVELS:
        return False, f"risk_level={task['risk_level']} blocked by Ralph"
    backend = task.get("execution_backend", "")
    if backend not in ELIGIBLE_BACKENDS:
        return False, f"backend={backend} not in Ralph's eligible set"
    if backend in ("qwen_executor", "qwen_planner"):
        age = _task_age_secs(task)
        if age < STEAL_AFTER_SECONDS:
            remain = int(STEAL_AFTER_SECONDS - age)
            return False, f"backend={backend}, Ralph won't steal for {remain}s"
    if task.get("final_outcome") and task.get("related_review_ids") and task.get("related_approval_ids"):
        return False, "already completed (re-queue guard)"
    return True, ""


# ---------------------------------------------------------------------------
# Queue analysis
# ---------------------------------------------------------------------------

def _build_ralph_queue(all_tasks: list[dict]) -> list[dict]:
    """Return Ralph-eligible queued tasks in processing order."""
    queued = [t for t in all_tasks if t.get("status") == "queued"]

    ralph_first = sorted(
        [t for t in queued if t.get("execution_backend") == "ralph_adapter"],
        key=lambda t: t.get("created_at", ""),
    )
    others = sorted(
        [t for t in queued if t.get("execution_backend") != "ralph_adapter"],
        key=lambda t: t.get("created_at", ""),
    )

    result = []
    for t in ralph_first + others:
        eligible, reason = _is_ralph_eligible(t)
        result.append({
            "task_id": t["task_id"],
            "request": t.get("normalized_request", "")[:50],
            "backend": t.get("execution_backend", ""),
            "eligible": eligible,
            "ineligible_reason": reason,
            "age": _age_str(t.get("created_at", "")),
        })
    return result


def _count_higher_priority_work(all_tasks: list[dict], root: Path = ROOT) -> list[dict]:
    """Tasks in waiting_review or waiting_approval that Ralph services before queued."""
    work = []
    for t in all_tasks:
        if t.get("execution_backend") != "ralph_adapter":
            continue
        status = t.get("status", "")
        if status == "waiting_review":
            review = _latest_review_for_task(t["task_id"], root)
            review_status = review.get("status", "?") if review else "none"
            work.append({
                "task_id": t["task_id"],
                "status": status,
                "detail": f"review {review_status}",
                "request": t.get("normalized_request", "")[:40],
            })
        elif status == "waiting_approval":
            approval = _latest_approval_for_task(t["task_id"], root)
            approval_status = approval.get("status", "?") if approval else "none"
            work.append({
                "task_id": t["task_id"],
                "status": status,
                "detail": f"approval {approval_status}",
                "request": t.get("normalized_request", "")[:40],
            })
    return work


# ---------------------------------------------------------------------------
# Status explanations
# ---------------------------------------------------------------------------

_STAGE_EXPLANATION = {
    "queued": "Waiting in Ralph's queue. Ralph processes one task per cycle (10 min timer).",
    "running": "Currently being executed by Ralph/HAL. Should finish within ~120s.",
    "waiting_review": "HAL finished execution. Waiting for Archimedes auto-review (next Ralph cycle).",
    "waiting_approval": "Review approved. Waiting for operator approval.",
    "blocked": "Execution failed or was rejected. Operator can --retry to re-queue.",
    "failed": "Task failed. Check last_error. Operator can --retry to re-queue.",
    "completed": "Task finished successfully.",
}


# ---------------------------------------------------------------------------
# Build explanation
# ---------------------------------------------------------------------------

def explain(task_id: str, root: Path = ROOT) -> dict[str, Any]:
    task = _load_task(task_id, root)
    if not task:
        return {"ok": False, "error": f"Task {task_id} not found"}

    status = task.get("status", "unknown")
    all_tasks = _load_all_tasks(root)

    result: dict[str, Any] = {
        "ok": True,
        "task_id": task["task_id"],
        "status": status,
        "stage_explanation": _STAGE_EXPLANATION.get(status, "Unknown status."),
        "task_type": task.get("task_type", ""),
        "risk_level": task.get("risk_level", ""),
        "review_required": task.get("review_required", False),
        "approval_required": task.get("approval_required", False),
        "execution_backend": task.get("execution_backend", ""),
        "source_channel": task.get("source_channel", ""),
        "source_user": task.get("source_user", ""),
        "source_message_id": task.get("source_message_id", ""),
        "created": _age_str(task.get("created_at", "")),
        "updated": _age_str(task.get("updated_at", "")),
    }

    # Status-specific analysis
    if status == "queued":
        eligible, reason = _is_ralph_eligible(task)
        result["ralph_eligible"] = eligible
        if not eligible:
            result["ineligible_reason"] = reason
            result["action"] = f"Task is not eligible for Ralph: {reason}"
        else:
            # Queue position
            queue = _build_ralph_queue(all_tasks)
            eligible_queue = [q for q in queue if q["eligible"]]
            position = None
            for i, q in enumerate(eligible_queue):
                if q["task_id"] == task_id:
                    position = i + 1
                    break
            result["queue_position"] = position
            result["queue_total"] = len(eligible_queue)
            result["ahead_in_queue"] = eligible_queue[:position - 1] if position else []

            # Higher-priority work
            higher = _count_higher_priority_work(all_tasks, root)
            result["higher_priority_work"] = higher

            cycles_away = (len(higher) + (position - 1 if position else 0))
            if cycles_away == 0:
                result["action"] = "This task is next. Ralph will pick it up on the next cycle."
            else:
                result["action"] = (
                    f"~{cycles_away} Ralph cycle(s) away (~{cycles_away * 10}min). "
                    f"{len(higher)} review/approval tasks served first, "
                    f"{position - 1 if position else '?'} queued tasks ahead."
                )

    elif status == "waiting_review":
        review = _latest_review_for_task(task_id, root)
        if review:
            result["review_id"] = review.get("review_id", "")
            result["review_status"] = review.get("review_status", review.get("status", ""))
            if review.get("status") == "pending":
                result["action"] = "Archimedes will auto-review on the next Ralph cycle."
            elif review.get("status") == "approved":
                if task.get("approval_required"):
                    result["action"] = "Review approved. Ralph will request operator approval next cycle."
                else:
                    result["action"] = "Review approved. Ralph will complete this task next cycle (no approval needed)."
            elif review.get("status") == "rejected":
                result["action"] = "Review was rejected. Ralph will fail this task next cycle."
        else:
            result["action"] = "In waiting_review but no review record found."

    elif status == "waiting_approval":
        approval = _latest_approval_for_task(task_id, root)
        if approval:
            result["approval_id"] = approval.get("approval_id", "")
            result["approval_status"] = approval.get("status", "")
            if approval.get("status") == "pending":
                aid = approval.get("approval_id", "")
                result["action"] = (
                    f"Waiting for operator approval.\n"
                    f"  python3 scripts/run_ralph_v1.py --approve {task_id}\n"
                    f"  python3 scripts/run_ralph_v1.py --reject {task_id}\n"
                    f"  Discord #review: approve {aid}"
                )
            elif approval.get("status") == "approved":
                result["action"] = "Approval granted. Ralph will finalize on next cycle."
        else:
            result["action"] = "In waiting_approval but no approval record found."

    elif status in ("failed", "blocked"):
        error = task.get("last_error", "")
        result["last_error"] = error[:200]
        result["error_count"] = task.get("error_count", 0)
        transient = any(kw in error.lower() for kw in [
            "[transient]", "timeout", "timed out", "connection refused",
            "connection error", "nvidia_transient", "read timed out",
            "max retries exceeded", "rate limit", "502", "503",
        ])
        result["looks_transient"] = transient
        result["action"] = (
            f"{'Looks transient — safe to retry.' if transient else 'Check last_error before retrying.'}\n"
            f"  python3 scripts/run_ralph_v1.py --retry {task_id}"
        )

    elif status == "completed":
        result["final_outcome"] = task.get("final_outcome", "")[:200]
        result["action"] = "Done. No action needed."

    return result


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def render_terminal(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return data.get("error", "Unknown error")

    lines = []
    tid = data["task_id"]
    status = data["status"].upper()
    lines.append(f"Task {tid}")
    lines.append(f"  Status:   {status}")
    lines.append(f"  Type:     {data['task_type']}  Risk: {data['risk_level']}")
    lines.append(f"  Backend:  {data['execution_backend']}")

    if data.get("source_channel"):
        lines.append(f"  Source:   #{data['source_channel']} by {data.get('source_user', '?')}")
    if data.get("source_message_id"):
        lines.append(f"  Msg ID:   {data['source_message_id']}")

    lines.append(f"  Review:   {'required' if data.get('review_required') else 'not required'}")
    lines.append(f"  Approval: {'required' if data.get('approval_required') else 'not required'}")
    lines.append(f"  Created:  {data.get('created', '?')}  Updated: {data.get('updated', '?')}")
    lines.append("")
    lines.append(f"  {data.get('stage_explanation', '')}")
    lines.append("")

    # Queue details
    if data["status"] == "queued" and data.get("ralph_eligible"):
        pos = data.get("queue_position", "?")
        total = data.get("queue_total", "?")
        lines.append(f"  Queue position: {pos} of {total}")

        higher = data.get("higher_priority_work", [])
        if higher:
            lines.append(f"  Higher-priority work ({len(higher)} items served first):")
            for h in higher:
                lines.append(f"    {h['task_id'][:16]}  {h['status']:18}  {h['detail']}")

        ahead = data.get("ahead_in_queue", [])
        if ahead:
            lines.append(f"  Queued tasks ahead ({len(ahead)}):")
            for a in ahead:
                lines.append(f"    {a['task_id'][:16]}  {a['backend']:16}  {a['request']}")
        lines.append("")

    # Review/approval details
    if data.get("review_id"):
        lines.append(f"  Review:   {data['review_id']}  status={data.get('review_status', '?')}")
    if data.get("approval_id"):
        lines.append(f"  Approval: {data['approval_id']}  status={data.get('approval_status', '?')}")

    # Error details
    if data.get("last_error"):
        lines.append(f"  Error:    {data['last_error'][:100]}")
        if data.get("looks_transient"):
            lines.append(f"  (looks transient — retry likely safe)")

    # Final outcome
    if data.get("final_outcome"):
        lines.append(f"  Outcome:  {data['final_outcome'][:100]}")

    # Action
    action = data.get("action", "")
    if action:
        lines.append("")
        lines.append(f"  Next: {action}")

    return "\n".join(lines)


def render_compact(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return data.get("error", "Unknown error")
    tid = data["task_id"][:16]
    status = data["status"]
    action = (data.get("action") or "").split("\n")[0]
    pos = ""
    if data.get("queue_position"):
        pos = f" [{data['queue_position']}/{data['queue_total']}]"
    return f"{tid}  {status}{pos}  {action}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Explain why a task is waiting")
    parser.add_argument("--root", default=str(ROOT), help="Project root")
    parser.add_argument("--task-id", help="Task ID to explain")
    parser.add_argument("--latest-todo", action="store_true",
                        help="Explain the most recently created #todo task")
    parser.add_argument("--latest-failed", action="store_true",
                        help="Explain the most recently failed task")
    parser.add_argument("--latest-approval", action="store_true",
                        help="Explain the most recent waiting_approval task")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--compact", action="store_true", help="One-line output")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    task_id = args.task_id

    if args.latest_todo:
        task = _find_latest_todo_task(root)
        if not task:
            print("No #todo tasks found")
            return 1
        task_id = task["task_id"]
    elif args.latest_failed:
        task = _find_latest_by_status("failed", root)
        if not task:
            print("No failed tasks found")
            return 1
        task_id = task["task_id"]
    elif args.latest_approval:
        task = _find_latest_by_status("waiting_approval", root)
        if not task:
            print("No waiting_approval tasks found")
            return 1
        task_id = task["task_id"]

    if not task_id:
        parser.error("Provide --task-id, --latest-todo, --latest-failed, or --latest-approval")

    data = explain(task_id, root)

    if args.json:
        print(json.dumps(data, indent=2))
    elif args.compact:
        print(render_compact(data))
    else:
        print(render_terminal(data))

    return 0 if data.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
