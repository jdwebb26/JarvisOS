#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.dashboard.operator_snapshot import build_operator_snapshot
from runtime.dashboard.state_export import build_state_export
from runtime.dashboard.task_board import build_task_board
from runtime.gateway.review_inbox import build_review_inbox
from scripts.operator_action_ledger import (
    latest_failed_action_for_task,
    latest_successful_action_for_task,
)


def _load_jsons(folder: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return rows


def _sort_recent(rows: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> tuple[str, ...]:
        return tuple(str(row.get(key, "")) for key in keys)

    return sorted(rows, key=sort_key, reverse=True)


def _artifact_summary(rows: list[dict[str, Any]], *, lifecycle_state: str, limit: int) -> list[dict[str, Any]]:
    filtered = [row for row in rows if row.get("lifecycle_state") == lifecycle_state]
    filtered = _sort_recent(filtered, "updated_at", "created_at")
    return [
        {
            "artifact_id": row.get("artifact_id"),
            "task_id": row.get("task_id"),
            "title": row.get("title"),
            "artifact_type": row.get("artifact_type"),
            "execution_backend": row.get("execution_backend"),
            "updated_at": row.get("updated_at"),
        }
        for row in filtered[:limit]
    ]


def _trace_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "trace_id": row.get("trace_id"),
            "task_id": row.get("task_id"),
            "trace_kind": row.get("trace_kind"),
            "status": row.get("status"),
            "execution_backend": row.get("execution_backend"),
            "candidate_artifact_id": row.get("candidate_artifact_id"),
            "response_summary": row.get("response_summary"),
            "updated_at": row.get("updated_at"),
        }
        for row in _sort_recent(rows, "updated_at", "created_at")[:limit]
    ]


def _eval_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "eval_result_id": row.get("eval_result_id"),
            "task_id": row.get("task_id"),
            "trace_id": row.get("trace_id"),
            "score": row.get("score"),
            "passed": row.get("passed"),
            "summary": row.get("summary"),
            "report_artifact_id": row.get("report_artifact_id"),
            "updated_at": row.get("updated_at"),
        }
        for row in _sort_recent(rows, "updated_at", "created_at")[:limit]
    ]


def _operator_action_execution_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "execution_id": row.get("execution_id"),
            "action_id": row.get("action_id"),
            "category": (row.get("selected_action") or {}).get("category"),
            "verb": (row.get("selected_action") or {}).get("verb"),
            "target_id": (row.get("selected_action") or {}).get("target_id"),
            "task_id": (row.get("selected_action") or {}).get("task_id"),
            "dry_run": row.get("dry_run", False),
            "success": row.get("success", False),
            "return_code": row.get("return_code"),
            "ack_summary": row.get("ack_summary", ""),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _operator_queue_run_summary(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "queue_run_id": row.get("queue_run_id"),
            "ok": row.get("ok", False),
            "attempted_count": row.get("attempted_count", 0),
            "succeeded_count": row.get("succeeded_count", 0),
            "failed_count": row.get("failed_count", 0),
            "stopped_on_action_id": row.get("stopped_on_action_id"),
            "filters": row.get("filters", {}),
            "completed_at": row.get("completed_at"),
        }
        for row in _sort_recent(rows, "completed_at", "started_at")[:limit]
    ]


def _ralph_memory_summary(
    consolidation_runs: list[dict[str, Any]],
    memory_candidates: list[dict[str, Any]],
    *,
    limit: int,
) -> dict[str, Any]:
    latest_runs = _sort_recent(consolidation_runs, "updated_at", "created_at")[:limit]
    latest_candidates = _sort_recent(memory_candidates, "updated_at", "created_at")[:limit]
    return {
        "latest_consolidation_runs": [
            {
                "consolidation_run_id": row.get("consolidation_run_id"),
                "task_id": row.get("task_id"),
                "status": row.get("status"),
                "digest_artifact_id": row.get("digest_artifact_id"),
                "memory_candidate_ids": row.get("memory_candidate_ids", []),
                "summary": row.get("summary"),
                "updated_at": row.get("updated_at"),
            }
            for row in latest_runs
        ],
        "latest_memory_candidates": [
            {
                "memory_candidate_id": row.get("memory_candidate_id"),
                "task_id": row.get("task_id"),
                "memory_type": row.get("memory_type"),
                "lifecycle_state": row.get("lifecycle_state"),
                "decision_status": row.get("decision_status"),
                "confidence_score": row.get("confidence_score"),
                "execution_backend": row.get("execution_backend"),
                "summary": row.get("summary"),
                "updated_at": row.get("updated_at"),
            }
            for row in latest_candidates
        ],
    }


