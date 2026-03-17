#!/usr/bin/env python3
"""agent_status_store — cheap per-agent "what is happening right now" store.

One JSON file per agent in state/agent_status/<agent_id>.json.
Readable without an LLM. No events, no history — just the latest state.

Schema:
    agent_id        str     — agent identifier
    updated_at      str     — ISO timestamp of last write
    headline        str     — plain-English current status (1 line)
    state           str     — idle | running | waiting | blocked | error
    current_task_id str|null
    last_result     str     — short plain-English summary of last result
    last_result_at  str|null
    extra           dict    — optional opaque bag for caller-specific fields
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import now_iso


# ---------------------------------------------------------------------------
# State directory
# ---------------------------------------------------------------------------

def _status_dir(root: Optional[Path] = None) -> Path:
    base = Path(root or ROOT).resolve()
    d = base / "state" / "agent_status"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _status_path(agent_id: str, root: Optional[Path] = None) -> Path:
    return _status_dir(root) / f"{agent_id}.json"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def update_agent_status(
    agent_id: str,
    headline: str,
    *,
    state: str = "idle",
    current_task_id: Optional[str] = None,
    last_result: str = "",
    last_result_at: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Overwrite the per-agent status file with the latest state.

    Returns the written record as a dict.
    """
    record: dict[str, Any] = {
        "agent_id": agent_id,
        "updated_at": now_iso(),
        "headline": headline,
        "state": state,
        "current_task_id": current_task_id,
        "last_result": last_result,
        "last_result_at": last_result_at,
        "extra": extra or {},
    }
    path = _status_path(agent_id, root)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_agent_status(
    agent_id: str,
    root: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Return the current status record for an agent, or None if absent."""
    path = _status_path(agent_id, root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def get_all_statuses(root: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    """Return a dict of agent_id → status record for all agents with a status file."""
    d = _status_dir(root)
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(d.glob("*.json")):
        agent_id = path.stem
        try:
            result[agent_id] = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Agent status store CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_get = sub.add_parser("get", help="Get status for one agent")
    p_get.add_argument("agent_id")

    p_all = sub.add_parser("all", help="Show all agent statuses")

    p_set = sub.add_parser("set", help="Update agent status")
    p_set.add_argument("agent_id")
    p_set.add_argument("headline")
    p_set.add_argument("--state", default="idle")
    p_set.add_argument("--task-id")

    args = parser.parse_args()
    if args.cmd == "get":
        rec = get_agent_status(args.agent_id)
        print(json.dumps(rec, indent=2) if rec else f"No status for {args.agent_id}")
    elif args.cmd == "all":
        print(json.dumps(get_all_statuses(), indent=2))
    elif args.cmd == "set":
        rec = update_agent_status(
            args.agent_id, args.headline,
            state=args.state, current_task_id=args.task_id,
        )
        print(json.dumps(rec, indent=2))
    else:
        parser.print_help()
