#!/usr/bin/env python3
"""run_ralph_v1.py — Entry point for one Ralph v1 cycle.

Usage:
    python3 scripts/run_ralph_v1.py [--root PATH] [--dry-run] [--log-level LEVEL]
    python3 scripts/run_ralph_v1.py --retry TASK_ID

One cycle. One task. One step forward. Stop at approval.
Exit 0 on success or idle. Exit 1 on unhandled error.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Ralph v1 — one bounded autonomy cycle")
    parser.add_argument(
        "--root",
        default=str(ROOT),
        help="Project root path (default: jarvis-v5 root)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run health gates only; do not advance any task",
    )
    parser.add_argument(
        "--retry",
        metavar="TASK_ID",
        help="Requeue a failed/blocked Ralph task for re-execution",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show Ralph's current state, owned tasks, and what needs operator action",
    )
    parser.add_argument(
        "--approve",
        metavar="TASK_ID",
        help="Approve a pending Ralph approval",
    )
    parser.add_argument(
        "--reject",
        metavar="TASK_ID",
        help="Reject a pending Ralph approval",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Reason for --approve or --reject",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    log = logging.getLogger("ralph.v1.main")

    root = Path(args.root).resolve()

    # --status: show Ralph's state
    if args.status:
        from runtime.ralph.agent_loop import ralph_status, _load_env
        _load_env(root)
        status = ralph_status(root)
        print(f"Ralph state: {status['agent_state']}")
        print(f"Headline:    {status['headline']}")
        if status['last_result']:
            print(f"Last result: {status['last_result']}")
        print()
        if status['ralph_tasks']:
            print(f"Owned tasks ({status['total_ralph_tasks']}):")
            for t in status['ralph_tasks']:
                extra = ""
                if t.get("approval_status"):
                    extra = f"  approval={t['approval_status']}"
                if t.get("error"):
                    extra = f"  error={t['error']}"
                print(f"  {t['task_id'][:16]}  {t['status']:<18} {t['type']:<10} {t['request'][:50]}{extra}")
        else:
            print("No Ralph-owned tasks.")
        if status['needs_operator_action']:
            print()
            print("Needs operator action:")
            for a in status['needs_operator_action']:
                if a['action'] == 'approve_or_reject':
                    print(f"  APPROVE/REJECT: {a['task_id'][:16]}  approval={a['approval_id']}")
                    print(f"    {a.get('summary', '')}")
                    print(f"    python3 scripts/run_ralph_v1.py --approve {a['task_id']}")
                elif a['action'] == 'retry_or_dismiss':
                    tag = "RETRY (transient — safe to retry)" if a.get('transient') else "RETRY"
                    print(f"  {tag}: {a['task_id'][:16]}")
                    print(f"    {a.get('hint', '')}")
                elif a['action'] == 'run_ralph_cycle':
                    print(f"  RUN CYCLE: {a.get('reason', '')}")
                    print(f"    python3 scripts/run_ralph_v1.py")
        return 0

    # --approve / --reject: approve or reject a pending approval
    if args.approve or args.reject:
        from runtime.ralph.agent_loop import approve_task, _load_env
        _load_env(root)
        task_id = args.approve or args.reject
        decision = "approved" if args.approve else "rejected"
        result = approve_task(task_id, decision=decision, reason=args.reason, root=root)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    # --retry: requeue a failed/blocked task
    if args.retry:
        from runtime.ralph.agent_loop import retry_task, _load_env
        _load_env(root)
        result = retry_task(args.retry, root=root)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    log.info("Ralph v1 starting  root=%s  dry_run=%s", root, args.dry_run)

    from runtime.ralph.agent_loop import run_cycle, run_health_gates, _load_env

    if args.dry_run:
        _load_env(root)
        healthy, gate_results = run_health_gates(root)
        result = {
            "dry_run": True,
            "healthy": healthy,
            "gates": gate_results,
        }
        print(json.dumps(result, indent=2))
        return 0 if healthy else 1

    try:
        result = run_cycle(root)
    except Exception as exc:
        log.exception("Unhandled error in Ralph v1 cycle: %s", exc)
        print(json.dumps({"outcome": "error", "error": str(exc)}, indent=2))
        return 1

    print(json.dumps(result, indent=2, default=str))

    outcome = result.get("outcome", "")
    if outcome.startswith("failed:"):
        log.warning("Cycle ended with failure: %s", outcome)
        return 1

    log.info("Cycle complete: %s", outcome)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
