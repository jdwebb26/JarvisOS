#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.task_store import list_tasks
from runtime.dashboard.status_names import normalize_status_name


def build_task_board(root: Path) -> dict:
    tasks = list_tasks(root=root, limit=500)

    rows = []
    for t in tasks:
        rows.append(
            {
                "task_id": t.task_id,
                "summary": t.normalized_request,
                "task_type": t.task_type,
                "status": normalize_status_name(t.status),
                "priority": t.priority,
                "risk_level": t.risk_level,
                "assigned_model": t.assigned_model,
                "review_required": t.review_required,
                "approval_required": t.approval_required,
                "related_review_ids": t.related_review_ids,
                "related_approval_ids": t.related_approval_ids,
                "updated_at": t.updated_at,
            }
        )

    board = {
        "rows": rows,
        "total": len(rows),
    }

    out_path = root / "state" / "logs" / "task_board.json"
    out_path.write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8")
    return board


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a dashboard-friendly task board.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    board = build_task_board(root)
    print(json.dumps(board, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
