#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


WORKSPACE = Path("/home/rollan/.openclaw/workspace")
ROOT = WORKSPACE / "jarvis-v5"
APPROVAL_PATH = ROOT / "runtime" / "core" / "qwen_approval_state.json"
WRITE_GATE_PATH = ROOT / "runtime" / "core" / "qwen_write_gate.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Arm Qwen control-state files for a real Jarvis task.")
    ap.add_argument("--task-id", required=True, help="Real task id, for example task_cec3239feefb")
    ap.add_argument(
        "--target-path",
        action="append",
        required=True,
        help="Allowed target path. Repeat this flag for multiple files.",
    )
    ap.add_argument("--mode", default="dry_run", choices=["dry_run", "apply_live"])
    ap.add_argument("--approval-note", default="")
    ap.add_argument("--gate-note", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    task_path = ROOT / "state" / "tasks" / f"{args.task_id}.json"
    if not task_path.exists():
        raise SystemExit(f"Task not found: {task_path}")

    allowed_paths = []
    seen = set()
    for raw in args.target_path:
        resolved = str(Path(raw).expanduser().resolve())
        if resolved in seen:
            continue
        if not Path(resolved).exists():
            raise SystemExit(f"Target path does not exist: {resolved}")
        seen.add(resolved)
        allowed_paths.append(resolved)

    approval_payload = {
        "approved_task_id": args.task_id,
        "approved_at": now_iso(),
        "approval_note": args.approval_note,
        "mode": args.mode,
    }

    gate_payload = {
        "enabled": True,
        "mode": "allowlist_only",
        "approved_task_id": args.task_id,
        "allowed_paths": allowed_paths,
        "note": args.gate_note or args.approval_note,
    }

    write_json(APPROVAL_PATH, approval_payload)
    write_json(WRITE_GATE_PATH, gate_payload)

    payload = {
        "ok": True,
        "task_id": args.task_id,
        "mode": args.mode,
        "approval_path": str(APPROVAL_PATH),
        "write_gate_path": str(WRITE_GATE_PATH),
        "allowed_paths": allowed_paths,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
