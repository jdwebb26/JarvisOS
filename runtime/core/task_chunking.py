#!/usr/bin/env python3
"""task_chunking — Split large tasks into durable child tasks.

When a task's normalized_request is large enough to benefit from decomposition,
this module uses the LLM to split it into smaller subtasks that Ralph can
execute independently.  The parent task tracks its children and rolls up
their completion state.

Flow:
  1. should_chunk(task) → True if request is large/complex
  2. chunk_task(task) → creates child tasks in the store, updates parent
  3. Ralph runs each child independently through the normal HAL/review path
  4. rollup_parent(parent_id) → checks if all children done, marks parent complete
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import TaskRecord, new_id, now_iso
from runtime.core.task_store import create_task, load_task, save_task

log = logging.getLogger("ralph.chunking")

# ── Thresholds ──────────────────────────────────────────────────────────────
# Requests longer than this are candidates for chunking.
CHUNK_CHAR_THRESHOLD = 300
# Requests with more than this many distinct action verbs are candidates.
CHUNK_VERB_THRESHOLD = 3
# Minimum children for a chunk to be valid.
MIN_CHILDREN = 2
# Maximum children to prevent runaway decomposition.
MAX_CHILDREN = 6

_ACTION_VERB_RE = re.compile(
    r"\b(?:implement|create|write|build|add|design|test|validate|fix|refactor|"
    r"deploy|configure|update|remove|integrate|wire|connect|extract|parse|"
    r"generate|compute|calculate|analyze)\b",
    re.IGNORECASE,
)


def _count_action_verbs(text: str) -> int:
    return len(set(_ACTION_VERB_RE.findall(text.lower())))


def should_chunk(task: Any) -> bool:
    """Return True if the task should be decomposed into child tasks."""
    request = task.normalized_request or task.raw_request or ""
    if len(request) < CHUNK_CHAR_THRESHOLD:
        return False
    if task.parent_task_id:
        return False  # Already a child task
    if task.child_task_ids:
        return False  # Already chunked
    verb_count = _count_action_verbs(request)
    return verb_count >= CHUNK_VERB_THRESHOLD


def decompose_request(request: str) -> list[str]:
    """Use the LLM to split a large request into concrete subtasks.

    Returns a list of subtask descriptions.  Falls back to heuristic
    splitting if the LLM call fails.
    """
    import requests as _req

    base = os.getenv("QWEN_AGENT_MODEL_SERVER", "http://100.70.114.34:1234/v1").rstrip("/")
    model = os.getenv("QWEN_AGENT_MODEL", "qwen3.5-35b-a3b")
    api_key = os.getenv("QWEN_AGENT_API_KEY", "lm-studio")

    system_prompt = (
        "You are a task decomposition assistant. Given a large implementation request, "
        "split it into 2-5 concrete, independent subtasks. Each subtask must be self-contained "
        "and executable on its own.\n\n"
        "Output ONLY a JSON array of strings. Each string is one subtask description.\n"
        "Example: [\"Create the data model\", \"Implement the API endpoint\", \"Write unit tests\"]\n"
        "/no_think"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Split this task into subtasks:\n\n{request[:2000]}"},
        ],
        "temperature": 0.0,
        "max_tokens": 1024,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        r = _req.post(f"{base}/chat/completions", headers=headers, json=payload, timeout=(8, 60))
        if not r.ok:
            log.warning("Decompose LLM call failed: HTTP %d", r.status_code)
            return _heuristic_split(request)
        data = r.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        # Extract JSON array from response
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            subtasks = json.loads(match.group())
            if isinstance(subtasks, list) and all(isinstance(s, str) for s in subtasks):
                filtered = [s.strip() for s in subtasks if len(s.strip()) >= 15]
                if MIN_CHILDREN <= len(filtered) <= MAX_CHILDREN:
                    return filtered
        log.warning("Decompose LLM response unparseable, falling back to heuristic")
        return _heuristic_split(request)
    except Exception as exc:
        log.warning("Decompose LLM call failed: %s", exc)
        return _heuristic_split(request)


def _heuristic_split(request: str) -> list[str]:
    """Fallback: split on numbered items or sentence boundaries."""
    # Try numbered list: "1. ...", "2. ..."
    numbered = re.findall(r"(?:^|\n)\s*\d+[.)]\s*(.+?)(?=\n\s*\d+[.)]|\Z)", request, re.DOTALL)
    if len(numbered) >= MIN_CHILDREN:
        return [s.strip() for s in numbered[:MAX_CHILDREN] if len(s.strip()) >= 15]
    # Try splitting on major sentence boundaries
    sentences = [s.strip() for s in re.split(r"[.!]\s+", request) if len(s.strip()) >= 30]
    if len(sentences) >= MIN_CHILDREN:
        return sentences[:MAX_CHILDREN]
    return []


def chunk_task(
    task: Any,
    *,
    root: Path,
    subtask_descriptions: Optional[list[str]] = None,
) -> list[str]:
    """Decompose a parent task into child tasks in the store.

    Returns list of child task_ids.  Updates parent with child_task_ids.
    If subtask_descriptions is provided, uses those instead of calling the LLM.
    """
    if subtask_descriptions is None:
        subtask_descriptions = decompose_request(
            task.normalized_request or task.raw_request or ""
        )

    if len(subtask_descriptions) < MIN_CHILDREN:
        log.info("Chunking skipped: fewer than %d subtasks", MIN_CHILDREN)
        return []

    ts = now_iso()
    child_ids: list[str] = []

    for i, desc in enumerate(subtask_descriptions[:MAX_CHILDREN], 1):
        child = TaskRecord(
            task_id=new_id("task"),
            created_at=ts,
            updated_at=ts,
            source_lane=task.source_lane,
            source_channel=task.source_channel,
            source_message_id=task.source_message_id,
            source_user=task.source_user,
            trigger_type="chunked_subtask",
            raw_request=desc,
            normalized_request=desc,
            task_type=task.task_type,
            status="queued",
            risk_level=task.risk_level,
            execution_backend="ralph_adapter",
            parent_task_id=task.task_id,
            backend_metadata={"chunk_index": i, "chunk_total": len(subtask_descriptions)},
        )
        created = create_task(child, root=root)
        child_ids.append(created.task_id)
        log.info("[CHUNK] Child %d/%d: %s — %s",
                 i, len(subtask_descriptions), created.task_id, desc[:60])

    # Update parent with child refs
    parent = load_task(task.task_id, root=root)
    if parent:
        parent.child_task_ids = child_ids
        parent.backend_metadata = {
            **(parent.backend_metadata or {}),
            "chunked": True,
            "chunk_count": len(child_ids),
        }
        save_task(parent, root=root)

    log.info("[CHUNK] Parent %s → %d children: %s",
             task.task_id, len(child_ids), child_ids)
    return child_ids


def get_children_status(parent_task_id: str, *, root: Path) -> dict[str, Any]:
    """Check completion state of all children of a parent task."""
    parent = load_task(parent_task_id, root=root)
    if not parent or not parent.child_task_ids:
        return {"parent_id": parent_task_id, "has_children": False}

    children = []
    for cid in parent.child_task_ids:
        child = load_task(cid, root=root)
        if child:
            children.append({
                "task_id": child.task_id,
                "status": child.status,
                "final_outcome": (child.final_outcome or "")[:200],
            })

    completed = sum(1 for c in children if c["status"] in ("completed", "waiting_approval"))
    failed = sum(1 for c in children if c["status"] in ("failed", "blocked"))
    pending = len(children) - completed - failed

    return {
        "parent_id": parent_task_id,
        "has_children": True,
        "total": len(children),
        "completed": completed,
        "failed": failed,
        "pending": pending,
        "all_done": pending == 0,
        "all_succeeded": completed == len(children),
        "children": children,
    }


def rollup_parent(parent_task_id: str, *, root: Path) -> dict[str, Any]:
    """Roll up child completion state to the parent task.

    If all children are done (completed/waiting_approval), marks parent completed
    with a rollup summary.  If any child failed, marks parent failed.
    Returns a report dict.
    """
    from runtime.core.task_runtime import complete_task, fail_task

    status = get_children_status(parent_task_id, root=root)
    if not status["has_children"]:
        return {"action": "skip", "reason": "no children"}
    if not status["all_done"]:
        return {"action": "wait", "reason": f"{status['pending']} children still pending"}

    parent = load_task(parent_task_id, root=root)
    if parent is None:
        return {"action": "error", "error": "parent not found"}

    if status["all_succeeded"]:
        outcomes = []
        for child in status["children"]:
            outcomes.append(f"- {child['task_id']}: {child['final_outcome'][:100]}")
        rollup = f"All {status['total']} subtasks completed.\n" + "\n".join(outcomes)
        parent.final_outcome = rollup[:1000]
        parent.backend_metadata = {
            **(parent.backend_metadata or {}),
            "rollup": "all_succeeded",
            "rollup_at": now_iso(),
        }
        save_task(parent, root=root)
        log.info("[ROLLUP] Parent %s: all %d children succeeded", parent_task_id, status["total"])
        return {"action": "completed", "rollup": rollup[:500]}
    else:
        failed_children = [c for c in status["children"] if c["status"] in ("failed", "blocked")]
        reason = f"{status['failed']} of {status['total']} subtasks failed: " + \
                 ", ".join(c["task_id"] for c in failed_children)
        parent.final_outcome = reason[:500]
        parent.status = "failed"
        parent.last_error = reason[:300]
        parent.backend_metadata = {
            **(parent.backend_metadata or {}),
            "rollup": "partial_failure",
            "rollup_at": now_iso(),
        }
        save_task(parent, root=root)
        log.info("[ROLLUP] Parent %s: %d/%d children failed", parent_task_id, status["failed"], status["total"])
        return {"action": "failed", "reason": reason[:500]}
