#!/usr/bin/env python3
import sqlite3
from pathlib import Path

DB = Path("/home/rollan/.openclaw/workspace/tasks/tasks.db")


def get_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


def pick_order_column(columns: list[str]) -> str:
    for name in ("created_at", "updated_at", "id"):
        if name in columns:
            return name
    return "rowid"


def main() -> int:
    if not DB.exists():
        print(f"[ERROR] Database not found: {DB}")
        return 1

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    try:
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "tasks" not in tables:
            print("[ERROR] No 'tasks' table found in database.")
            return 2

        columns = get_columns(conn, "tasks")
        wanted = ["id", "title", "status", "priority", "created_at"]
        selected = [c for c in wanted if c in columns]

        if not selected:
            print("[ERROR] None of the expected columns exist in 'tasks'.")
            print("Available columns:", ", ".join(columns))
            return 3

        order_col = pick_order_column(columns)
        sql = (
            f"SELECT {', '.join(selected)} "
            f"FROM tasks ORDER BY {order_col} DESC LIMIT 10"
        )

        rows = conn.execute(sql).fetchall()

        print(f"DB: {DB}")
        print(f"Rows: {len(rows)}")
        print("")

        if not rows:
            print("No tasks found.")
            return 0

        for row in rows:
            task_id = row["id"] if "id" in row.keys() else "?"
            title = row["title"] if "title" in row.keys() else ""
            status = row["status"] if "status" in row.keys() else ""
            priority = row["priority"] if "priority" in row.keys() else ""
            created_at = row["created_at"] if "created_at" in row.keys() else ""

            title = str(title).replace("\n", " ").strip()
            if len(title) > 100:
                title = title[:97] + "..."

            print(
                f"- id={task_id} | status={status} | priority={priority} | "
                f"created_at={created_at} | title={title}"
            )

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
