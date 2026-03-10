#!/usr/bin/env python3
from __future__ import annotations

from runtime.dashboard.status_names import normalize_status_counts


def chat_only_ack() -> dict:
    return {
        "kind": "chat_only",
        "reply": "Got it. I’m keeping this as conversation only. Use `task:` if you want me to create durable work.",
    }


def task_created_ack(result: dict) -> dict:
    task_id = result["task_id"]
    summary = result["short_summary"]
    status = result["initial_status"]
    review_expected = result["review_expected"]
    approval_expected = result["approval_expected"]

    parts = [
        f"Created task `{task_id}`.",
        f"Summary: {summary}.",
        f"Status: {status}.",
        "Progress will appear in #tasks.",
    ]

    if review_expected:
        parts.append("This task is expected to need review.")
    if approval_expected:
        parts.append("This task is expected to need approval.")

    return {
        "kind": "task_created_ack",
        "reply": " ".join(parts),
        "task_id": task_id,
    }


def duplicate_task_ack(result: dict) -> dict:
    return {
        "kind": "duplicate_task_ack",
        "reply": (
            f"No new task created. Matching active task `{result['existing_task_id']}` "
            f"already exists with status `{result['existing_status']}`."
        ),
        "task_id": result["existing_task_id"],
    }


def status_ack(summary: dict) -> dict:
    counts = normalize_status_counts(summary["counts"])
    waiting_review = counts.get("waiting_review", 0)
    waiting_approval = counts.get("waiting_approval", 0)
    reply = (
        f"Tasks: total={counts['total_tasks']}, "
        f"queued={counts['queued']}, "
        f"running={counts['running']}, "
        f"blocked={counts['blocked']}, "
        f"waiting_review={waiting_review}, "
        f"waiting_approval={waiting_approval}. "
        f"Next: {summary['next_recommended_move']}"
    )
    return {
        "kind": "status_ack",
        "reply": reply,
    }


def build_task_status_reply(summary: dict) -> dict:
    return status_ack(summary)


def review_requested_ack(result: dict) -> dict:
    return {
        "kind": "review_requested_ack",
        "reply": (
            f"Review requested for task `{result['task_id']}`. "
            f"Review ID: `{result['review_id']}`. "
            f"Reviewer: {result['reviewer_role']}. "
            "Task is now waiting_review."
        ),
        "task_id": result["task_id"],
        "review_id": result["review_id"],
    }


def approval_requested_ack(result: dict) -> dict:
    return {
        "kind": "approval_requested_ack",
        "reply": (
            f"Approval requested for task `{result['task_id']}`. "
            f"Approval ID: `{result['approval_id']}`. "
            f"Requested reviewer: {result['requested_reviewer']}. "
            "Task is now waiting_approval."
        ),
        "task_id": result["task_id"],
        "approval_id": result["approval_id"],
    }


def review_recorded_ack(result: dict, task_status_after: str) -> dict:
    verdict = result["status"]
    if verdict == "approved":
        reply = (
            f"Review `{result['review_id']}` approved for task `{result['task_id']}`. "
            f"Task status is now `{task_status_after}`."
        )
    else:
        reply = (
            f"Review `{result['review_id']}` recorded as `{verdict}` for task `{result['task_id']}`. "
            f"Task status is now `{task_status_after}`."
        )

    return {
        "kind": "review_recorded_ack",
        "reply": reply,
        "review_id": result["review_id"],
        "task_id": result["task_id"],
        "task_status_after": task_status_after,
    }


def approval_recorded_ack(result: dict, task_status_after: str) -> dict:
    decision = result["status"]
    if decision == "approved":
        reply = (
            f"Approval `{result['approval_id']}` granted for task `{result['task_id']}`. "
            f"Task status is now `{task_status_after}`."
        )
    else:
        reply = (
            f"Approval `{result['approval_id']}` recorded as `{decision}` for task `{result['task_id']}`. "
            f"Task status is now `{task_status_after}`."
        )

    return {
        "kind": "approval_recorded_ack",
        "reply": reply,
        "approval_id": result["approval_id"],
        "task_id": result["task_id"],
        "task_status_after": task_status_after,
    }


def task_update_ack(result: dict) -> dict:
    status = result.get("status", "updated")
    return {
        "kind": "task_update_ack",
        "reply": f"Task `{result['task_id']}` is now `{status}`.",
        "task_id": result["task_id"],
        "status": status,
    }
