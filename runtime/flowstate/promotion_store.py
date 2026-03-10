#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.approval_store import request_approval


def flowstate_dir(root: Optional[Path] = None) -> Path:
    base = root or ROOT
    path = base / "state" / "flowstate_sources"
    path.mkdir(parents=True, exist_ok=True)
    return path


def source_path(source_id: str, root: Optional[Path] = None) -> Path:
    return flowstate_dir(root) / f"{source_id}.json"


def load_source(source_id: str, root: Optional[Path] = None) -> Optional[dict]:
    path = source_path(source_id, root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_source(record: dict, root: Optional[Path] = None) -> dict:
    record["updated_at"] = record.get("updated_at") or record.get("created_at")
    source_path(record["source_id"], root).write_text(
        json.dumps(record, indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def request_flowstate_promotion(
    *,
    source_id: str,
    target_task_id: str,
    requested_by: str,
    requested_reviewer: str,
    summary: str,
    root: Optional[Path] = None,
) -> dict:
    source = load_source(source_id, root=root)
    if source is None:
        raise ValueError(f"Flowstate source not found: {source_id}")

    approval = request_approval(
        task_id=target_task_id,
        approval_type="flowstate_promotion",
        requested_by=requested_by,
        requested_reviewer=requested_reviewer,
        lane="flowstate",
        summary=summary,
        details=f"Promotion requested from Flowstate source {source_id}",
        root=root,
    )

    if approval["approval_id"] if isinstance(approval, dict) else False:
        pass

    source.setdefault("promotion_request_ids", [])
    source["promotion_request_ids"].append(approval.approval_id)
    source["processing_status"] = "awaiting_promotion_approval"
    source["updated_at"] = source.get("updated_at") or source.get("created_at")
    save_source(source, root=root)

    return {
        "source_id": source_id,
        "task_id": target_task_id,
        "approval_id": approval.approval_id,
        "requested_reviewer": approval.requested_reviewer,
        "processing_status": source["processing_status"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Request approval-gated promotion from Flowstate into a task lane.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--source-id", required=True, help="Flowstate source id")
    parser.add_argument("--target-task-id", required=True, help="Target task id")
    parser.add_argument("--requested-by", default="operator", help="Requester")
    parser.add_argument("--requested-reviewer", default="anton", help="Reviewer")
    parser.add_argument("--summary", required=True, help="Promotion summary")
    args = parser.parse_args()

    result = request_flowstate_promotion(
        source_id=args.source_id,
        target_task_id=args.target_task_id,
        requested_by=args.requested_by,
        requested_reviewer=args.requested_reviewer,
        summary=args.summary,
        root=Path(args.root).resolve(),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
