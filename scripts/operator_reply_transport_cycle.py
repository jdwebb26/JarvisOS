#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import new_id, now_iso
from scripts.operator_handoff_pack import build_operator_handoff_pack
from scripts.operator_outbound_prompt import build_operator_outbound_prompt
from scripts.operator_reply_ack import build_operator_reply_ack
from scripts.operator_reply_ingress_runner import run_reply_ingress_batch
from scripts.operator_triage_support import save_reply_transport_cycle_record


def run_operator_reply_transport_cycle(
    root: Path,
    *,
    limit: int,
    apply: bool,
    preview: bool,
    dry_run: bool,
    continue_on_failure: bool,
    refresh_handoff: bool,
) -> tuple[dict[str, object], int]:
    started_at = now_iso()
    outbound = build_operator_outbound_prompt(root, limit=min(limit, 5))
    ingress_payload, ingress_exit = run_reply_ingress_batch(
        root,
        limit=limit,
        apply=apply,
        preview=preview,
        dry_run=dry_run,
        continue_on_failure=continue_on_failure,
    )
    ack = build_operator_reply_ack(root, limit=min(limit, 5))
    handoff = None
    record = {
        "transport_cycle_id": new_id("opreplycycle"),
        "started_at": started_at,
        "completed_at": now_iso(),
        "ok": bool(ingress_payload.get("ok")),
        "mode": "apply" if apply else "preview" if preview else "plan",
        "dry_run": dry_run,
        "continue_on_failure": continue_on_failure,
        "outbound_prompt_path": outbound["json_path"],
        "reply_ingress_run_id": (ingress_payload.get("run") or {}).get("run_id"),
        "reply_ack_path": ack["json_path"],
        "handoff_refreshed": refresh_handoff,
        "handoff_path": None if handoff is None else handoff["json_path"],
        "outbound_prompt_pack_id": (outbound.get("pack") or {}).get("pack_id"),
        "reply_ack_result_kind": ((ack.get("pack") or {}).get("latest_reply_received") or {}).get("result_kind"),
        "attempted_count": (ingress_payload.get("run") or {}).get("attempted_count", 0),
        "applied_count": (ingress_payload.get("run") or {}).get("applied_count", 0),
        "blocked_count": (ingress_payload.get("run") or {}).get("blocked_count", 0),
        "ignored_count": (ingress_payload.get("run") or {}).get("ignored_count", 0),
        "invalid_count": (ingress_payload.get("run") or {}).get("invalid_count", 0),
        "stop_reason": (ingress_payload.get("run") or {}).get("stop_reason", ""),
        "processed_ingress_ids": list((ingress_payload.get("run") or {}).get("processed_ingress_ids", [])),
        "processed_message_paths": [row.get("message_path") for row in ingress_payload.get("processed_messages", []) if row.get("message_path")],
        "processed_source_message_ids": [
            row.get("source_message_id") for row in ingress_payload.get("processed_messages", []) if row.get("source_message_id")
        ],
    }
    save_reply_transport_cycle_record(root, record)
    handoff = build_operator_handoff_pack(root, limit=max(limit, 5)) if refresh_handoff else None
    if handoff is not None:
        record["handoff_path"] = handoff["json_path"]
        save_reply_transport_cycle_record(root, record)
    payload = {
        "ok": record["ok"],
        "transport_cycle": record,
        "outbound_prompt": outbound,
        "reply_ingress_run": ingress_payload,
        "reply_ack": ack,
        "handoff": handoff,
    }
    return payload, 0 if record["ok"] else ingress_exit


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded file-backed operator reply transport cycle.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=10, help="Maximum inbound messages to process")
    parser.add_argument("--apply", action="store_true", help="Apply replies through the existing wrapper path")
    parser.add_argument("--preview", action="store_true", help="Preview replies instead of planning only")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run the apply path")
    parser.add_argument("--continue-on-failure", action="store_true", help="Continue through blocked/failed inbound rows")
    parser.add_argument("--no-refresh-handoff", action="store_true", help="Skip the final explicit handoff refresh")
    args = parser.parse_args()

    payload, exit_code = run_operator_reply_transport_cycle(
        Path(args.root).resolve(),
        limit=args.limit,
        apply=args.apply,
        preview=args.preview,
        dry_run=args.dry_run,
        continue_on_failure=args.continue_on_failure,
        refresh_handoff=not args.no_refresh_handoff,
    )
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
