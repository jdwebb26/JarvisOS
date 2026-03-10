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
    apply: bool,
    preview: bool,
    dry_run: bool,
    continue_on_failure: bool,
    refresh_handoff: bool,
) -> tuple[dict[str, Any], int]:
    readiness = gateway_operator_bridge_readiness(root, allow_inbox_rebuild=False, limit=min(limit, 5))
    outbound = build_operator_outbound_packet(root, limit=min(limit, 5))
    imported_rows: list[dict[str, Any]] = []
    if import_from_folder:
        folder = operator_gateway_inbound_messages_dir(root)
        for path in sorted(folder.glob("*.json"))[:limit]:
            payload = _load_json(path)
            if payload is None or payload.get("imported_at"):
                continue
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
    handoff = None if refresh_handoff else build_operator_handoff_pack(root, limit=max(limit, 5))
    record = {
        "bridge_cycle_id": new_id("opbridge"),
        "started_at": now_iso(),
        "completed_at": now_iso(),
        "ok": bool(transport_payload.get("ok")),
        "bridge_ready": readiness["bridge_ready"],
        "outbound_packet_id": (outbound.get("packet") or {}).get("outbound_packet_id"),
        "imported_count": len(imported_rows),
        "imported_reply_message_ids": [row.get("import_id") for row in imported_rows],
        "reply_transport_cycle_id": ((transport_payload.get("transport_cycle") or {}).get("transport_cycle_id")),
        "reply_ack_result_kind": ((ack.get("pack") or {}).get("latest_reply_received") or {}).get("result_kind"),
        "handoff_refreshed": refresh_handoff,
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
