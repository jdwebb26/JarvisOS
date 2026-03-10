#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import new_id
from scripts.operator_triage_support import (
    build_operator_outbound_packet_data,
    build_operator_outbound_packet_markdown,
    save_outbound_packet_record,
    triage_logs_dir,
)


def build_operator_outbound_packet(root: Path, *, limit: int = 5) -> dict[str, str | dict]:
    packet = build_operator_outbound_packet_data(root, limit=limit, allow_inbox_rebuild=True)
    record = {"outbound_packet_id": new_id("opoutpkt"), **packet}
    save_outbound_packet_record(root, record)
    logs = triage_logs_dir(root)
    json_path = logs / "operator_outbound_packet_latest.json"
    markdown_path = logs / "operator_outbound_packet_latest.md"
    json_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(build_operator_outbound_packet_markdown(record), encoding="utf-8")
    return {"packet": record, "json_path": str(json_path), "markdown_path": str(markdown_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and persist a compact operator outbound packet.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=5, help="Maximum top reply items to include")
    args = parser.parse_args()

    payload = build_operator_outbound_packet(Path(args.root).resolve(), limit=args.limit)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
