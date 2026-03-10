#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import build_decision_manifest_data, build_decision_manifest_markdown, triage_logs_dir


def build_operator_decision_manifest(root: Path, *, limit: int = 10) -> dict[str, str | dict]:
    pack = build_decision_manifest_data(root, limit=limit)
    logs = triage_logs_dir(root)
    json_path = logs / "operator_decision_manifest.json"
    markdown_path = logs / "operator_decision_manifest.md"
    json_path.write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(build_decision_manifest_markdown(pack), encoding="utf-8")
    return {"pack": pack, "json_path": str(json_path), "markdown_path": str(markdown_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a bounded operator decision manifest.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=10, help="Maximum recent items")
    args = parser.parse_args()

    payload = build_operator_decision_manifest(Path(args.root).resolve(), limit=args.limit)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
