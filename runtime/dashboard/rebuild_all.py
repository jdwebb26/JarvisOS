#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _run_json_script(script_path: Path, *, root: Path) -> dict:
    cmd = [sys.executable, str(script_path), "--root", str(root)]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    if proc.returncode != 0:
        raise RuntimeError(
            f"{script_path.name} failed with exit {proc.returncode}: "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )

    text = proc.stdout.strip()
    if not text:
        return {}

    return json.loads(text)


def rebuild_all(*, root: Path) -> dict:
    root = root.resolve()

    dashboard_dir = root / "runtime" / "dashboard"
    gateway_dir = root / "runtime" / "gateway"
    flowstate_dir = root / "runtime" / "flowstate"

    errors: list[str] = []

    def run_or_default(path: Path, default: dict) -> dict:
        if not path.exists():
            errors.append(f"missing script: {path}")
            return default
        try:
            return _run_json_script(path, root=root)
        except Exception as exc:
            errors.append(str(exc))
            return default

    operator_snapshot = run_or_default(
        dashboard_dir / "operator_snapshot.py",
        {"counts": {"pending_reviews": 0, "pending_approvals": 0, "flowstate_waiting_promotion": 0}},
    )
    task_board = run_or_default(
        dashboard_dir / "task_board.py",
        {"rows": [], "total": 0},
    )
    event_board = run_or_default(
        dashboard_dir / "event_board.py",
        {"rows": [], "total": 0},
    )
    review_inbox = run_or_default(
        gateway_dir / "review_inbox.py",
        {"pending_reviews": [], "pending_approvals": [], "flowstate_waiting_promotion": []},
    )
    state_export = run_or_default(
        dashboard_dir / "state_export.py",
        {"counts": {}},
    )
    heartbeat_report = run_or_default(
        dashboard_dir / "heartbeat_report.py",
        {"overall_health": "unknown", "status_counts": {}},
    )
    flowstate_index = run_or_default(
        flowstate_dir / "index_builder.py",
        {"counts": {"total_sources": 0, "awaiting_promotion_approval": 0, "ingested_only": 0, "extracted": 0, "distilled": 0}},
    )

    output_board_path = dashboard_dir / "output_board.py"
    output_board = run_or_default(
        output_board_path,
        {"rows": [], "total": 0},
    ) if output_board_path.exists() else {"rows": [], "total": 0}

    result = {
        "ok": len(errors) == 0,
        "status_counts": operator_snapshot.get("status", {}).get("counts", {}),
        "operator_snapshot_counts": operator_snapshot.get("counts", {}),
        "task_board_total": task_board.get("total", 0),
        "event_board_total": event_board.get("total", 0),
        "review_inbox_counts": {
            "pending_reviews": len(review_inbox.get("pending_reviews", [])),
            "pending_approvals": len(review_inbox.get("pending_approvals", [])),
            "flowstate_waiting_promotion": len(review_inbox.get("flowstate_waiting_promotion", [])),
        },
        "state_export_counts": state_export.get("counts", {}),
        "heartbeat_overall_health": heartbeat_report.get("overall_health", "unknown"),
        "heartbeat_status_counts": heartbeat_report.get("status_counts", {}),
        "flowstate_index_counts": flowstate_index.get("counts", {}),
        "output_board_total": output_board.get("total", 0),
        "written_files": [
            str(root / "state" / "logs" / "operator_snapshot.json"),
            str(root / "state" / "logs" / "task_board.json"),
            str(root / "state" / "logs" / "event_board.json"),
            str(root / "state" / "logs" / "review_inbox.json"),
            str(root / "state" / "logs" / "state_export.json"),
            str(root / "state" / "logs" / "heartbeat_report.json"),
            str(root / "state" / "logs" / "output_board.json"),
            str(root / "state" / "flowstate_sources" / "index.json"),
        ],
        "errors": errors,
    }

    out_path = root / "state" / "logs" / "dashboard_rebuild.json"
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild dashboard/state summaries.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    result = rebuild_all(root=Path(args.root).resolve())
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
