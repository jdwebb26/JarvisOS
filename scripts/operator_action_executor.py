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
from runtime.core.approval_store import load_approval
from runtime.core.review_store import load_review
from runtime.memory.governance import load_memory_candidate
from scripts.operator_action_ledger import (
    latest_successful_action_for_action_id,
    save_execution_record,
)
from scripts.operator_checkpoint_action_pack import resolve_action_pack


def _base_record(
    *,
    action_id: str,
    action: dict[str, Any] | None,
    action_pack_path: Path,
    dry_run: bool,
    invoked_by: str,
) -> dict[str, Any]:
    command = action.get("command", {}) if action else {}
    return {
        "execution_id": new_id("opexec"),
        "action_id": action_id,
        "invoked_by": invoked_by,
        "selected_action": action,
        "source_action_pack_path": str(action_pack_path),
        "source_action_pack_id": None,
        "source_action_pack_fingerprint": None,
        "source_action_pack_validation_status": "",
        "source_action_pack_resolution": "",
        "source_action_pack_rebuild_reason": "",
        "source_action_pack_requested_explicit": False,
        "command_argv": list(command.get("argv", [])),
        "command_string": str(command.get("command", "")),
        "started_at": now_iso(),
        "completed_at": None,
        "success": False,
        "failure": False,
        "failure_kind": "",
        "failure_reason": "",
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


def revalidate_selected_action(root: Path, *, action: dict[str, Any]) -> tuple[bool, str, str]:
    category = str(action.get("category") or "")
    verb = str(action.get("verb") or "")
    target_id = str(action.get("target_id") or "")

    if category == "pending_review":
        review = load_review(target_id, root=root)
        if review is None:
            return False, "stale_action", f"Review {target_id} no longer exists."
        if review.status != "pending":
            return False, "stale_action", f"Review {target_id} is `{review.status}` and is no longer pending."
        return True, "ok", "Review is still pending."

    if category == "pending_approval":
        approval = load_approval(target_id, root=root)
        if approval is None:
            return False, "stale_action", f"Approval {target_id} no longer exists."
        if approval.status != "pending":
            return False, "stale_action", f"Approval {target_id} is `{approval.status}` and is no longer pending."
        return True, "ok", "Approval is still pending."

    if category == "memory_candidate":
        memory_candidate = load_memory_candidate(target_id, root=root)
        if memory_candidate is None:
            return False, "stale_action", f"Memory candidate {target_id} no longer exists."
        if memory_candidate.lifecycle_state != "candidate":
            return (
                False,
                "stale_action",
                f"Memory candidate {target_id} is `{memory_candidate.lifecycle_state}` and cannot accept `{verb}`.",
            )
        if memory_candidate.decision_status != "candidate":
            return (
                False,
                "stale_action",
                f"Memory candidate {target_id} already has decision `{memory_candidate.decision_status}`.",
            )
        if verb == "promote":
            if memory_candidate.superseded_by_memory_candidate_id:
                return False, "stale_action", f"Memory candidate {target_id} is already superseded."
            if memory_candidate.contradiction_status == "contradicted":
                return False, "stale_action", f"Memory candidate {target_id} is already contradicted."
        return True, "ok", "Memory candidate is still actionable."

    if category == "artifact_followup" and verb in {"inspect", "inspect_artifact_json"}:
        return True, "ok", "Artifact inspection remains informational and allowed."

    return True, "ok", "No wrapper-level stale-action rule blocked this action."


def execute_selected_action(
    root: Path,
    *,
    action_id: str,
    action: dict[str, Any],
    action_pack_path: Path,
    invoked_by: str = "executor",
    dry_run: bool = False,
    force: bool = False,
    source_action_pack_id: str | None = None,
    source_action_pack_fingerprint: str | None = None,
    source_action_pack_validation_status: str = "valid",
    source_action_pack_resolution: str = "current",
    source_action_pack_rebuild_reason: str = "",
    source_action_pack_requested_explicit: bool = False,
) -> tuple[dict[str, Any], int]:
    record = _base_record(
        action_id=action_id,
        action=action,
        action_pack_path=action_pack_path,
        dry_run=dry_run,
        invoked_by=invoked_by,
    )
    record["source_action_pack_id"] = source_action_pack_id
    record["source_action_pack_fingerprint"] = source_action_pack_fingerprint
    record["source_action_pack_validation_status"] = source_action_pack_validation_status
    record["source_action_pack_resolution"] = source_action_pack_resolution
    record["source_action_pack_rebuild_reason"] = source_action_pack_rebuild_reason
    record["source_action_pack_requested_explicit"] = source_action_pack_requested_explicit

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
        record["failure_kind"] = "already_executed"
        record["failure_reason"] = stderr_snapshot
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

    allowed, failure_kind, failure_reason = revalidate_selected_action(root, action=action)
    if not allowed:
        _complete_record(
            record,
            success=False,
            return_code=1,
            ack_summary="",
            stdout_snapshot="",
            stderr_snapshot=failure_reason,
        )
        record["failure_kind"] = failure_kind
        record["failure_reason"] = failure_reason
        save_execution_record(root, record)
        payload = {
            "ok": False,
            "action_id": action_id,
            "action_pack_path": str(action_pack_path),
            "selected_action": action,
            "command_run": action["command"],
            "failure": {
                "error": failure_reason,
                "kind": failure_kind,
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
        record["failure_kind"] = "command_failed"
        record["failure_reason"] = str(detail_payload.get("stderr", "") or detail_payload.get("stdout", "") or detail_payload)
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
    parser.add_argument("--action-pack-path", default="", help="Explicit action pack JSON path to use without rebuilding")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    explicit_pack_path = Path(args.action_pack_path).resolve() if args.action_pack_path else None
    pack, pack_path, pack_meta, pack_error = resolve_action_pack(
        root,
        limit=args.limit,
        explicit_pack_path=explicit_pack_path,
    )
    if pack_error is not None or pack is None:
        failure_kind = "expired_pack" if pack_meta.get("status") == "expired" else "pinned_pack_validation_failed"
        record = _base_record(
            action_id=args.action_id,
            action=None,
            action_pack_path=pack_path,
            dry_run=args.dry_run,
            invoked_by="executor",
        )
        record["source_action_pack_validation_status"] = pack_meta.get("status", "")
        record["source_action_pack_resolution"] = pack_meta.get("resolution", "")
        record["source_action_pack_rebuild_reason"] = pack_meta.get("rebuild_reason") or ""
        record["source_action_pack_requested_explicit"] = bool(pack_meta.get("requested_explicit"))
        _complete_record(
            record,
            success=False,
            return_code=1,
            ack_summary="",
            stdout_snapshot="",
            stderr_snapshot=pack_error or "Unable to load action pack.",
        )
        record["failure_kind"] = failure_kind
        record["failure_reason"] = pack_error or "Unable to load action pack."
        save_execution_record(root, record)
        payload = {
            "ok": False,
            "error": pack_error or "Unable to load action pack.",
            "failure": {
                "kind": failure_kind,
                "error": pack_error or "Unable to load action pack.",
            },
            "action_id": args.action_id,
            "action_pack_path": str(pack_path),
            "action_pack_validation": pack_meta,
            "execution_record": record,
        }
        print(json.dumps(payload, indent=2))
        return 1
    action = pack.get("action_index", {}).get(args.action_id)
    if action is None:
        record = _base_record(
            action_id=args.action_id,
            action=None,
            action_pack_path=pack_path,
            dry_run=args.dry_run,
            invoked_by="executor",
        )
        record["source_action_pack_id"] = pack.get("action_pack_id")
        record["source_action_pack_fingerprint"] = pack.get("action_pack_fingerprint")
        record["source_action_pack_validation_status"] = pack_meta.get("status", "")
        record["source_action_pack_resolution"] = pack_meta.get("resolution", "")
        record["source_action_pack_rebuild_reason"] = pack_meta.get("rebuild_reason") or ""
        record["source_action_pack_requested_explicit"] = bool(pack_meta.get("requested_explicit"))
        _complete_record(
            record,
            success=False,
            return_code=1,
            ack_summary="",
            stdout_snapshot="",
            stderr_snapshot=f"Action id not found: {args.action_id}",
        )
        record["failure_kind"] = "action_not_found"
        record["failure_reason"] = f"Action id not found: {args.action_id}"
        save_execution_record(root, record)
        payload = {
            "ok": False,
            "error": f"Action id not found: {args.action_id}",
            "action_id": args.action_id,
            "action_pack_path": str(pack_path),
            "action_pack_validation": pack_meta,
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
        source_action_pack_id=pack.get("action_pack_id"),
        source_action_pack_fingerprint=pack.get("action_pack_fingerprint"),
        source_action_pack_validation_status=pack_meta.get("status", "valid"),
        source_action_pack_resolution=pack_meta.get("resolution", "current"),
        source_action_pack_rebuild_reason=pack_meta.get("rebuild_reason") or "",
        source_action_pack_requested_explicit=bool(pack_meta.get("requested_explicit")),
    )
    payload["action_pack_validation"] = pack_meta
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
