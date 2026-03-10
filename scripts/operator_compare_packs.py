#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import compare_action_pack_payloads, current_action_pack_path, load_jsons


def _load_pack(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_packs(root: Path, *, other_pack_path: Path) -> dict:
    current_path = current_action_pack_path(root)
    current_pack = _load_pack(current_path)
    other_pack = _load_pack(other_pack_path)
    referenced_action_ids = {
        row.get("action_id")
        for row in load_jsons(root / "state" / "operator_action_executions")
        if row.get("action_id")
    }
    result = compare_action_pack_payloads(current_pack, other_pack, referenced_action_ids=referenced_action_ids)
    latest_path = root / "state" / "logs" / "operator_compare_packs_latest.json"
    latest_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare the current action pack against another saved action-pack path.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--other-pack-path", required=True, help="Saved action-pack JSON path to compare against")
    args = parser.parse_args()
    payload = compare_packs(Path(args.root).resolve(), other_pack_path=Path(args.other_pack_path).resolve())
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
