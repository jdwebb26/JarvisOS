#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _safe_load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_output_board(*, root: Path, limit: int = 50) -> dict:
    out_dir = root / "workspace" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for path in out_dir.glob("*.json"):
        record = _safe_load(path)
        if not record:
            continue
        rows.append(
            {
                "output_id": record.get("output_id"),
                "task_id": record.get("task_id"),
                "artifact_id": record.get("artifact_id"),
                "title": record.get("title"),
                "summary": record.get("summary"),
                "published_at": record.get("published_at"),
                "published_by": record.get("published_by"),
                "lane": record.get("lane"),
                "status": record.get("status"),
                "markdown_path": record.get("markdown_path"),
            }
        )

    rows.sort(key=lambda row: row.get("published_at", ""), reverse=True)
    rows = rows[:limit]

    result = {
        "rows": rows,
        "total": len(rows),
    }

    out_path = root / "state" / "logs" / "output_board.json"
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the outputs board.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=50, help="Max number of rows")
    args = parser.parse_args()

    result = build_output_board(root=Path(args.root).resolve(), limit=args.limit)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
