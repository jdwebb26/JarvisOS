"""Auto-promotion — create artifact + promote + publish when a task completes.

Called at the two terminal completion points in the Ralph cycle:
  1. stage_review_to_approval (approval_required=False path)
  2. stage_approval_complete (approval granted path)

Reuses promote_task_result from scripts/promote_output.py.
Idempotent: skips if task already has a promoted_artifact_id or if
the backend result is missing/too short.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("ralph.auto_promote")


def auto_promote_completed_task(task_id: str, *, root: Path) -> str | None:
    """Attempt to auto-promote a completed task's result.

    Returns the artifact_id on success, None if ineligible/already done.
    Never raises — all errors are logged and swallowed so the cycle
    is never broken by promotion failures.
    """
    import sys
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from scripts.promote_output import promote_task_result
    except ImportError:
        log.warning("promote_output not importable — skipping auto-promote")
        return None

    try:
        result = promote_task_result(
            task_id,
            actor="ralph",
            root=root,
        )
    except Exception as exc:
        log.warning("auto_promote failed for %s: %s", task_id, exc)
        return None

    if not result.get("ok"):
        # Not promotable (no result, too short, already promoted, etc.)
        # This is normal — not every task has a promotable backend result.
        reason = result.get("error", "unknown")
        log.info("auto_promote skipped for %s: %s", task_id, reason)
        return None

    artifact_id = result["artifact_id"]
    output_id = result.get("output_id", "?")
    log.info(
        "[AUTO-PROMOTE] task=%s artifact=%s output=%s title=%s",
        task_id, artifact_id, output_id, result.get("title", "")[:60],
    )

    # Emit Discord notification
    try:
        from runtime.core.discord_event_router import emit_event
        emit_event(
            "artifact_auto_promoted", "ralph",
            task_id=task_id,
            artifact_id=artifact_id,
            output_id=output_id,
            detail=f"Auto-promoted: {result.get('title', '')[:60]}",
            root=root,
        )
    except Exception:
        pass

    return artifact_id
