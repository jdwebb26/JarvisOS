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

from scripts.operator_handoff_pack import build_operator_handoff_pack


def _quote(value: str) -> str:
    return json.dumps(value)


def _command_spec(argv: list[str]) -> dict[str, Any]:
    return {
        "argv": argv,
        "command": " ".join(_quote(part) for part in argv),
    }


def _action_id(category: str, verb: str, target_id: str) -> str:
    return f"{category}:{verb}:{target_id}"


def _artifact_path(root: Path, artifact_id: str) -> Path:
    return root / "state" / "artifacts" / f"{artifact_id}.json"


def _task_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["task_id"]: row for row in rows if row.get("task_id")}


def _review_actions(root: Path, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        review_id = item["review_id"]
        task_id = item["task_id"]
        approve_action_id = _action_id("review", "approve", review_id)
        changes_requested_action_id = _action_id("review", "changes_requested", review_id)
        reject_action_id = _action_id("review", "reject", review_id)
        rows.append(
            {
                "review_id": review_id,
                "task_id": task_id,
                "summary": item.get("summary", ""),
                "reviewer_role": item.get("reviewer_role"),
                "commands": {
                    "approve": _command_spec(
                        [
                            "python3",
                            "runtime/gateway/review_decision.py",
                            "--root",
                            str(root),
                            "--review-id",
                            review_id,
                            "--verdict",
                            "approved",
                            "--actor",
                            "operator",
                            "--lane",
                            "review",
                            "--reason",
                            f"Approved from checkpoint pack for {task_id}",
                        ]
                    ),
                    "changes_requested": _command_spec(
                        [
                            "python3",
                            "runtime/gateway/review_decision.py",
                            "--root",
                            str(root),
                            "--review-id",
                            review_id,
                            "--verdict",
                            "changes_requested",
                            "--actor",
                            "operator",
                            "--lane",
                            "review",
                            "--reason",
                            f"Changes requested from checkpoint pack for {task_id}",
                        ]
                    ),
                    "reject": _command_spec(
                        [
                            "python3",
                            "runtime/gateway/review_decision.py",
                            "--root",
                            str(root),
                            "--review-id",
                            review_id,
                            "--verdict",
                            "rejected",
                            "--actor",
                            "operator",
                            "--lane",
                            "review",
                            "--reason",
                            f"Rejected from checkpoint pack for {task_id}",
                        ]
                    ),
                },
                "action_ids": {
                    "approve": approve_action_id,
                    "changes_requested": changes_requested_action_id,
                    "reject": reject_action_id,
                },
            }
        )
    return rows


def _approval_actions(root: Path, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        approval_id = item["approval_id"]
        task_id = item["task_id"]
        approve_action_id = _action_id("approval", "approve", approval_id)
        reject_action_id = _action_id("approval", "reject", approval_id)
        cancel_action_id = _action_id("approval", "cancel", approval_id)
        rows.append(
            {
                "approval_id": approval_id,
                "task_id": task_id,
                "summary": item.get("summary", ""),
                "requested_reviewer": item.get("requested_reviewer"),
                "commands": {
                    "approve": _command_spec(
                        [
                            "python3",
                            "runtime/gateway/approval_decision.py",
                            "--root",
                            str(root),
                            "--approval-id",
                            approval_id,
                            "--decision",
                            "approved",
                            "--actor",
                            "operator",
                            "--lane",
                            "review",
                            "--reason",
                            f"Approved from checkpoint pack for {task_id}",
                        ]
                    ),
                    "reject": _command_spec(
                        [
                            "python3",
                            "runtime/gateway/approval_decision.py",
                            "--root",
                            str(root),
                            "--approval-id",
                            approval_id,
                            "--decision",
                            "rejected",
                            "--actor",
                            "operator",
                            "--lane",
                            "review",
                            "--reason",
                            f"Rejected from checkpoint pack for {task_id}",
                        ]
                    ),
                    "cancel": _command_spec(
                        [
                            "python3",
                            "runtime/gateway/approval_decision.py",
                            "--root",
                            str(root),
                            "--approval-id",
                            approval_id,
                            "--decision",
                            "cancelled",
                            "--actor",
                            "operator",
                            "--lane",
                            "review",
                            "--reason",
                            f"Cancelled from checkpoint pack for {task_id}",
                        ]
                    ),
                },
                "action_ids": {
                    "approve": approve_action_id,
                    "reject": reject_action_id,
                    "cancel": cancel_action_id,
                },
            }
        )
    return rows


def _memory_actions(root: Path, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [item for item in items if item.get("lifecycle_state") == "candidate"]
    by_task: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        by_task.setdefault(item["task_id"], []).append(item)

    rows: list[dict[str, Any]] = []
    for task_id, task_items in by_task.items():
        sorted_items = sorted(task_items, key=lambda row: (row.get("confidence_score") or 0.0, row.get("updated_at", "")), reverse=True)
        for index, item in enumerate(sorted_items):
            mem_id = item["memory_candidate_id"]
            promote_action_id = _action_id("memory", "promote", mem_id)
            reject_action_id = _action_id("memory", "reject", mem_id)
            commands = {
                "promote": _command_spec(
                    [
                        "python3",
                        "runtime/gateway/memory_decision.py",
                        "--root",
                        str(root),
                        "--action",
                        "promote",
                        "--memory-candidate-id",
                        mem_id,
                        "--actor",
                        "operator",
                        "--lane",
                        "memory",
                        "--reason",
                        f"Promoted from checkpoint pack for {task_id}",
                    ]
                ),
                "reject": _command_spec(
                    [
                        "python3",
                        "runtime/gateway/memory_decision.py",
                        "--root",
                        str(root),
                        "--action",
                        "reject",
                        "--memory-candidate-id",
                        mem_id,
                        "--actor",
                        "operator",
                        "--lane",
                        "memory",
                        "--reason",
                        f"Rejected from checkpoint pack for {task_id}",
                    ]
                ),
            }
            action_ids = {
                "promote": promote_action_id,
                "reject": reject_action_id,
            }
            if index > 0:
                commands["supersede"] = _command_spec(
                    [
                        "python3",
                        "runtime/gateway/memory_decision.py",
                        "--root",
                        str(root),
                        "--action",
                        "supersede",
                        "--memory-candidate-id",
                        mem_id,
                        "--actor",
                        "operator",
                        "--lane",
                        "memory",
                        "--superseded-by-memory-candidate-id",
                        sorted_items[0]["memory_candidate_id"],
                        "--reason",
                        f"Superseded from checkpoint pack for {task_id}",
                    ]
                )
                action_ids["supersede"] = _action_id("memory", "supersede", mem_id)

            rows.append(
                {
                    "memory_candidate_id": mem_id,
                    "task_id": task_id,
                    "memory_type": item.get("memory_type"),
                    "summary": item.get("summary", ""),
                    "confidence_score": item.get("confidence_score"),
                    "commands": commands,
                    "action_ids": action_ids,
                }
            )
    return rows


def _artifact_followups(root: Path, task_rows: list[dict[str, Any]], artifacts: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    task_by_id = _task_index(task_rows)
    rows: list[dict[str, Any]] = []

    for item in artifacts.get("candidate", []) + artifacts.get("promoted", []):
        artifact_id = item["artifact_id"]
        task = task_by_id.get(item["task_id"], {})
        commands = {
            "inspect_artifact_json": _command_spec(
                [
                    "python3",
                    "-m",
                    "json.tool",
                    str(_artifact_path(root, artifact_id)),
                ]
            ),
        }
        action_ids = {
            "inspect_artifact_json": _action_id("artifact", "inspect", artifact_id),
        }
        status = task.get("status")
        promoted_artifact_id = task.get("promoted_artifact_id")
        if status == "shipped" and promoted_artifact_id == artifact_id:
            commands["publish_complete"] = _command_spec(
                [
                    "python3",
                    "runtime/gateway/complete_from_artifact.py",
                    "--root",
                    str(root),
                    "--task-id",
                    task["task_id"],
                    "--artifact-id",
                    artifact_id,
                    "--actor",
                    "operator",
                    "--lane",
                    "outputs",
                    "--final-outcome",
                    f"Completed from checkpoint pack for {task['task_id']}",
                ]
            )
            action_ids["publish_complete"] = _action_id("artifact", "publish_complete", artifact_id)
        elif status == "ready_to_ship" and promoted_artifact_id == artifact_id:
            commands["ship_task"] = _command_spec(
                [
                    "python3",
                    "runtime/gateway/ship_task.py",
                    "--root",
                    str(root),
                    "--task-id",
                    task["task_id"],
                    "--actor",
                    "operator",
                    "--lane",
                    "outputs",
                    "--final-outcome",
                    f"Shipped from checkpoint pack for {task['task_id']}",
                ]
            )
            action_ids["ship_task"] = _action_id("artifact", "ship_task", artifact_id)

        rows.append(
            {
                "artifact_id": artifact_id,
                "task_id": item["task_id"],
                "title": item.get("title"),
                "lifecycle_state": "promoted" if item in artifacts.get("promoted", []) else "candidate",
                "task_status": status,
                "commands": commands,
                "action_ids": action_ids,
            }
        )
    return rows


def _build_action_index(
    review_actions: list[dict[str, Any]],
    approval_actions: list[dict[str, Any]],
    memory_actions: list[dict[str, Any]],
    artifact_followups: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}

    for row in review_actions:
        for verb, action_id in row["action_ids"].items():
            index[action_id] = {
                "action_id": action_id,
                "category": "pending_review",
                "verb": verb,
                "target_id": row["review_id"],
                "task_id": row["task_id"],
                "command": row["commands"][verb],
                "summary": row.get("summary", ""),
            }

    for row in approval_actions:
        for verb, action_id in row["action_ids"].items():
            index[action_id] = {
                "action_id": action_id,
                "category": "pending_approval",
                "verb": verb,
                "target_id": row["approval_id"],
                "task_id": row["task_id"],
                "command": row["commands"][verb],
                "summary": row.get("summary", ""),
            }

    for row in memory_actions:
        for verb, action_id in row["action_ids"].items():
            index[action_id] = {
                "action_id": action_id,
                "category": "memory_candidate",
                "verb": verb,
                "target_id": row["memory_candidate_id"],
                "task_id": row["task_id"],
                "command": row["commands"][verb],
                "summary": row.get("summary", ""),
            }

    for row in artifact_followups:
        for verb, action_id in row["action_ids"].items():
            index[action_id] = {
                "action_id": action_id,
                "category": "artifact_followup",
                "verb": verb,
                "target_id": row["artifact_id"],
                "task_id": row["task_id"],
                "command": row["commands"][verb],
                "summary": row.get("title", ""),
            }

    return index


def _recommended_order(
    review_actions: list[dict[str, Any]],
    approval_actions: list[dict[str, Any]],
    memory_actions: list[dict[str, Any]],
    artifact_followups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    order: list[dict[str, Any]] = []
    for row in review_actions[:5]:
        action_id = row["action_ids"]["approve"]
        order.append(
            {
                "action_id": action_id,
                "category": "pending_review",
                "target_id": row["review_id"],
                "task_id": row["task_id"],
                "recommended_command": row["commands"]["approve"]["command"],
                "reason": "Reviews unblock the next approval or promotion decision.",
            }
        )
    for row in approval_actions[:5]:
        action_id = row["action_ids"]["approve"]
        order.append(
            {
                "action_id": action_id,
                "category": "pending_approval",
                "target_id": row["approval_id"],
                "task_id": row["task_id"],
                "recommended_command": row["commands"]["approve"]["command"],
                "reason": "Approvals unblock resume, ship, or publish decisions.",
            }
        )
    for row in memory_actions[:5]:
        action_id = row["action_ids"]["promote"]
        order.append(
            {
                "action_id": action_id,
                "category": "memory_candidate",
                "target_id": row["memory_candidate_id"],
                "task_id": row["task_id"],
                "recommended_command": row["commands"]["promote"]["command"],
                "reason": "Memory candidates stay non-promoted until an explicit operator decision.",
            }
        )
    for row in artifact_followups[:5]:
        primary_verb = "publish_complete" if "publish_complete" in row["commands"] else "ship_task" if "ship_task" in row["commands"] else "inspect_artifact_json"
        followup_command = row["commands"][primary_verb]
        order.append(
            {
                "action_id": row["action_ids"][primary_verb],
                "category": "artifact_followup",
                "target_id": row["artifact_id"],
                "task_id": row["task_id"],
                "recommended_command": followup_command["command"],
                "reason": "Inspect or continue artifact-backed work only after upstream decisions are clear.",
            }
        )
    return order


def _build_markdown(pack: dict[str, Any]) -> str:
    lines = [
        "# Operator Checkpoint Action Pack",
        "",
        f"Generated at: {pack['generated_at']}",
        "",
        "## Recommended Execution Order",
    ]
    for row in pack["recommended_execution_order"]:
        lines.append(f"- [{row['category']}] {row['target_id']} task={row['task_id']}")
        lines.append(f"  command: `{row['recommended_command']}`")

    lines.extend(["", "## Pending Review Commands"])
    for row in pack["pending_review_commands"]:
        lines.append(f"- {row['review_id']} task={row['task_id']}")
        lines.append(f"  approve [{row['action_ids']['approve']}]: `{row['commands']['approve']['command']}`")

    lines.extend(["", "## Pending Approval Commands"])
    for row in pack["pending_approval_commands"]:
        lines.append(f"- {row['approval_id']} task={row['task_id']}")
        lines.append(f"  approve [{row['action_ids']['approve']}]: `{row['commands']['approve']['command']}`")

    lines.extend(["", "## Memory Decision Commands"])
    for row in pack["memory_decision_commands"]:
        lines.append(f"- {row['memory_candidate_id']} task={row['task_id']} type={row['memory_type']}")
        lines.append(f"  promote [{row['action_ids']['promote']}]: `{row['commands']['promote']['command']}`")

    lines.extend(["", "## Artifact Follow-Up Commands"])
    for row in pack["artifact_followup_commands"]:
        lines.append(f"- {row['artifact_id']} task={row['task_id']} state={row['lifecycle_state']}")
        primary_verb = "publish_complete" if "publish_complete" in row["commands"] else "ship_task" if "ship_task" in row["commands"] else "inspect_artifact_json"
        primary = row["commands"][primary_verb]
        lines.append(f"  next [{row['action_ids'][primary_verb]}]: `{primary['command']}`")

    return "\n".join(lines).strip() + "\n"


def build_operator_checkpoint_action_pack(root: Path, *, limit: int = 10) -> dict[str, Any]:
    handoff_result = build_operator_handoff_pack(root, limit=limit)
    handoff = handoff_result["pack"]

    review_actions = _review_actions(root, handoff["pending_review_items"])
    approval_actions = _approval_actions(root, handoff["pending_approval_items"])
    memory_actions = _memory_actions(root, handoff["ralph_memory_summary"]["latest_memory_candidates"])
    artifact_followups = _artifact_followups(root, handoff["recent_task_status"], handoff["artifacts"])
    recommended_order = _recommended_order(review_actions, approval_actions, memory_actions, artifact_followups)
    action_index = _build_action_index(review_actions, approval_actions, memory_actions, artifact_followups)

    pack = {
        "generated_at": handoff["generated_at"],
        "source_handoff_pack_json_path": handoff_result["json_path"],
        "source_handoff_pack_markdown_path": handoff_result["markdown_path"],
        "pending_review_commands": review_actions,
        "pending_approval_commands": approval_actions,
        "memory_decision_commands": memory_actions,
        "artifact_followup_commands": artifact_followups,
        "recommended_execution_order": recommended_order,
        "action_index": action_index,
        "operator_focus": handoff.get("operator_focus", ""),
        "review_inbox_reply": handoff.get("review_inbox_reply", ""),
    }

    markdown = _build_markdown(pack)
    json_path = root / "state" / "logs" / "operator_checkpoint_action_pack.json"
    markdown_path = root / "state" / "logs" / "operator_checkpoint_action_pack.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")

    return {
        "pack": pack,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an operator checkpoint action pack with exact next-step commands.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--limit", type=int, default=10, help="Maximum recent items per section")
    args = parser.parse_args()

    result = build_operator_checkpoint_action_pack(Path(args.root).resolve(), limit=args.limit)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
