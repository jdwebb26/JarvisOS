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
from scripts.operator_handoff_pack import build_operator_handoff_pack
from scripts.operator_publish_outbound_packet import build_operator_outbound_packet
from scripts.operator_reply_ack import build_operator_reply_ack
from scripts.operator_reply_transport_cycle import run_operator_reply_transport_cycle
from scripts.operator_triage_support import (
    gateway_operator_bridge_readiness,
    import_gateway_reply_message,
    operator_gateway_inbound_messages_dir,
    save_bridge_cycle_record,
)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def run_operator_bridge_cycle(
    root: Path,
    *,
    limit: int,
    import_from_folder: bool,
    import_paths: list[Path] | None,
    apply: bool,
    preview: bool,
    dry_run: bool,
    continue_on_failure: bool,
    refresh_handoff: bool,
) -> tuple[dict[str, Any], int]:
    started_at = now_iso()
    readiness = gateway_operator_bridge_readiness(root, allow_inbox_rebuild=False, limit=min(limit, 5))
    outbound = build_operator_outbound_packet(root, limit=min(limit, 5))
    imported_rows: list[dict[str, Any]] = []
    if import_from_folder:
        paths = import_paths or sorted(operator_gateway_inbound_messages_dir(root).glob("*.json"))[:limit]
        for path in paths:
            payload = _load_json(path)
            if payload is None or payload.get("imported_at"):
                continue
            payload["gateway_message_path"] = str(path)
            imported = import_gateway_reply_message(root, payload=payload)
            payload["imported_at"] = now_iso()
            payload["import_id"] = imported.get("import_id")
            payload["classification"] = imported.get("classification")
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            imported_rows.append(imported)

    transport_payload, exit_code = run_operator_reply_transport_cycle(
        root,
        limit=limit,
        apply=apply,
        preview=preview,
        dry_run=dry_run,
        continue_on_failure=continue_on_failure,
        refresh_handoff=refresh_handoff,
    )
    ack = build_operator_reply_ack(root, limit=min(limit, 5))
    handoff = build_operator_handoff_pack(root, limit=max(limit, 5)) if refresh_handoff else None
    record = {
        "bridge_cycle_id": new_id("opbridge"),
        "started_at": started_at,
        "completed_at": now_iso(),
        "ok": bool(transport_payload.get("ok")),
        "mode": "apply" if apply else "preview" if preview else "plan",
        "dry_run": dry_run,
        "continue_on_failure": continue_on_failure,
        "bridge_ready": readiness["bridge_ready"],
        "outbound_packet_id": (outbound.get("packet") or {}).get("outbound_packet_id"),
        "outbound_packet_path": outbound.get("json_path"),
        "outbound_packet_pack_id": ((outbound.get("packet") or {}).get("pack_id")),
        "imported_count": len(imported_rows),
        "imported_reply_message_ids": [row.get("import_id") for row in imported_rows],
        "imported_source_message_ids": [row.get("source_message_id") for row in imported_rows if row.get("source_message_id")],
        "imported_gateway_message_paths": [row.get("gateway_message_path") for row in imported_rows if row.get("gateway_message_path")],
        "imported_rows": [
            {
                "import_id": row.get("import_id"),
                "source_message_id": row.get("source_message_id"),
                "source_kind": row.get("source_kind"),
                "source_lane": row.get("source_lane"),
                "source_channel": row.get("source_channel"),
                "source_user": row.get("source_user"),
                "raw_text": row.get("raw_text"),
                "classification": row.get("classification"),
                "apply": row.get("apply", False),
                "preview": row.get("preview", False),
                "dry_run": row.get("dry_run", False),
                "continue_on_failure": row.get("continue_on_failure", False),
                "gateway_message_path": row.get("gateway_message_path"),
                "reply_message_path": row.get("reply_message_path"),
                "imported": row.get("imported", False),
            }
            for row in imported_rows
        ],
        "reply_transport_cycle_id": ((transport_payload.get("transport_cycle") or {}).get("transport_cycle_id")),
        "reply_transport_attempted_count": ((transport_payload.get("transport_cycle") or {}).get("attempted_count", 0)),
        "reply_transport_blocked_count": ((transport_payload.get("transport_cycle") or {}).get("blocked_count", 0)),
        "reply_ack_result_kind": ((ack.get("pack") or {}).get("latest_reply_received") or {}).get("result_kind"),
        "reply_ack_path": ack.get("json_path"),
        "handoff_refreshed": refresh_handoff,
        "handoff_path": None if handoff is None else handoff.get("json_path"),
        "stop_reason": (transport_payload.get("transport_cycle") or {}).get("stop_reason", ""),
    }
    save_bridge_cycle_record(root, record)
    payload = {
        "ok": record["ok"],
        "bridge_cycle": record,
        "outbound_packet": outbound,
        "imported_messages": imported_rows,
        "reply_transport_cycle": transport_payload,
        "reply_ack": ack,
        "handoff": handoff,
    }
    return payload, 0 if payload["ok"] else exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded gateway/operator bridge cycle over the existing reply transport path.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--import-from-folder", action="store_true", help="Import gateway-style inbound rows from the file-backed source folder")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-failure", action="store_true")
    parser.add_argument("--no-refresh-handoff", action="store_true")
    args = parser.parse_args()

    payload, exit_code = run_operator_bridge_cycle(
        Path(args.root).resolve(),
        limit=args.limit,
        import_from_folder=args.import_from_folder,
        import_paths=None,
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
