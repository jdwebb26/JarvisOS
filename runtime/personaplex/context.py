#!/usr/bin/env python3
"""PersonaPlex context assembly — reads live runtime state for injection into conversation.

All readers are read-only. They never modify state.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import now_iso


# ---------------------------------------------------------------------------
# Task state
# ---------------------------------------------------------------------------

def read_tasks_by_status(root: Optional[Path] = None, limit: int = 50) -> dict[str, Any]:
    """Read all tasks grouped by status."""
    from runtime.core.task_store import list_tasks
    root_path = Path(root or ROOT).resolve()
    tasks = list_tasks(root=root_path, limit=limit)
    by_status: dict[str, list[dict[str, Any]]] = {}
    for t in tasks:
        d = t.to_dict()
        status = d.get("status", "unknown")
        entry = {
            "task_id": d["task_id"],
            "summary": d.get("summary") or d.get("normalized_request", "")[:120],
            "status": status,
            "task_type": d.get("task_type", ""),
            "priority": d.get("priority", ""),
            "execution_backend": d.get("execution_backend", ""),
            "updated_at": d.get("updated_at", ""),
            "last_error": d.get("last_error", ""),
            "final_outcome": (d.get("final_outcome") or "")[:200],
        }
        by_status.setdefault(status, []).append(entry)
    return {
        "total_tasks": len(tasks),
        "by_status": by_status,
        "status_counts": {k: len(v) for k, v in by_status.items()},
    }


def read_queued_tasks(root: Optional[Path] = None) -> list[dict[str, Any]]:
    """Return only queued tasks."""
    result = read_tasks_by_status(root=root)
    return result["by_status"].get("queued", [])


def read_failed_tasks(root: Optional[Path] = None) -> list[dict[str, Any]]:
    """Return only failed tasks."""
    result = read_tasks_by_status(root=root)
    return result["by_status"].get("failed", [])


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------

def read_pending_approvals(root: Optional[Path] = None) -> list[dict[str, Any]]:
    """Read all pending approval records."""
    root_path = Path(root or ROOT).resolve()
    approvals_dir = root_path / "state" / "approvals"
    if not approvals_dir.exists():
        return []
    pending: list[dict[str, Any]] = []
    for path in sorted(approvals_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("status") == "pending":
            pending.append({
                "approval_id": data.get("approval_id", ""),
                "task_id": data.get("task_id", ""),
                "summary": data.get("summary", ""),
                "requested_by": data.get("requested_by", ""),
                "requested_at": data.get("requested_at") or data.get("created_at", ""),
                "approval_type": data.get("approval_type", ""),
            })
    return pending


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

def read_pending_reviews(root: Optional[Path] = None) -> list[dict[str, Any]]:
    """Read all pending review records."""
    root_path = Path(root or ROOT).resolve()
    reviews_dir = root_path / "state" / "reviews"
    if not reviews_dir.exists():
        return []
    pending: list[dict[str, Any]] = []
    for path in sorted(reviews_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("status") == "pending":
            pending.append({
                "review_id": data.get("review_id", ""),
                "task_id": data.get("task_id", ""),
                "summary": data.get("summary", ""),
                "requested_by": data.get("requested_by", ""),
                "reviewer_role": data.get("reviewer_role", ""),
                "requested_at": data.get("requested_at") or data.get("created_at", ""),
            })
    return pending


# ---------------------------------------------------------------------------
# Recent activity
# ---------------------------------------------------------------------------

def read_recent_events(root: Optional[Path] = None, limit: int = 15) -> list[dict[str, Any]]:
    """Read the most recent runtime events."""
    root_path = Path(root or ROOT).resolve()
    events_dir = root_path / "state" / "events"
    if not events_dir.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(events_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if len(events) >= limit:
            break
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        events.append({
            "event_id": data.get("event_id", ""),
            "event_kind": data.get("event_kind", ""),
            "actor": data.get("actor", ""),
            "task_id": data.get("task_id", ""),
            "summary": (data.get("summary") or data.get("detail") or "")[:200],
            "created_at": data.get("created_at", ""),
        })
    return events


# ---------------------------------------------------------------------------
# Agent status
# ---------------------------------------------------------------------------

def read_agent_statuses(root: Optional[Path] = None) -> list[dict[str, Any]]:
    """Read per-agent status files."""
    root_path = Path(root or ROOT).resolve()
    status_dir = root_path / "state" / "agent_status"
    if not status_dir.exists():
        return []
    agents: list[dict[str, Any]] = []
    for path in sorted(status_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        agents.append({
            "agent_id": data.get("agent_id", path.stem),
            "state": data.get("state", "unknown"),
            "headline": data.get("headline", ""),
            "updated_at": data.get("updated_at", ""),
            "current_task_id": data.get("current_task_id", ""),
        })
    return agents


# ---------------------------------------------------------------------------
# Service health (lightweight check)
# ---------------------------------------------------------------------------

def read_service_health(root: Optional[Path] = None) -> dict[str, Any]:
    """Quick service health summary from the latest cockpit snapshot."""
    root_path = Path(root or ROOT).resolve()
    snapshot_path = root_path / "state" / "logs" / "cockpit_snapshot.json"
    if snapshot_path.exists():
        try:
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            return {
                "source": "cockpit_snapshot",
                "services": data.get("services", {}),
                "generated_at": data.get("generated_at", ""),
            }
        except Exception:
            pass
    # Fallback: just report what we can see
    return {"source": "fallback", "services": {}, "generated_at": now_iso()}


# ---------------------------------------------------------------------------
# Git / repo changes
# ---------------------------------------------------------------------------

def read_recent_git_activity(root: Optional[Path] = None, limit: int = 10) -> list[dict[str, str]]:
    """Read recent git commits."""
    root_path = Path(root or ROOT).resolve()
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={limit}", "--format=%H|%ai|%s"],
            cwd=str(root_path),
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []
        commits: list[dict[str, str]] = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({"hash": parts[0][:8], "date": parts[1], "message": parts[2]})
        return commits
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Workspace file reader (safe, bounded)
# ---------------------------------------------------------------------------

SAFE_READ_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml", ".jsonl", ".py", ".js", ".ts"}
SAFE_READ_DIRS = {"docs", "config", "state/logs", "workspace"}
BLOCKED_PATTERNS = {".env", "secrets", "credentials", "api_key", "token"}


def safe_read_file(file_path: str, *, root: Optional[Path] = None, max_chars: int = 4000) -> dict[str, Any]:
    """Read a workspace file safely. Returns content or error."""
    root_path = Path(root or ROOT).resolve()
    try:
        resolved = Path(file_path).resolve()
    except Exception:
        return {"error": f"Invalid path: {file_path}", "content": ""}

    # Must be under the project root
    try:
        resolved.relative_to(root_path)
    except ValueError:
        return {"error": "Path is outside the project directory.", "content": ""}

    # Block sensitive patterns
    name_lower = resolved.name.lower()
    for blocked in BLOCKED_PATTERNS:
        if blocked in name_lower:
            return {"error": f"Reading files matching '{blocked}' is not allowed.", "content": ""}

    # Check extension
    if resolved.suffix.lower() not in SAFE_READ_EXTENSIONS:
        return {"error": f"File type '{resolved.suffix}' is not in the safe-read list.", "content": ""}

    if not resolved.exists():
        return {"error": f"File does not exist: {file_path}", "content": ""}

    if not resolved.is_file():
        return {"error": f"Not a file: {file_path}", "content": ""}

    try:
        content = resolved.read_text(encoding="utf-8")
        truncated = len(content) > max_chars
        return {
            "path": str(resolved.relative_to(root_path)),
            "content": content[:max_chars],
            "truncated": truncated,
            "size_bytes": len(content.encode("utf-8")),
            "error": "",
        }
    except Exception as exc:
        return {"error": f"Read error: {exc}", "content": ""}


# ---------------------------------------------------------------------------
# Master context assembly
# ---------------------------------------------------------------------------

def assemble_runtime_context(root: Optional[Path] = None) -> str:
    """Build a compact text summary of current runtime state for LLM injection."""
    root_path = Path(root or ROOT).resolve()
    parts: list[str] = []

    # Pending approvals
    approvals = read_pending_approvals(root=root_path)
    if approvals:
        parts.append(f"PENDING APPROVALS ({len(approvals)}):")
        for a in approvals[:5]:
            parts.append(f"  - {a['approval_id']} for task {a['task_id']}: {a['summary'][:100]}")
    else:
        parts.append("PENDING APPROVALS: none")

    # Pending reviews
    reviews = read_pending_reviews(root=root_path)
    if reviews:
        parts.append(f"PENDING REVIEWS ({len(reviews)}):")
        for r in reviews[:5]:
            parts.append(f"  - {r['review_id']} for task {r['task_id']}: {r['summary'][:100]}")
    else:
        parts.append("PENDING REVIEWS: none")

    # Task status summary
    task_data = read_tasks_by_status(root=root_path, limit=50)
    counts = task_data["status_counts"]
    parts.append(f"TASK STATUS: {task_data['total_tasks']} total — " +
                 ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))

    # Failed tasks
    failed = task_data["by_status"].get("failed", [])
    if failed:
        parts.append(f"FAILED TASKS ({len(failed)}):")
        for f_task in failed[:3]:
            parts.append(f"  - {f_task['task_id']}: {f_task['summary'][:80]} | error: {f_task['last_error'][:100]}")

    # Queued tasks
    queued = task_data["by_status"].get("queued", [])
    if queued:
        parts.append(f"QUEUED TASKS ({len(queued)}):")
        for q in queued[:3]:
            parts.append(f"  - {q['task_id']}: {q['summary'][:80]}")

    # Agent statuses
    agents = read_agent_statuses(root=root_path)
    if agents:
        parts.append(f"AGENT STATUS ({len(agents)}):")
        for ag in agents:
            parts.append(f"  - {ag['agent_id']}: {ag['state']} — {ag['headline'][:80]}")

    # Recent events
    events = read_recent_events(root=root_path, limit=8)
    if events:
        parts.append(f"RECENT EVENTS ({len(events)}):")
        for ev in events[:5]:
            parts.append(f"  - [{ev['event_kind']}] {ev['actor']}: {ev['summary'][:80]} ({ev['created_at'][:19]})")

    # Recent git
    commits = read_recent_git_activity(root=root_path, limit=5)
    if commits:
        parts.append("RECENT COMMITS:")
        for c in commits:
            parts.append(f"  - {c['hash']} {c['message'][:80]}")

    return "\n".join(parts)
