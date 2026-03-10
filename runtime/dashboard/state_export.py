#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.dashboard.status_names import normalize_status_name


def _load_jsons(folder: Path) -> list[dict]:
    rows: list[dict] = []
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return rows


def _load_flowstate_source_records(folder: Path) -> list[dict]:
    rows: list[dict] = []
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "source_id" not in row:
            continue
        rows.append(row)
    return rows


def build_state_export(root: Path) -> dict:
    tasks = _load_jsons(root / "state" / "tasks")
    reviews = _load_jsons(root / "state" / "reviews")
    approvals = _load_jsons(root / "state" / "approvals")
    artifacts = _load_jsons(root / "state" / "artifacts")
    outputs = _load_jsons(root / "workspace" / "out")
    flowstate_sources = _load_flowstate_source_records(root / "state" / "flowstate_sources")

    summary = {
        "counts": {
            "tasks": len(tasks),
            "reviews": len(reviews),
            "approvals": len(approvals),
            "artifacts": len(artifacts),
            "outputs": len(outputs),
            "flowstate_sources": len(flowstate_sources),
        },
        "task_status_counts": {},
        "task_lifecycle_counts": {},
        "review_status_counts": {},
        "approval_status_counts": {},
        "artifact_lifecycle_counts": {},
        "output_status_counts": {},
        "flowstate_processing_counts": {},
    }

    for task in tasks:
        status = normalize_status_name(task.get("status", "unknown"))
        lifecycle_state = task.get("lifecycle_state", "unknown")
        summary["task_status_counts"][status] = summary["task_status_counts"].get(status, 0) + 1
        summary["task_lifecycle_counts"][lifecycle_state] = summary["task_lifecycle_counts"].get(lifecycle_state, 0) + 1

    for review in reviews:
        status = review.get("status", "unknown")
        summary["review_status_counts"][status] = summary["review_status_counts"].get(status, 0) + 1

    for approval in approvals:
        status = approval.get("status", "unknown")
        summary["approval_status_counts"][status] = summary["approval_status_counts"].get(status, 0) + 1

    for artifact in artifacts:
        lifecycle_state = artifact.get("lifecycle_state", "unknown")
        summary["artifact_lifecycle_counts"][lifecycle_state] = (
            summary["artifact_lifecycle_counts"].get(lifecycle_state, 0) + 1
        )

    for output in outputs:
        status = output.get("status", "unknown")
        summary["output_status_counts"][status] = summary["output_status_counts"].get(status, 0) + 1

    for source in flowstate_sources:
        status = source.get("processing_status", "unknown")
        summary["flowstate_processing_counts"][status] = summary["flowstate_processing_counts"].get(status, 0) + 1

    out_path = root / "state" / "logs" / "state_export.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a compact state summary for operator handoff/debug.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    summary = build_state_export(root)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
