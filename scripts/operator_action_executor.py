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

from runtime.core.models import new_id, now_iso
from scripts.operator_action_ledger import (
    latest_successful_action_for_action_id,
    save_execution_record,
)
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


def _base_record(*, action_id: str, action: dict[str, Any] | None, action_pack_path: Path, dry_run: bool) -> dict[str, Any]:
    command = action.get("command", {}) if action else {}
    return {
        "execution_id": new_id("opexec"),
        "action_id": action_id,
        "selected_action": action,
        "source_action_pack_path": str(action_pack_path),
        "command_argv": list(command.get("argv", [])),
        "command_string": str(command.get("command", "")),
        "started_at": now_iso(),
        "completed_at": None,
        "success": False,
        "failure": False,
        "dry_run": dry_run,
        "return_code": None,
        "ack_summary": "",
        "stdout_snapshot": "",
        "stderr_snapshot": "",
    }


def _complete_record(
    record: dict[str, Any],
    *,
    success: bool,
    return_code: int,
    ack_summary: str,
    stdout_snapshot: str,
    stderr_snapshot: str,
) -> dict[str, Any]:
    record["completed_at"] = now_iso()
    record["success"] = success
    record["failure"] = not success
    record["return_code"] = return_code
    record["ack_summary"] = ack_summary
    record["stdout_snapshot"] = stdout_snapshot
    record["stderr_snapshot"] = stderr_snapshot
    return record


def _execute_action(action: dict[str, Any]) -> dict[str, Any]:
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
        "return_code": completed.returncode,
    }


def execute_selected_action(
    root: Path,
    *,
    action_id: str,
    action: dict[str, Any],
    action_pack_path: Path,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[dict[str, Any], int]:
    record = _base_record(
        action_id=action_id,
        action=action,
        action_pack_path=action_pack_path,
        dry_run=dry_run,
    )

    previous_success = None if dry_run else latest_successful_action_for_action_id(root, action_id)
    if previous_success is not None and not force:
        stderr_snapshot = (
            "Action already has a successful non-dry-run execution record. "
            f"Use --force to re-execute action_id `{action_id}`."
        )
        _complete_record(
            record,
            success=False,
            return_code=1,
            ack_summary="",
            stdout_snapshot="",
            stderr_snapshot=stderr_snapshot,
        )
        save_execution_record(root, record)
        payload = {
            "ok": False,
            "action_id": action_id,
            "action_pack_path": str(action_pack_path),
            "selected_action": action,
            "command_run": action["command"],
            "failure": {
                "error": stderr_snapshot,
                "kind": "already_executed",
                "prior_execution_id": previous_success.get("execution_id"),
            },
            "execution_record": record,
        }
        return payload, 1

    if dry_run:
        _complete_record(
            record,
            success=True,
            return_code=0,
            ack_summary="Dry run only. Command was resolved but not executed.",
            stdout_snapshot="",
            stderr_snapshot="",
        )
        save_execution_record(root, record)
        payload = {
            "ok": True,
            "dry_run": True,
            "action_id": action_id,
            "action_pack_path": str(action_pack_path),
            "selected_action": action,
            "command_run": action["command"],
            "ack_summary": record["ack_summary"],
            "execution_record": record,
        }
        return payload, 0

    try:
        execution = _execute_action(action)
    except Exception as exc:
        detail = str(exc)
        try:
            detail_payload = json.loads(detail)
        except Exception:
            detail_payload = {"error": detail}
        _complete_record(
            record,
            success=False,
            return_code=int(detail_payload.get("returncode", 1)),
            ack_summary="",
            stdout_snapshot=str(detail_payload.get("stdout", "")),
            stderr_snapshot=str(detail_payload.get("stderr", "")),
        )
        save_execution_record(root, record)
        payload = {
            "ok": False,
            "action_id": action_id,
            "action_pack_path": str(action_pack_path),
            "selected_action": action,
            "command_run": action["command"],
            "failure": detail_payload,
            "execution_record": record,
        }
        return payload, 1

    _complete_record(
        record,
        success=True,
        return_code=execution["return_code"],
        ack_summary=execution["ack_summary"],
        stdout_snapshot=execution["stdout_text"],
        stderr_snapshot=execution["stderr_text"],
    )
    save_execution_record(root, record)
    payload = {
        "ok": True,
        "action_id": action_id,
        "action_pack_path": str(action_pack_path),
        **execution,
        "dry_run": False,
        "execution_record": record,
    }
    return payload, 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute one operator checkpoint action by stable action id.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--action-id", required=True, help="Stable action id from the checkpoint action pack")
    parser.add_argument("--limit", type=int, default=10, help="Action-pack rebuild limit if the pack is missing")
    parser.add_argument("--dry-run", action="store_true", help="Resolve and log the action without executing the command")
    parser.add_argument("--force", action="store_true", help="Re-execute an action even if it already succeeded previously")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    pack, pack_path = _load_or_build_action_pack(root, limit=args.limit)
    action = pack.get("action_index", {}).get(args.action_id)
    if action is None:
        record = _base_record(
            action_id=args.action_id,
            action=None,
            action_pack_path=pack_path,
            dry_run=args.dry_run,
        )
        _complete_record(
            record,
            success=False,
            return_code=1,
            ack_summary="",
            stdout_snapshot="",
            stderr_snapshot=f"Action id not found: {args.action_id}",
        )
        save_execution_record(root, record)
        payload = {
            "ok": False,
            "error": f"Action id not found: {args.action_id}",
            "action_id": args.action_id,
            "action_pack_path": str(pack_path),
            "execution_record": record,
        }
        print(json.dumps(payload, indent=2))
        return 1

    payload, exit_code = execute_selected_action(
        root,
        action_id=args.action_id,
        action=action,
        action_pack_path=pack_path,
        dry_run=args.dry_run,
        force=args.force,
    )
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
