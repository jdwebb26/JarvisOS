#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_source_id() -> str:
    return f"fsrc_{uuid.uuid4().hex[:12]}"


def flowstate_dir(root: Optional[Path] = None) -> Path:
    base = root or ROOT
    path = base / "state" / "flowstate_sources"
    path.mkdir(parents=True, exist_ok=True)
    return path


def source_path(source_id: str, root: Optional[Path] = None) -> Path:
    return flowstate_dir(root) / f"{source_id}.json"


def save_source(record: dict, root: Optional[Path] = None) -> dict:
    record["updated_at"] = now_iso()
    source_path(record["source_id"], root).write_text(
        json.dumps(record, indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def load_source(source_id: str, root: Optional[Path] = None) -> Optional[dict]:
    path = source_path(source_id, root)
    if not path.exists():
        return None

    record = json.loads(path.read_text(encoding="utf-8"))

    # Backward-compatible defaults
    record.setdefault("processing_status", "ingested")
    record.setdefault("distillation_artifact_ids", [])
    record.setdefault("promotion_request_ids", [])
    record.setdefault("extraction_artifact_id", None)
    record.setdefault("latest_distillation_artifact_id", None)
    record.setdefault("version", "v1")

    return record


def list_sources(root: Optional[Path] = None) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(flowstate_dir(root).glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "source_id" not in row:
            continue
        row.setdefault("processing_status", "ingested")
        row.setdefault("distillation_artifact_ids", [])
        row.setdefault("promotion_request_ids", [])
        row.setdefault("extraction_artifact_id", None)
        row.setdefault("latest_distillation_artifact_id", None)
        row.setdefault("version", "v1")
        rows.append(row)
    return rows


def create_source(
    *,
    source_type: str,
    title: str,
    content: str,
    source_ref: str,
    created_by: str,
    root: Optional[Path] = None,
) -> dict:
    source_id = new_source_id()
    record = {
        "source_id": source_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "source_type": source_type,
        "title": title,
        "content": content,
        "source_ref": source_ref,
        "created_by": created_by,
        "processing_status": "ingested",
        "extraction_artifact_id": None,
        "distillation_artifact_ids": [],
        "latest_distillation_artifact_id": None,
        "promotion_request_ids": [],
        "version": "v1",
    }

    save_source(record, root=root)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a durable Flowstate source record.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--source-type", default="note", help="Source type")
    parser.add_argument("--title", required=True, help="Title")
    parser.add_argument("--content", required=True, help="Content")
    parser.add_argument("--source-ref", default="", help="Source reference")
    parser.add_argument("--created-by", default="operator", help="Creator")
    args = parser.parse_args()

    record = create_source(
        source_type=args.source_type,
        title=args.title,
        content=args.content,
        source_ref=args.source_ref,
        created_by=args.created_by,
        root=Path(args.root).resolve(),
    )
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
