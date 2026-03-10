#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.approval_store import resume_approval_from_checkpoint


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway wrapper for resuming approved work from a stored approval checkpoint.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--approval-id", required=True, help="Approval id")
    parser.add_argument("--actor", default="operator", help="Actor resuming work")
    parser.add_argument("--lane", default="review", help="Lane")
    parser.add_argument("--reason", default="", help="Resume reason")
    args = parser.parse_args()

    result = resume_approval_from_checkpoint(
        approval_id=args.approval_id,
        actor=args.actor,
        lane=args.lane,
        reason=args.reason,
        root=Path(args.root).resolve(),
    )

    ack = {
        "kind": "approval_resume_ack",
        "reply": (
            f"Resumed task `{result['task_id']}` from approval checkpoint `{result['checkpoint_id']}`. "
            f"Task status is now `{result['task_status_after']}`."
        ),
        "approval_id": result["approval_id"],
        "checkpoint_id": result["checkpoint_id"],
        "task_id": result["task_id"],
        "task_status_after": result["task_status_after"],
    }

    print(json.dumps({"result": result, "ack": ack}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