def _recommended_actions(snapshot: dict[str, Any], review_inbox: dict[str, Any], memory_candidates: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    if snapshot.get("operator_focus"):
        actions.append(snapshot["operator_focus"])

    pending_reviews = review_inbox.get("pending_reviews", [])
    for row in pending_reviews[:3]:
        actions.append(f"Review `{row['review_id']}` for task `{row['task_id']}`.")

    pending_approvals = review_inbox.get("pending_approvals", [])
    for row in pending_approvals[:3]:
        actions.append(f"Decide approval `{row['approval_id']}` for task `{row['task_id']}`.")

    candidate_memories = [
        row
        for row in _sort_recent(memory_candidates, "updated_at", "created_at")
        if row.get("lifecycle_state") == "candidate"
    ]
    for row in candidate_memories[:3]:
        actions.append(
            f"Decide memory candidate `{row['memory_candidate_id']}` ({row.get('memory_type', 'unknown')}) for task `{row['task_id']}`."
        )

    if not actions:
        actions.append("No immediate manual checkpoint items. Inspect recent artifacts and traces for the next bounded run.")
    return actions


def _build_markdown(pack: dict[str, Any]) -> str:
    lines = [
        "# Operator Handoff Pack",
        "",
        f"Generated at: {pack['generated_at']}",
        "",
        "## Recent Task Status",
    ]
    for row in pack["recent_task_status"]:
        lines.append(
            f"- {row['task_id']}: status={row['status']} backend={row.get('execution_backend')} control={row.get('control_status')} summary={row['summary']}"
        )
        if row.get("last_successful_operator_action"):
            lines.append(
                f"  last_success={row['last_successful_operator_action']['action_id']} ack={row['last_successful_operator_action']['ack_summary']}"
            )
        if row.get("last_failed_operator_action"):
            lines.append(
                f"  last_failed={row['last_failed_operator_action']['action_id']} stderr={row['last_failed_operator_action']['stderr_snapshot']}"
            )

    lines.extend(["", "## Artifacts"])
    lines.append(f"- candidate_artifacts={len(pack['artifacts']['candidate'])}")
    lines.append(f"- promoted_artifacts={len(pack['artifacts']['promoted'])}")

    lines.extend(["", "## Latest Traces"])
    for row in pack["latest_trace_summary"]:
        lines.append(f"- {row['trace_id']}: {row['trace_kind']} status={row['status']} task={row['task_id']}")

    lines.extend(["", "## Latest Evals"])
    for row in pack["latest_eval_summary"]:
        lines.append(
            f"- {row['eval_result_id']}: passed={row['passed']} score={row['score']} task={row['task_id']} summary={row['summary']}"
        )

    lines.extend(["", "## Recent Operator Actions"])
    for row in pack["recent_operator_action_executions"]:
        lines.append(
            f"- {row['execution_id']}: action={row['action_id']} success={row['success']} dry_run={row['dry_run']} ack={row['ack_summary']}"
        )
    if not pack["recent_operator_action_executions"]:
        lines.append("- none")

    lines.extend(["", "## Recent Queue Runs"])
    for row in pack["recent_operator_queue_runs"]:
        lines.append(
            f"- {row['queue_run_id']}: ok={row['ok']} attempted={row['attempted_count']} failed={row['failed_count']} stopped_on={row['stopped_on_action_id']}"
        )
    if not pack["recent_operator_queue_runs"]:
        lines.append("- none")

    lines.extend(["", "## Pending Review / Approval"])
    for row in pack["pending_review_items"]:
        lines.append(f"- review {row['review_id']} task={row['task_id']} reviewer={row['reviewer_role']} summary={row['summary']}")
    for row in pack["pending_approval_items"]:
        lines.append(
            f"- approval {row['approval_id']} task={row['task_id']} reviewer={row['requested_reviewer']} summary={row['summary']}"
        )
    if not pack["pending_review_items"] and not pack["pending_approval_items"]:
        lines.append("- none")

    lines.extend(["", "## Ralph / Memory"])
    for row in pack["ralph_memory_summary"]["latest_consolidation_runs"]:
        lines.append(
            f"- consolidation {row['consolidation_run_id']} task={row['task_id']} digest={row['digest_artifact_id']} status={row['status']}"
        )
    for row in pack["ralph_memory_summary"]["latest_memory_candidates"]:
        lines.append(
            f"- memory {row['memory_candidate_id']} task={row['task_id']} type={row['memory_type']} lifecycle={row['lifecycle_state']} decision={row['decision_status']}"
        )

    lines.extend(["", "## Recommended Next Actions"])
    for action in pack["recommended_next_actions"]:
        lines.append(f"- {action}")

    return "\n".join(lines).strip() + "\n"


def build_operator_handoff_pack(root: Path, *, limit: int = 10) -> dict[str, Any]:
    snapshot = build_operator_snapshot(root)
    task_board = build_task_board(root)
    review_inbox = build_review_inbox(root)
    state_export = build_state_export(root)

    artifacts = _load_jsons(root / "state" / "artifacts")
    run_traces = _load_jsons(root / "state" / "run_traces")
    eval_results = _load_jsons(root / "state" / "eval_results")
    consolidation_runs = _load_jsons(root / "state" / "consolidation_runs")
    memory_candidates = _load_jsons(root / "state" / "memory_candidates")
    operator_action_executions = _load_jsons(root / "state" / "operator_action_executions")
    operator_queue_runs = _load_jsons(root / "state" / "operator_queue_runs")
    recent_task_status = task_board["rows"][:limit]
    for row in recent_task_status:
        latest_success = latest_successful_action_for_task(root, row["task_id"])
        latest_failed = latest_failed_action_for_task(root, row["task_id"])
        row["last_successful_operator_action"] = latest_success
        row["last_failed_operator_action"] = latest_failed

    pack = {
        "generated_at": snapshot["status"].get("generated_at"),
        "recent_task_status": recent_task_status,
        "artifacts": {
            "candidate": _artifact_summary(artifacts, lifecycle_state="candidate", limit=limit),
            "promoted": _artifact_summary(artifacts, lifecycle_state="promoted", limit=limit),
        },
        "latest_trace_summary": _trace_summary(run_traces, limit=limit),
        "latest_eval_summary": _eval_summary(eval_results, limit=limit),
        "recent_operator_action_executions": _operator_action_execution_summary(operator_action_executions, limit=limit),
        "recent_operator_queue_runs": _operator_queue_run_summary(operator_queue_runs, limit=limit),
        "pending_review_items": review_inbox["pending_reviews"],
        "pending_approval_items": review_inbox["pending_approvals"],
        "ralph_memory_summary": _ralph_memory_summary(consolidation_runs, memory_candidates, limit=limit),
        "recommended_next_actions": _recommended_actions(snapshot, review_inbox, memory_candidates),
        "status_counts": snapshot.get("status", {}).get("counts", {}),
        "state_export_counts": state_export.get("counts", {}),
        "control_state": snapshot.get("control_state", {}),
        "operator_focus": snapshot.get("operator_focus", ""),
        "review_inbox_reply": review_inbox.get("reply", ""),
    }

    markdown = _build_markdown(pack)
    json_path = root / "state" / "logs" / "operator_handoff_pack.json"
    markdown_path = root / "state" / "logs" / "operator_handoff_pack.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")

    return {
        "pack": pack,
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an operator handoff pack from durable state.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=10, help="Maximum recent items per section")
    args = parser.parse_args()

    result = build_operator_handoff_pack(Path(args.root).resolve(), limit=args.limit)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
