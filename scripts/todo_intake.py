#!/usr/bin/env python3
"""todo_intake — Direct task creation from #todo messages without a Jarvis turn.

Accepts a plain-text todo, wraps it as a `task:` trigger, routes it through
the standard intake pipeline, and emits a Discord confirmation event.

Small tasks enqueue directly for Ralph. No LLM turn needed.

Usage:
    # CLI
    python3 scripts/todo_intake.py "Summarize the latest NQ regime brief"
    python3 scripts/todo_intake.py "Fix the SearXNG query encoding bug" --lane hal

    # Programmatic
    from scripts.todo_intake import submit_todo
    result = submit_todo("Summarize the latest NQ regime brief")
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


from runtime.core.intake import create_task_from_message_result
from runtime.core.task_store import load_task as _load_task
from runtime.core.task_runtime import save_task as _save_task
from runtime.core.discord_event_router import emit_event
from runtime.core.models import new_id


def submit_todo(
    text: str,
    *,
    user: str = "operator",
    lane: str = "jarvis",
    channel: str = "todo",
    message_id: str = "",
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Submit a todo item as a durable task.

    Wraps the text with `task:` prefix if not already present,
    runs it through the standard intake pipeline, and emits
    a Discord confirmation event.

    Returns the intake result dict with added `todo_intake` metadata.
    """
    resolved_root = Path(root or ROOT).resolve()
    raw = text.strip()
    if not raw:
        return {"ok": False, "error": "empty todo text"}

    # Ensure task: prefix
    if not raw.lower().startswith("task:"):
        raw = f"task: {raw}"

    if not message_id:
        message_id = new_id("todo")

    # --- Create the task via standard intake ---
    result = create_task_from_message_result(
        text=raw,
        user=user,
        lane=lane,
        channel=channel,
        message_id=message_id,
        root=resolved_root,
    )

    # Tag the result
    result["todo_intake"] = True
    result["source_channel"] = channel

    # --- Re-assign to ralph_adapter for immediate pickup ---
    # Standard intake routes to qwen_executor/qwen_planner, which Ralph only
    # steals after 1 hour. For #todo tasks that aren't deploy/high_stakes,
    # override to ralph_adapter so Ralph picks them up on the next cycle.
    if result.get("task_created"):
        task_id = result.get("task_id", "")
        risk = result.get("risk_level", "normal")
        ttype = result.get("task_type", "general")
        if ttype != "deploy" and risk != "high_stakes" and task_id:
            try:
                task_rec = _load_task(task_id, root=resolved_root)
                if task_rec and task_rec.status == "queued":
                    task_rec.execution_backend = "ralph_adapter"
                    _save_task(resolved_root, task_rec)
                    result["execution_backend_override"] = "ralph_adapter"
            except Exception:
                pass  # Non-fatal: task still exists, just won't be immediate

    # --- Emit Discord confirmation ---
    if result.get("task_created"):
        task_id = result.get("task_id", "")
        task_type = result.get("task_type", "general")
        short = result.get("short_summary", raw)[:80]
        try:
            emit_event(
                "task_created", "jarvis",
                task_id=task_id,
                detail=f"[todo] {short}",
                root=resolved_root,
            )
        except Exception:
            pass

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Submit a #todo item directly as a durable task.",
    )
    parser.add_argument("text", nargs="?", default="", help="Todo text (or use --text)")
    parser.add_argument("--text", dest="text_flag", default="", help="Todo text (alternative)")
    parser.add_argument("--user", default="operator")
    parser.add_argument("--lane", default="jarvis")
    parser.add_argument("--channel", default="todo")
    parser.add_argument("--message-id", default="")
    parser.add_argument("--json", action="store_true", help="Print full JSON result")
    args = parser.parse_args()

    todo_text = args.text or args.text_flag
    if not todo_text:
        parser.error("Provide todo text as positional arg or --text")

    result = submit_todo(
        todo_text,
        user=args.user,
        lane=args.lane,
        channel=args.channel,
        message_id=args.message_id,
    )

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        if result.get("task_created"):
            tid = result["task_id"]
            ttype = result.get("task_type", "?")
            status = result.get("final_status", result.get("initial_status", "?"))
            model = result.get("assigned_model", "?")
            print(f"\u2705 Task created: {tid}")
            print(f"   type={ttype}  status={status}  model={model}")
            print(f"   {result.get('short_summary', '')[:80]}")
        elif result.get("kind") == "duplicate_task_existing":
            print(f"\u26a0\ufe0f  Duplicate: {result.get('existing_task_id')} ({result.get('existing_status')})")
        elif result.get("error"):
            print(f"\u274c {result['error']}")
        else:
            print(f"\u274c Task not created: {result.get('message', 'unknown')}")

    return 0 if result.get("task_created") or result.get("kind") == "duplicate_task_existing" else 1


if __name__ == "__main__":
    raise SystemExit(main())
