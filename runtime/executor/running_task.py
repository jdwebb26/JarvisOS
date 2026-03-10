#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.task_queue import list_running_tasks


def pick_oldest_running_task(*, root: Path) -> Optional[dict]:
    running = list_running_tasks(root=root)
    if not running:
        return None
    running.sort(key=lambda row: row["created_at"])
    return running[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect currently running tasks.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--pick", action="store_true", help="Return only the oldest running task")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    if args.pick:
        result = pick_oldest_running_task(root=root)
    else:
        result = {"running": list_running_tasks(root=root)}

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
