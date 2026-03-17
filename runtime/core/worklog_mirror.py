#!/usr/bin/env python3
"""worklog_mirror — helpers to mirror important status/result events to worklog.

Thin wrapper around discord_event_router.emit_event() that always ensures
a worklog outbox entry is written even if the caller only wants the mirror
side effect without the full event routing machinery.

Usage:
    from runtime.core.worklog_mirror import mirror_to_worklog

    mirror_to_worklog(
        kind="task_completed",
        agent_id="hal",
        task_id="task_abc123",
        detail="implementing backend dispatch fix.",
    )
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import new_id, now_iso
from runtime.core.discord_event_router import (
    _load_channel_map,
    _outbox_dir,
    _render_status_text,
    _write_outbox_entry,
)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def mirror_to_worklog(
    kind: str,
    agent_id: str,
    *,
    task_id: str = "",
    detail: str = "",
    target: str = "",
    artifact_id: str = "",
    reviewer_id: str = "",
    text_override: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Write a worklog outbox entry for an event.

    Returns the outbox entry dict, or None if worklog channel is not configured.
    """
    resolved_root = Path(root or ROOT).resolve()
    channel_map = _load_channel_map(resolved_root)
    worklog_ch = channel_map.get("logical_channels", {}).get("worklog", {}).get("channel_id")
    if not worklog_ch:
        return None

    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "task_id": task_id,
        "detail": detail,
        "target": target,
        "artifact_id": artifact_id,
        "reviewer_id": reviewer_id,
        **(extra or {}),
    }
    text = text_override or _render_status_text(kind, payload)
    event_id = new_id("wlmir")
    return _write_outbox_entry(worklog_ch, text, event_id, kind, "worklog", resolved_root)


def mirror_browser_result(
    agent_id: str,
    task_id: str,
    target_url: str,
    status: str,
    outcome_summary: str,
    *,
    result_id: str = "",
    root: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Convenience: mirror a browser_result event to worklog."""
    status_word = "completed" if status == "ok" else "FAILED"
    detail = f"{status_word}. {outcome_summary}"
    return mirror_to_worklog(
        "browser_result",
        agent_id,
        task_id=task_id,
        target=target_url,
        detail=detail,
        extra={"result_id": result_id},
        root=root,
    )


def mirror_task_event(
    kind: str,
    agent_id: str,
    task_id: str,
    detail: str = "",
    root: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Convenience: mirror a task lifecycle event (started/completed/failed/blocked) to worklog."""
    worklog_mirror_kinds = {
        "task_started", "task_completed", "task_failed", "task_blocked",
        "review_requested", "review_completed",
        "approval_requested", "approval_completed",
        "artifact_promoted",
        "delegation_sent", "delegation_received",
        "warning", "error",
    }
    if kind not in worklog_mirror_kinds:
        return None
    return mirror_to_worklog(kind, agent_id, task_id=task_id, detail=detail, root=root)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Worklog mirror CLI")
    parser.add_argument("kind")
    parser.add_argument("agent_id")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--detail", default="")
    parser.add_argument("--target", default="")
    args = parser.parse_args()

    entry = mirror_to_worklog(
        args.kind, args.agent_id,
        task_id=args.task_id, detail=args.detail, target=args.target,
    )
    print(json.dumps(entry, indent=2) if entry else "worklog channel not configured")
