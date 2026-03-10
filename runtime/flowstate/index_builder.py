#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_approval(approvals_dir: Path, approval_id: str) -> dict | None:
    path = approvals_dir / f"{approval_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _effective_processing_status(source_record: dict, approvals_dir: Path) -> str:
    approval_ids = source_record.get("promotion_request_ids", [])
    for approval_id in reversed(approval_ids):
        approval = _load_approval(approvals_dir, approval_id)
        if not approval:
            continue
        if approval.get("status") == "pending":
            return "awaiting_promotion_approval"
    return source_record.get("processing_status", "unknown")


def build_flowstate_index(root: Path) -> dict:
    source_dir = root / "state" / "flowstate_sources"
    approvals_dir = root / "state" / "approvals"
    source_dir.mkdir(parents=True, exist_ok=True)

    items = []
    raw_sources = []

    for path in sorted(source_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if "source_id" not in record:
            continue

        raw_sources.append(record)

    artifact_dir = source_dir / "artifacts"
    distillations = {}
    if artifact_dir.exists():
        for path in sorted(artifact_dir.glob("*.json")):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if row.get("artifact_type") != "flowstate_distillation":
                continue
            distillations[row.get("artifact_id")] = row

    for record in raw_sources:
        latest_id = record.get("latest_distillation_artifact_id")
        candidate_action_count = 0
        if latest_id and latest_id in distillations:
            candidate_action_count = len(distillations[latest_id].get("candidate_actions", []))

        items.append(
            {
                "source_id": record.get("source_id"),
                "title": record.get("title"),
                "source_type": record.get("source_type"),
                "processing_status": _effective_processing_status(record, approvals_dir),
                "created_by": record.get("created_by"),
                "extraction_artifact_present": bool(record.get("extraction_artifact_id")),
                "distillation_artifact_present": bool(record.get("latest_distillation_artifact_id")),
                "candidate_action_count": candidate_action_count,
                "promotion_request_ids": record.get("promotion_request_ids", []),
                "updated_at": record.get("updated_at"),
            }
        )

    counts = {
        "total_sources": len(items),
        "awaiting_promotion_approval": sum(
            1 for item in items if item["processing_status"] == "awaiting_promotion_approval"
        ),
        "ingested_only": sum(1 for item in items if item["processing_status"] == "ingested"),
        "extracted": sum(1 for item in items if item["processing_status"] == "extracted"),
        "distilled": sum(1 for item in items if item["processing_status"] == "distilled"),
    }

    index = {
        "counts": counts,
        "items": items,
    }

    out_path = source_dir / "index.json"
    out_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Flowstate index file.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    index = build_flowstate_index(root)
    print(json.dumps(index, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
