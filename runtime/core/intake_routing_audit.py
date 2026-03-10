#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path("/home/rollan/.openclaw/workspace/jarvis-v5")
RUNTIME = ROOT / "runtime"

KEYWORDS = {
    "task_intake": ["task:", "task", "create_task", "insert into tasks", "tasks.db", "pending", "queued"],
    "routing": ["route", "router", "dispatch", "classify", "manual_followup=ops_report", "local_executor"],
    "approval": ["approval", "approved_task_id", "write_gate", "allowlist_only", "apply_live"],
    "qwen": ["qwen", "candidate", "patch_plan", "scope_apply", "live_apply"],
}

def scan_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    hits = {}
    for group, needles in KEYWORDS.items():
        found = [n for n in needles if n.lower() in text.lower()]
        if found:
            hits[group] = found
    return {
        "path": str(path),
        "hits": hits,
        "size": len(text),
    }

def main() -> int:
    files = []
    for p in sorted(RUNTIME.rglob("*.py")):
        files.append(scan_file(p))

    interesting = [f for f in files if f["hits"]]
    out = {
        "ok": True,
        "runtime_root": str(RUNTIME),
        "interesting_file_count": len(interesting),
        "interesting_files": interesting,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
