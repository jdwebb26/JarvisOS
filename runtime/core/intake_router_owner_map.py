#!/usr/bin/env python3
import json, re
from pathlib import Path

FILES = [
    Path("/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/intake.py"),
    Path("/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/decision_router.py"),
    Path("/home/rollan/.openclaw/workspace/jarvis-v5/runtime/core/models.py"),
]

PATTERNS = {
    "task_trigger": [r"task:", r"create_task", r"insert", r"tasks?\.db"],
    "routing": [r"route", r"router", r"dispatch", r"classify", r"executor"],
    "approval": [r"approval", r"approved_task_id", r"write_gate", r"apply_live"],
    "statuses": [r"queued", r"pending", r"running", r"done", r"blocked"],
}

def scan(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    out = {"path": str(path), "matches": {}}
    for group, pats in PATTERNS.items():
        found = []
        for i, line in enumerate(lines, 1):
            low = line.lower()
            if any(re.search(p, low) for p in pats):
                found.append({"line": i, "text": line[:220]})
        if found:
            out["matches"][group] = found[:20]
    return out

def main() -> int:
    payload = {
        "ok": True,
        "files": [scan(f) for f in FILES],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
