#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_checkpoint_action_pack import build_operator_checkpoint_action_pack


def _load_or_build_action_pack(root: Path, *, limit: int) -> tuple[dict[str, Any], Path]:
    pack_path = root / "state" / "logs" / "operator_checkpoint_action_pack.json"
    if pack_path.exists():
        try:
            return json.loads(pack_path.read_text(encoding="utf-8")), pack_path
        except Exception:
            pass
    result = build_operator_checkpoint_action_pack(root, limit=limit)
    return result["pack"], Path(result["json_path"])


def _execute_action(root: Path, action: dict[str, Any]) -> dict[str, Any]:
    command = list(action["command"]["argv"])
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )

    stdout_text = completed.stdout.strip()
    stderr_text = completed.stderr.strip()
    stdout_payload: Any = None
    if stdout_text:
        try:
            stdout_payload = json.loads(stdout_text)
        except json.JSONDecodeError:
            stdout_payload = stdout_text

    ack_summary = ""
    if isinstance(stdout_payload, dict):
        if isinstance(stdout_payload.get("ack"), dict):
            ack_summary = str(stdout_payload["ack"].get("reply") or "")
        elif isinstance(stdout_payload.get("reply"), str):
            ack_summary = stdout_payload["reply"]

    if completed.returncode != 0:
        raise RuntimeError(
            json.dumps(
                {
                    "returncode": completed.returncode,
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                }
            )
        )

    return {
        "selected_action": action,
        "command_run": action["command"],
        "stdout_payload": stdout_payload,
        "stdout_text": stdout_text,
        "stderr_text": stderr_text,
        "ack_summary": ack_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute one operator checkpoint action by stable action id.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--action-id", required=True, help="Stable action id from the checkpoint action pack")
    parser.add_argument("--limit", type=int, default=10, help="Action-pack rebuild limit if the pack is missing")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    pack, pack_path = _load_or_build_action_pack(root, limit=args.limit)
    action = pack.get("action_index", {}).get(args.action_id)
    if action is None:
        payload = {
            "ok": False,
            "error": f"Action id not found: {args.action_id}",
            "action_id": args.action_id,
            "action_pack_path": str(pack_path),
        }
        print(json.dumps(payload, indent=2))
        return 1

    try:
        execution = _execute_action(root, action)
    except Exception as exc:
        detail = str(exc)
        try:
            detail_payload = json.loads(detail)
        except Exception:
            detail_payload = {"error": detail}
        payload = {
            "ok": False,
            "action_id": args.action_id,
            "action_pack_path": str(pack_path),
            "selected_action": action,
            "command_run": action["command"],
            "failure": detail_payload,
        }
        print(json.dumps(payload, indent=2))
        return 1

    payload = {
        "ok": True,
        "action_id": args.action_id,
        "action_pack_path": str(pack_path),
        **execution,
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
