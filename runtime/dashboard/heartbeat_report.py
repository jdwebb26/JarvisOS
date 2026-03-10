#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import now_iso
from runtime.core.status import summarize_status


def _folder_counts(path: Path) -> dict:
    if not path.exists():
        return {"exists": False, "json_files": 0}
    return {"exists": True, "json_files": len(list(path.glob("*.json")))}


def build_heartbeat_report(root: Path) -> dict:
    logs_dir = root / "state" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    status = summarize_status(root)

    subsystems = {
        "tasks": _folder_counts(root / "state" / "tasks"),
        "events": _folder_counts(root / "state" / "events"),
        "reviews": _folder_counts(root / "state" / "reviews"),
        "approvals": _folder_counts(root / "state" / "approvals"),
        "artifacts": _folder_counts(root / "state" / "artifacts"),
        "outputs": _folder_counts(root / "workspace" / "out"),
        "logs": _folder_counts(logs_dir),
    }

    degraded_signals: list[str] = []
    if status["counts"].get("revoked_outputs", 0):
        degraded_signals.append("revoked_outputs_present")
    if status["counts"].get("revoked_artifacts", 0):
        degraded_signals.append("revoked_artifacts_present")
    if status["counts"].get("blocked", 0):
        degraded_signals.append("blocked_tasks_present")
    for name, info in subsystems.items():
        if not info["exists"]:
            degraded_signals.append(f"missing_{name}_dir")

    heartbeat = {
        "schema_version": "v5.1",
        "generated_at": now_iso(),
        "heartbeat_kind": "jarvis_status_heartbeat",
        "repo_root": str(root),
        "overall_health": "degraded" if degraded_signals else "ok",
        "degraded_signals": degraded_signals,
        "status_counts": status.get("counts", {}),
        "subsystems": subsystems,
        "work_summary": {
            "running": status.get("running_now", []),
            "blocked": status.get("blocked", []),
            "waiting_review": status.get("waiting_review", []),
            "waiting_approval": status.get("waiting_approval", []),
            "ready_to_ship": status.get("ready_to_ship", []),
            "shipped": status.get("shipped", []),
            "impacted_outputs": status.get("impacted_outputs", []),
            "revoked_outputs": status.get("revoked_outputs", []),
            "revoked_artifacts": status.get("revoked_artifacts", []),
        },
        "next_recommended_move": status.get("next_recommended_move", ""),
    }

    out_path = logs_dir / "heartbeat_report.json"
    out_path.write_text(json.dumps(heartbeat, indent=2) + "\n", encoding="utf-8")
    return heartbeat


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a durable repo heartbeat report.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    args = parser.parse_args()

    result = build_heartbeat_report(Path(args.root).resolve())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
