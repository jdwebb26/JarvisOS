#!/usr/bin/env python3
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = Path("/home/rollan/.openclaw/workspace")
DB = WORKSPACE / "tasks" / "tasks.db"
LIVE_EXECUTOR = WORKSPACE / "tasks" / "local_executor.py"
RESULTS_DIR = WORKSPACE / "tasks" / "results"
VENV_PY = Path("/home/rollan/.openclaw/workspace/jarvis-v5/.venv-qwen-agent/bin/python")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_result_path(raw_path: str, task_id: int) -> Path:
    if raw_path:
        p = Path(raw_path)
        if p.is_absolute():
            return p
        return WORKSPACE / raw_path
    return RESULTS_DIR / f"{task_id}.md"


def main() -> int:
    if not DB.exists():
        print(json.dumps({"ok": True, "skipped": True, "reason": f"tasks.db not found: {DB}"}, indent=2))
        return 0
    if not LIVE_EXECUTOR.exists():
        print(json.dumps({"ok": True, "skipped": True, "reason": f"local_executor.py not found: {LIVE_EXECUTOR}"}, indent=2))
        return 0
    if not VENV_PY.exists():
        print(json.dumps({"ok": True, "skipped": True, "reason": f"venv python not found: {VENV_PY}"}, indent=2))
        return 0
    if not os.access(DB, os.W_OK):
        print(json.dumps({"ok": True, "skipped": True, "reason": f"tasks.db not writable: {DB}"}, indent=2))
        return 0

    inserted_task_id = None
    inserted_title = f"ops report e2e executor smoke {datetime.now().strftime('%Y%m%d_%H%M%S')}"
    inserted_notes = "manual_followup=ops_report e2e_executor_smoke=1"

    try:
        with sqlite3.connect(str(DB)) as conn:
            conn.row_factory = sqlite3.Row
            cols = [row["name"] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()]

            max_priority = 0
            if "priority" in cols:
                row = conn.execute("SELECT COALESCE(MAX(priority), 0) AS m FROM tasks").fetchone()
                max_priority = int(row["m"] or 0)

            payload = {}
            if "title" in cols:
                payload["title"] = inserted_title
            if "status" in cols:
                payload["status"] = "pending"
            if "notes" in cols:
                payload["notes"] = inserted_notes
            if "priority" in cols:
                payload["priority"] = max_priority + 1000
            if "created_at" in cols:
                payload["created_at"] = now_iso()
            if "updated_at" in cols:
                payload["updated_at"] = now_iso()
            if "payload_path" in cols:
                payload["payload_path"] = ""
            if "result_path" in cols:
                payload["result_path"] = ""
            if "source_channel_id" in cols:
                payload["source_channel_id"] = ""

            required_min = {"title", "status"}
            missing_min = [k for k in required_min if k in cols and k not in payload]
            if missing_min:
                raise RuntimeError(f"Could not satisfy required insert fields: {missing_min}")

            sql = "INSERT INTO tasks ({cols}) VALUES ({vals})".format(
                cols=", ".join(payload.keys()),
                vals=", ".join(["?"] * len(payload)),
            )
            cur = conn.execute(sql, list(payload.values()))
            inserted_task_id = int(cur.lastrowid)
            conn.commit()
    except sqlite3.OperationalError as exc:
        if "readonly" in str(exc).lower():
            print(json.dumps({"ok": True, "skipped": True, "reason": f"readonly tasks.db: {DB}"}, indent=2))
            return 0
        raise

    run = subprocess.run(
        [str(VENV_PY), str(LIVE_EXECUTOR)],
        capture_output=True,
        text=True,
        timeout=120,
    )

    with sqlite3.connect(str(DB)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (inserted_task_id,)).fetchone()
        if row is None:
            raise RuntimeError(f"Inserted task disappeared: {inserted_task_id}")

        row_dict = {k: row[k] for k in row.keys()}
        result_path = resolve_result_path(str(row_dict.get("result_path") or ""), inserted_task_id)

    artifact_exists = result_path.exists()
    preview = ""
    if artifact_exists:
        preview = result_path.read_text(encoding="utf-8", errors="replace")[:2500]

    expected_sections = [
        "## Summary",
        "## Queue Counts",
        "## Recently Completed / Updated Tasks",
        "## Latest Artifact Paths",
        "## Attention Items",
        "## Next Human/Agent Action",
    ]
    found_sections = [s for s in expected_sections if s in preview]

    out = {
        "ok": True,
        "inserted_task_id": inserted_task_id,
        "inserted_title": inserted_title,
        "executor_exit_code": run.returncode,
        "executor_stdout_head": (run.stdout or "")[:1200],
        "executor_stderr_head": (run.stderr or "")[:1200],
        "task_status": row_dict.get("status"),
        "task_result_path": str(result_path),
        "artifact_exists": artifact_exists,
        "found_sections": found_sections,
        "preview_head": preview,
    }

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
