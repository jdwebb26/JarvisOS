#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import new_id, now_iso
from runtime.evals.scorers import build_scorer_catalog, run_scaffolding_scorers
from runtime.evals.trace_store import list_run_traces, load_run_trace


def eval_runs_dir(root: Optional[Path] = None) -> Path:
    path = Path(root or ROOT).resolve() / "state" / "eval_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def eval_run_path(eval_run_id: str, *, root: Optional[Path] = None) -> Path:
    return eval_runs_dir(root) / f"{eval_run_id}.json"


def save_eval_run(payload: dict[str, Any], *, root: Optional[Path] = None) -> dict[str, Any]:
    path = eval_run_path(str(payload["eval_run_id"]), root=root)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_eval_run(eval_run_id: str, *, root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    path = eval_run_path(eval_run_id, root=root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_eval_runs(*, root: Optional[Path] = None, limit: Optional[int] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(eval_runs_dir(root).glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(key=lambda row: str(row.get("updated_at", row.get("created_at", ""))), reverse=True)
    if limit is not None:
        return rows[:limit]
    return rows


def build_eval_run_summary(*, root: Optional[Path] = None) -> dict[str, Any]:
    runs = list_eval_runs(root=root)
    latest = runs[0] if runs else None
    status_counts: dict[str, int] = {}
    for row in runs:
        status = str(row.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "eval_run_count": len(runs),
        "eval_run_status_counts": status_counts,
        "latest_eval_run": latest,
        "scorer_catalog": build_scorer_catalog(),
        "trace_catalog_count": len(list_run_traces(root=root)),
        "regression_suite_dir": str((Path(root or ROOT).resolve() / "runtime" / "evals" / "regression_suites")),
    }


def replay_trace(
    *,
    trace_id: str,
    actor: str,
    lane: str,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    resolved_root = Path(root or ROOT).resolve()
    trace = load_run_trace(trace_id, root=resolved_root)
    if trace is None:
        raise ValueError(f"Run trace not found: {trace_id}")

    trace_payload = trace.to_dict()
    scoring = run_scaffolding_scorers(trace_payload)
    payload = {
        "eval_run_id": new_id("evalrun"),
        "trace_id": trace_id,
        "task_id": trace.task_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "actor": actor,
        "lane": lane,
        "status": "stubbed",
        "replay_mode": "scaffolding_only",
        "notes": [
            "5.2-prep replay scaffold only. This pass does not add deep replay execution or routing-core hooks."
        ],
        "scoring": scoring,
        "trace_snapshot": {
            "trace_kind": trace.trace_kind,
            "execution_backend": trace.execution_backend,
            "status": trace.status,
        },
    }
    return save_eval_run(payload, root=resolved_root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a stored run trace through the bounded 5.2-prep eval scaffold.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--trace-id", default="", help="Trace id to replay")
    parser.add_argument("--actor", default="operator", help="Actor name")
    parser.add_argument("--lane", default="eval", help="Lane name")
    parser.add_argument("--list", action="store_true", help="List current eval runs and exit")
    args = parser.parse_args()

    resolved_root = Path(args.root).resolve()
    if args.list:
        print(json.dumps(build_eval_run_summary(root=resolved_root), indent=2))
        return 0
    if not args.trace_id:
        raise SystemExit("--trace-id is required unless --list is used.")
    print(json.dumps(replay_trace(trace_id=args.trace_id, actor=args.actor, lane=args.lane, root=resolved_root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
