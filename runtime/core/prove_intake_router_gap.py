#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path("/home/rollan/.openclaw/workspace/jarvis-v5")

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.intake import create_task_from_message
from runtime.core.decision_router import route_task_for_decision
from runtime.core.task_store import load_task

def run_case(text: str, label: str) -> dict:
    created = create_task_from_message(
        text=text,
        user="gap_smoke",
        lane="gap_smoke",
        channel="gap_smoke",
        message_id=label,
        root=ROOT,
    )
    task_id = created.get("task_id")
    before = load_task(task_id, root=ROOT) if task_id else None
    routed = route_task_for_decision(
        task_id=task_id,
        actor="gap_smoke",
        lane="gap_smoke",
        root=ROOT,
    ) if task_id else None
    after = load_task(task_id, root=ROOT) if task_id else None
    return {
        "label": label,
        "input": text,
        "create_result": created,
        "pre_route_status": None if before is None else before.status,
        "pre_route_review_required": None if before is None else before.review_required,
        "pre_route_approval_required": None if before is None else before.approval_required,
        "route_result": routed,
        "post_route_status": None if after is None else after.status,
    }

def main() -> int:
    payload = {
        "ok": True,
        "cases": [
            run_case("task: deploy live production service restart", "deploy_case"),
            run_case("task: patch python function bug in executor", "code_case"),
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
