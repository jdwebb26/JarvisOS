#!/usr/bin/env python3
import argparse
import json
import sqlite3
from pathlib import Path

WORKSPACE = Path("/home/rollan/.openclaw/workspace")
TASK_DB = WORKSPACE / "tasks" / "tasks.db"
RESULTS_DIR = WORKSPACE / "tasks" / "results"


def scope_decision(task: dict) -> dict:
    title = str(task.get("title", "") or "").lower()
    status = str(task.get("status", "") or "").lower()
    priority = task.get("priority", 0)
    kind = str(task.get("kind", "") or "").lower()
    notes = str(task.get("notes", "") or "").lower()
    payload_path = str(task.get("payload_path", "") or "").strip()

    reasons: list[str] = []
    allowed = True

    positive_signals: list[str] = []
    if "strategy factory" in title or "nq sf" in title:
        positive_signals.append("strategy-factory workflow")
    if any(tok in title for tok in ["p1.", "p2.", "phase", "step"]):
        positive_signals.append("structured phase/step naming")
    if any(tok in title for tok in ["implement", "build", "create"]):
        positive_signals.append("implementation-oriented title")

    has_impl_shape = len(positive_signals) >= 2

    if status and status not in {"pending", "running", "done", "completed"}:
        allowed = False
        reasons.append(f"unexpected status={status}")

    try:
        prio = int(priority)
        if prio < 5:
            allowed = False
            reasons.append(f"priority too low ({priority})")
    except Exception:
        reasons.append(f"non-integer priority={priority}")

    if "helper" in title or "stub" in notes:
        allowed = False
        reasons.append("generic helper/stub task")

    if "smoke test" in title and not has_impl_shape:
        allowed = False
        reasons.append("generic smoke test without strong implementation signals")

    if not positive_signals:
        allowed = False
        reasons.append("missing structured implementation signals")

    if not payload_path:
        reasons.append("no payload_path present")

    if kind and kind not in {"prompt", "plan", "task", "strategy_factory"}:
        reasons.append(f"unrecognized kind={kind}")

    return {
        "allowed": allowed,
        "positive_signals": positive_signals,
        "reasons": reasons,
    }


def read_recent_tasks(limit: int) -> list[dict]:
    if not TASK_DB.exists():
        raise FileNotFoundError(f"Database not found: {TASK_DB}")

    conn = sqlite3.connect(str(TASK_DB))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        if row is None:
            raise RuntimeError("No 'tasks' table found in database.")

        pragma_rows = conn.execute("PRAGMA table_info(tasks)").fetchall()
        cols = [r["name"] if "name" in r.keys() else r[1] for r in pragma_rows]
        order_col = "created_at" if "created_at" in cols else ("updated_at" if "updated_at" in cols else "id")
        rows = conn.execute(
            f"SELECT * FROM tasks ORDER BY {order_col} DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{col: r[col] for col in r.keys()} for r in rows]
    finally:
        conn.close()


def read_result_preview(task_id: int, max_chars: int = 1200) -> dict:
    path = RESULTS_DIR / f"{task_id}.md"
    if not path.exists() or not path.is_file():
        return {
            "path": str(path),
            "exists": False,
            "preview": "",
        }

    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": str(path.relative_to(WORKSPACE)),
        "exists": True,
        "preview": text[:max_chars],
        "truncated": len(text) > max_chars,
        "total_chars": len(text),
    }


def choose_top_candidate(tasks: list[dict]) -> tuple[dict | None, dict | None]:
    allowed: list[tuple[dict, dict]] = []
    for task in tasks:
        decision = scope_decision(task)
        if decision["allowed"]:
            allowed.append((task, decision))

    if not allowed:
        return None, None

    def sort_key(item: tuple[dict, dict]):
        task, decision = item
        try:
            priority = int(task.get("priority", 0) or 0)
        except Exception:
            priority = 0
        task_id = int(task.get("id", 0) or 0)
        return (priority, len(decision["positive_signals"]), task_id)

    allowed.sort(key=sort_key, reverse=True)
    return allowed[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only live Qwen bridge for recent task triage.")
    parser.add_argument("--limit", type=int, default=20, help="How many recent tasks to scan.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    tasks = read_recent_tasks(args.limit)
    task, decision = choose_top_candidate(tasks)

    if task is None:
        payload = {
            "ok": True,
            "workspace": str(WORKSPACE),
            "scanned": len(tasks),
            "candidate_found": False,
            "message": "No in-scope task candidates found.",
        }
        print(json.dumps(payload, indent=2))
        return 0

    result = read_result_preview(int(task["id"]))

    payload = {
        "ok": True,
        "workspace": str(WORKSPACE),
        "scanned": len(tasks),
        "candidate_found": True,
        "task_id": task.get("id"),
        "title": task.get("title"),
        "status": task.get("status"),
        "priority": task.get("priority"),
        "kind": task.get("kind"),
        "payload_path": task.get("payload_path"),
        "scope": decision,
        "result": result,
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print("Qwen Live Bridge")
    print(f"Workspace : {WORKSPACE}")
    print(f"Scanned   : {len(tasks)} recent tasks")
    print("")
    print(f"Top candidate: task {task.get('id')}")
    print(f"Title       : {task.get('title')}")
    print(f"Status      : {task.get('status')}")
    print(f"Priority    : {task.get('priority')}")
    print(f"Kind        : {task.get('kind')}")
    print(f"Payload     : {task.get('payload_path')}")
    print("")
    print("Why in scope:")
    for item in decision["positive_signals"]:
        print(f"- {item}")
    if decision["reasons"]:
        print("")
        print("Other notes:")
        for item in decision["reasons"]:
            print(f"- {item}")
    print("")
    print(f"Result artifact: {result['path']}")
    if result["exists"]:
        print("")
        print("Result preview:")
        print(result["preview"])
    else:
        print("No result file found.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
