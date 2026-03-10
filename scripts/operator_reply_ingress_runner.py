#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import new_id, now_iso
from scripts.operator_triage_support import (
    list_reply_ingress_runs,
    operator_reply_messages_dir,
    save_reply_ingress_run,
    ingest_operator_reply,
)


def _load_message(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_message(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_reply_ingress_batch(
    root: Path,
    *,
    limit: int,
    apply: bool,
    preview: bool,
    dry_run: bool,
    continue_on_failure: bool,
) -> tuple[dict[str, Any], int]:
    mode = "apply" if apply else "preview" if preview else "plan"
    message_dir = operator_reply_messages_dir(root)
    files = sorted(message_dir.glob("*.json"))
    run = {
        "run_id": new_id("opreplyrun"),
        "started_at": now_iso(),
        "completed_at": None,
        "ok": True,
        "attempted_count": 0,
        "succeeded_count": 0,
        "ignored_count": 0,
        "invalid_count": 0,
        "blocked_count": 0,
        "applied_count": 0,
        "processed_ingress_ids": [],
        "stop_reason": "",
    }
    processed: list[dict[str, Any]] = []

    for path in files:
        message = _load_message(path)
        if message is None:
            continue
        if message.get("processed_at"):
            continue
        payload, exit_code = ingest_operator_reply(
            root,
            raw_text=str(message.get("raw_text", "")),
            source_kind=str(message.get("source_kind", "file")),
            source_lane=str(message.get("source_lane", "operator")),
            source_channel=str(message.get("source_channel", path.parent.name)),
            source_message_id=str(message.get("source_message_id", path.stem)),
            source_user=str(message.get("source_user", "operator")),
            mode="apply" if bool(message.get("apply", apply)) else "preview" if bool(message.get("preview", preview)) else mode,
            dry_run=bool(message.get("dry_run", dry_run)),
            continue_on_failure=bool(message.get("continue_on_failure", continue_on_failure)),
            force_duplicate=bool(message.get("force_duplicate", False)),
        )
        ingress_record = payload.get("ingress_record", {})
        result_kind = payload.get("result_kind", "")
        run["attempted_count"] += 1
        if result_kind == "ignored_non_reply":
            run["ignored_count"] += 1
        elif result_kind == "invalid_reply":
            run["invalid_count"] += 1
            run["ok"] = False
            run["blocked_count"] += 1
        elif result_kind in {"missing_inbox", "stale_inbox", "pack_refresh_required", "blocked", "duplicate_message"}:
            run["blocked_count"] += 1
            if result_kind != "duplicate_message":
                run["ok"] = False
        elif result_kind == "applied":
            run["applied_count"] += 1
            run["succeeded_count"] += 1 if payload.get("ok") else 0
            if not payload.get("ok"):
                run["blocked_count"] += 1
                run["ok"] = False
        else:
            run["succeeded_count"] += 1 if payload.get("ok") else 0
            if not payload.get("ok") and exit_code != 0:
                run["blocked_count"] += 1
                run["ok"] = False
        if ingress_record.get("ingress_id"):
            run["processed_ingress_ids"].append(ingress_record["ingress_id"])
        processed.append(
            {
                "message_path": str(path),
                "source_message_id": message.get("source_message_id", path.stem),
                "ingress_id": ingress_record.get("ingress_id"),
                "result_kind": result_kind,
                "ok": payload.get("ok", False),
            }
        )
        message["processed_at"] = now_iso()
        message["ingress_id"] = ingress_record.get("ingress_id")
        message["result_kind"] = result_kind
        _save_message(path, message)
        if len(processed) >= limit:
            break
        if exit_code != 0 and not continue_on_failure:
            run["stop_reason"] = result_kind or "ingress_failure"
            break

    run["completed_at"] = now_iso()
    save_reply_ingress_run(root, run)
    payload = {"ok": run["ok"], "run": run, "processed_messages": processed, "recent_run_count": len(list_reply_ingress_runs(root))}
    return payload, 0 if run["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Process a bounded batch of file-backed inbound operator replies.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=10, help="Maximum unprocessed inbound rows to consume")
    parser.add_argument("--apply", action="store_true", help="Apply replies through existing wrappers")
    parser.add_argument("--preview", action="store_true", help="Preview replies instead of only planning them")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run the apply path")
    parser.add_argument("--continue-on-failure", action="store_true", help="Keep processing the batch after a blocked/failed reply")
    args = parser.parse_args()

    payload, exit_code = run_reply_ingress_batch(
        Path(args.root).resolve(),
        limit=args.limit,
        apply=args.apply,
        preview=args.preview,
        dry_run=args.dry_run,
        continue_on_failure=args.continue_on_failure,
    )
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
