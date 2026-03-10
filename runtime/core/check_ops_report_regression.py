#!/usr/bin/env python3
import json
import sqlite3
from pathlib import Path

LIVE_FILE = Path("/home/rollan/.openclaw/workspace/tasks/local_executor.py")
TASK_DB = Path("/home/rollan/.openclaw/workspace/tasks/tasks.db")
RESULTS_DIR = Path("/home/rollan/.openclaw/workspace/tasks/results")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    out = {
        "ok": True,
        "live_file_exists": LIVE_FILE.exists(),
        "task_db_exists": TASK_DB.exists(),
        "results_dir_exists": RESULTS_DIR.exists(),
        "checks": {},
        "notes": [],
    }

    if not LIVE_FILE.exists():
        out["ok"] = False
        out["notes"].append(f"missing live file: {LIVE_FILE}")
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 1

    text = read_text(LIVE_FILE)

    checks = {
        "helper_signature": "def build_ops_report_snapshot(limit: int = 8):" in text,
        "counts_query_unfiltered": '"SELECT status, COUNT(*) AS c FROM tasks GROUP BY status"' in text,
        "recent_query_unfiltered": '"SELECT id, title, status, updated_at, created_at FROM tasks ORDER BY COALESCE(updated_at, created_at) DESC LIMIT ?"' in text,
        "callsite_no_task_id": "snapshot = build_ops_report_snapshot()" in text,
        "summary_heading": "## Summary" in text,
        "queue_counts_heading": "## Queue Counts" in text,
        "recent_heading": "## Recently Completed / Updated Tasks" in text,
        "artifact_paths_heading": "## Latest Artifact Paths" in text,
        "attention_heading": "## Attention Items" in text,
        "next_action_heading": "## Next Human/Agent Action" in text,
    }

    out["checks"] = checks
    out["ok"] = all(checks.values())

    if TASK_DB.exists():
        with sqlite3.connect(str(TASK_DB)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, status, result_path FROM tasks WHERE id = 74"
            ).fetchone()
            if row:
                out["task_74"] = {
                    "id": row["id"],
                    "status": row["status"],
                    "result_path": row["result_path"],
                }

    sample_artifacts = sorted(RESULTS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
    out["recent_result_files"] = [str(p) for p in sample_artifacts]

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
