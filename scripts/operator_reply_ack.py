#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import (
    build_operator_reply_ack_data,
    build_operator_reply_ack_markdown,
    triage_logs_dir,
)


def build_operator_reply_ack(root: Path, *, limit: int = 5) -> dict[str, str | dict]:
    payload = build_operator_reply_ack_data(root, limit=limit, allow_inbox_rebuild=False)
    logs = triage_logs_dir(root)
    json_path = logs / "operator_reply_ack_latest.json"
    markdown_path = logs / "operator_reply_ack_latest.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(build_operator_reply_ack_markdown(payload), encoding="utf-8")
    return {"pack": payload, "json_path": str(json_path), "markdown_path": str(markdown_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a compact reply acknowledgement artifact from the latest ingress/apply state.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    result = build_operator_reply_ack(Path(args.root).resolve(), limit=args.limit)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
