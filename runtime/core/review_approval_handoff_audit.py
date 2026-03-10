#!/usr/bin/env python3
import json
from pathlib import Path

FILES = {
    "review_store": Path("/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/review_store.py"),
    "approval_store": Path("/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/approval_store.py"),
    "task_store": Path("/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/task_store.py"),
}

NEEDLES = {
    "review_store": [
        "request_review",
        "latest_review_for_task",
        "Review approved:",
        "TaskStatus.WAITING_REVIEW.value",
        "TaskStatus.WAITING_APPROVAL.value",
        "TaskStatus.READY_TO_SHIP.value",
        "TaskStatus.COMPLETED.value",
        "task.approval_required",
    ],
    "approval_store": [
        "request_approval",
        "latest_approval_for_task",
        "Approval granted:",
        "TaskStatus.WAITING_APPROVAL.value",
        "TaskStatus.READY_TO_SHIP.value",
        "TaskStatus.QUEUED.value",
        "task.final_outcome",
    ],
    "task_store": [
        "VALID_TRANSITIONS",
        "TaskStatus.WAITING_REVIEW.value",
        "TaskStatus.WAITING_APPROVAL.value",
        "TaskStatus.READY_TO_SHIP.value",
        "TaskStatus.COMPLETED.value",
        "def transition_task(",
    ],
}

def scan(path: Path, needles: list[str]) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    matches = []
    for i, line in enumerate(lines, 1):
        for needle in needles:
            if needle in line:
                matches.append({
                    "line": i,
                    "needle": needle,
                    "text": line[:240],
                })
                break
    return {
        "path": str(path),
        "match_count": len(matches),
        "matches": matches[:80],
    }

def main() -> int:
    payload = {
        "ok": True,
        "files": {name: scan(path, NEEDLES[name]) for name, path in FILES.items()},
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
