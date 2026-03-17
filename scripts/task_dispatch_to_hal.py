#!/usr/bin/env python3
"""Post queued HAL-eligible tasks to the Discord #hal channel via HAL_WEBHOOK_URL.

Bridges the gap between state/tasks/ and HAL operator/agent visibility.
Idempotent: will not re-post tasks that were already dispatched
(tracked in state/logs/task_dispatch_sent.json).

HAL reply seams (call these commands after completing work):
  Start:     python3 runtime/gateway/task_update.py --task-id <id> --action start --actor hal --lane hal
  Complete:  python3 runtime/gateway/task_update.py --task-id <id> --action complete --actor hal --lane hal --outcome "..."
  Checkpoint:python3 runtime/gateway/task_update.py --task-id <id> --action checkpoint --actor hal --lane hal --note "..."
  Block:     python3 runtime/gateway/task_update.py --task-id <id> --action block --actor hal --lane hal --reason "..."
  Fail:      python3 runtime/gateway/task_update.py --task-id <id> --action fail --actor hal --lane hal --reason "..."
  Ship:      python3 runtime/gateway/task_update.py --task-id <id> --action ready_to_ship --actor hal --lane hal
  Artifact:  python3 runtime/gateway/complete_from_artifact.py --task-id <id> --artifact-id <art_id> --actor hal --lane hal
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import now_iso
from runtime.core.task_store import list_tasks
from scripts.dispatch_utils import load_sent, load_webhook_url, post_webhook, save_sent


SENT_LOG = ROOT / "state" / "logs" / "task_dispatch_sent.json"

HAL_ELIGIBLE_TYPES = {"code", "quant", "general", "research", "analysis"}
# deploy tasks route to anton/approval path — HAL does not dispatch those
HAL_EXCLUDED_TYPES = {"deploy"}


def _format_task_message(task: Any) -> str:
    task_id = task.task_id
    task_type = task.task_type
    model = task.assigned_model or "unassigned"
    request = (task.normalized_request or task.raw_request or "")[:400]
    priority = task.priority or "normal"
    risk = task.risk_level or "normal"

    start_cmd = (
        f"python3 runtime/gateway/task_update.py "
        f"--task-id {task_id} --action start --actor hal --lane hal"
    )
    complete_cmd = (
        f'python3 runtime/gateway/task_update.py '
        f'--task-id {task_id} --action complete --actor hal --lane hal --outcome "Done"'
    )
    artifact_cmd = (
        f"python3 runtime/gateway/complete_from_artifact.py "
        f"--task-id {task_id} --artifact-id <art_id> --actor hal --lane hal"
    )
    return (
        f"**TASK QUEUED** `{task_id}`\n"
        f"Type: **{task_type}** | Priority: {priority} | Risk: {risk} | Model: `{model}`\n"
        f"> {request}\n"
        f"▶ Start: `{start_cmd}`\n"
        f"✅ Complete: `{complete_cmd}`\n"
        f"📦 Artifact: `{artifact_cmd}`"
    )


def run_task_dispatch(root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    tasks = list_tasks(root=root, limit=200)
    queued = [
        t for t in tasks
        if t.status == "queued"
        and t.task_type not in HAL_EXCLUDED_TYPES
    ]

    webhook_url = load_webhook_url("HAL_WEBHOOK_URL", root)
    # Fallback: CREW_WEBHOOK_URL if no dedicated HAL webhook
    if not webhook_url:
        webhook_url = load_webhook_url("CREW_WEBHOOK_URL", root)

    sent = load_sent(SENT_LOG)
    dispatched: list[dict[str, Any]] = []
    skipped: list[str] = []

    for task in queued:
        item_id = task.task_id
        if item_id in sent:
            skipped.append(item_id)
            continue
        msg = _format_task_message(task)
        if dry_run:
            result: dict[str, Any] = {"ok": True, "dry_run": True}
        else:
            result = post_webhook(webhook_url, msg)
        dispatched.append({"id": item_id, "task_type": task.task_type, "result": result})
        if result["ok"]:
            sent.add(item_id)

    if not dry_run:
        save_sent(SENT_LOG, sent)

    return {
        "ok": True,
        "dispatched_count": len(dispatched),
        "skipped_count": len(skipped),
        "queued_count": len(queued),
        "webhook_configured": bool(webhook_url),
        "dry_run": dry_run,
        "dispatched": dispatched,
        "skipped": skipped,
        "generated_at": now_iso(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Post queued HAL-eligible tasks to Discord #hal channel."
    )
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--dry-run", action="store_true", help="Build messages but do not post")
    args = parser.parse_args()

    result = run_task_dispatch(Path(args.root).resolve(), dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
