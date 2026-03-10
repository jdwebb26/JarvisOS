#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import build_command_center_data, build_command_center_markdown, triage_logs_dir


def build_operator_command_center(root: Path, *, limit: int = 10) -> dict[str, str | dict]:
    pack = build_command_center_data(root, limit=limit)
    logs = triage_logs_dir(root)
    json_path = logs / "operator_command_center.json"
    markdown_path = logs / "operator_command_center.md"
    json_path.write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(build_command_center_markdown(pack), encoding="utf-8")
    return {"pack": pack, "json_path": str(json_path), "markdown_path": str(markdown_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the compact operator command-center pack.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=10, help="Maximum recent items to inspect")
    args = parser.parse_args()
    payload = build_operator_command_center(Path(args.root).resolve(), limit=args.limit)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
