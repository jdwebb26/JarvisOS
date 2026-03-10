#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operator_triage_support import build_reply_plan, resolve_decision_inbox


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview exactly what a compact operator reply would do.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--reply", required=True, help='Reply string such as "A1 X2"')
    args = parser.parse_args()

    root = Path(args.root).resolve()
    inbox, _ = resolve_decision_inbox(root)
    plan = build_reply_plan(root, reply_string=args.reply)
    payload = {
        "ok": plan.get("ok", False),
        "normalized_reply_tokens": plan.get("normalized_tokens", []),
        "matched_inbox_items": [step.get("inbox_item_id") for step in plan.get("steps", [])],
        "blocked_or_unknown_tokens": plan.get("unknown_tokens", []),
        "steps": [
            {
                "reply_code": step.get("reply_code"),
                "operation_kind": step.get("planned_operation_kind"),
                "task_id": step.get("task_id"),
                "action_id": step.get("action_id"),
                "requires_pack_refresh_first": step.get("requires_pack_refresh_first"),
                "suggested_command": step.get("suggested_command"),
            }
            for step in plan.get("steps", [])
        ],
        "any_stale_items": any(item.get("stale_risk") == "high" for item in inbox.get("items", [])),
        "pack_refresh_recommended_first": inbox.get("pack_status") != "valid",
        "plan": plan,
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
