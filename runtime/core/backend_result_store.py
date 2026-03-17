#!/usr/bin/env python3
"""backend_result_store — compact summaries of completed backend actions.

One JSON file per result in state/backend_results/<result_id>.json.
Lets Jarvis inspect results cheaply without reopening giant artifacts.

Schema:
    result_id   str     — bkres_<hex12>
    created_at  str     — ISO timestamp
    task_id     str
    agent_id    str     — which agent produced/owns this result
    backend     str     — browser_backend | nvidia_executor | hermes | ...
    status      str     — ok | error | partial | blocked
    summary     str     — plain-English one-liner of what happened
    artifact_refs dict  — optional: pointers to larger artifacts on disk
    error       str     — empty string if no error
    extra       dict    — opaque bag for backend-specific fields
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


# ---------------------------------------------------------------------------
# State directory
# ---------------------------------------------------------------------------

def _results_dir(root: Optional[Path] = None) -> Path:
    base = Path(root or ROOT).resolve()
    d = base / "state" / "backend_results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _result_path(result_id: str, root: Optional[Path] = None) -> Path:
    return _results_dir(root) / f"{result_id}.json"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_backend_result(
    task_id: str,
    agent_id: str,
    backend: str,
    status: str,
    summary: str,
    *,
    artifact_refs: Optional[dict[str, Any]] = None,
    error: str = "",
    extra: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Write a compact backend result summary and return the record."""
    result_id = new_id("bkres")
    record: dict[str, Any] = {
        "result_id": result_id,
        "created_at": now_iso(),
        "task_id": task_id,
        "agent_id": agent_id,
        "backend": backend,
        "status": status,
        "summary": summary,
        "artifact_refs": artifact_refs or {},
        "error": error,
        "extra": extra or {},
    }
    path = _result_path(result_id, root)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_result(result_id: str, root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """Return one result record by ID, or None."""
    path = _result_path(result_id, root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def get_latest_result(
    agent_id: str,
    root: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Return the most recently written result for an agent, or None."""
    d = _results_dir(root)
    candidates = []
    for path in d.glob("bkres_*.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            if rec.get("agent_id") == agent_id:
                candidates.append(rec)
        except (json.JSONDecodeError, OSError):
            pass
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.get("created_at", ""))


def get_results_for_task(
    task_id: str,
    root: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return all results for a given task_id, ordered by created_at."""
    d = _results_dir(root)
    results = []
    for path in d.glob("bkres_*.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            if rec.get("task_id") == task_id:
                results.append(rec)
        except (json.JSONDecodeError, OSError):
            pass
    return sorted(results, key=lambda r: r.get("created_at", ""))


def list_recent_results(
    n: int = 20,
    root: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return the N most recent result records across all agents."""
    d = _results_dir(root)
    results = []
    for path in d.glob("bkres_*.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            results.append(rec)
        except (json.JSONDecodeError, OSError):
            pass
    results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return results[:n]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backend result store CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_get = sub.add_parser("get", help="Get one result by ID")
    p_get.add_argument("result_id")

    p_agent = sub.add_parser("agent", help="Latest result for agent")
    p_agent.add_argument("agent_id")

    p_task = sub.add_parser("task", help="All results for task")
    p_task.add_argument("task_id")

    p_list = sub.add_parser("list", help="List recent results")
    p_list.add_argument("--n", type=int, default=10)

    args = parser.parse_args()
    if args.cmd == "get":
        print(json.dumps(get_result(args.result_id), indent=2))
    elif args.cmd == "agent":
        print(json.dumps(get_latest_result(args.agent_id), indent=2))
    elif args.cmd == "task":
        print(json.dumps(get_results_for_task(args.task_id), indent=2))
    elif args.cmd == "list":
        print(json.dumps(list_recent_results(args.n), indent=2))
    else:
        parser.print_help()
