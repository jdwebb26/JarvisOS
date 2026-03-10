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


def hermes_execute_ack(result: dict) -> dict:
    record = result["result"]
    status = result.get("task_status", "unknown")
    candidate_artifact_id = result.get("candidate_artifact_id")
    trace_id = record.get("trace_id")
    reply = [
        f"Hermes finished task `{record['task_id']}` with result `{record['status']}`.",
        f"Task status is now `{status}`.",
    ]
    if candidate_artifact_id:
        reply.append(f"Candidate artifact: `{candidate_artifact_id}`.")
    if trace_id:
        reply.append(f"Trace: `{trace_id}`.")
    return {
        "kind": "hermes_execute_ack",
        "reply": " ".join(reply),
        "task_id": record["task_id"],
        "result_id": record["result_id"],
        "trace_id": trace_id,
        "candidate_artifact_id": candidate_artifact_id,
        "task_status_after": status,
    }


def autoresearch_campaign_ack(result: dict) -> dict:
    campaign = result["campaign"]
    recommendation = result.get("recommendation") or {}
    reply = [
        f"Autoresearch campaign `{campaign['campaign_id']}` finished with status `{campaign['status']}`.",
        f"Completed passes: {campaign['completed_passes']}/{campaign['max_passes']}.",
        f"Budget used: {campaign['budget_used']}/{campaign['max_budget_units']}.",
    ]
    if result.get("candidate_artifact_id"):
        reply.append(f"Recommendation artifact: `{result['candidate_artifact_id']}`.")
    if recommendation.get("recommendation_id"):
        reply.append(f"Recommendation: `{recommendation['recommendation_id']}`.")
    return {
        "kind": "autoresearch_campaign_ack",
        "reply": " ".join(reply),
        "task_id": campaign["task_id"],
        "campaign_id": campaign["campaign_id"],
        "recommendation_id": recommendation.get("recommendation_id"),
        "candidate_artifact_id": result.get("candidate_artifact_id"),
        "task_status_after": result.get("task_status"),
    }


def replay_eval_ack(result: dict) -> dict:
    eval_result = result["eval_result"]
    return {
        "kind": "replay_eval_ack",
        "reply": (
            f"Replay eval `{eval_result['eval_result_id']}` completed for trace "
            f"`{eval_result['trace_id']}` with score `{eval_result['score']:.4f}` "
            f"and passed=`{eval_result['passed']}`."
        ),
        "task_id": eval_result["task_id"],
        "trace_id": eval_result["trace_id"],
        "eval_result_id": eval_result["eval_result_id"],
        "report_artifact_id": result.get("report_artifact_id"),
    }


def ralph_consolidation_ack(result: dict) -> dict:
    run = result["consolidation_run"]
    return {
        "kind": "ralph_consolidation_ack",
        "reply": (
            f"Ralph consolidation `{run['consolidation_run_id']}` completed for task "
            f"`{run['task_id']}`. Digest artifact: `{result['digest_artifact_id']}`. "
            f"Memory candidates: {len(result['memory_candidate_ids'])}."
        ),
        "task_id": run["task_id"],
        "consolidation_run_id": run["consolidation_run_id"],
        "digest_artifact_id": result["digest_artifact_id"],
        "memory_candidate_ids": result["memory_candidate_ids"],
        "task_status_after": result.get("task_status"),
    }


def memory_retrieval_ack(result: dict) -> dict:
    retrieval = result["retrieval"]
    return {
        "kind": "memory_retrieval_ack",
        "reply": (
            f"Retrieved {retrieval['result_count']} memory candidates for "
            f"task `{retrieval.get('task_id') or 'all'}`."
        ),
        "memory_retrieval_id": retrieval["memory_retrieval_id"],
        "task_id": retrieval.get("task_id"),
        "result_count": retrieval["result_count"],
        "returned_memory_candidate_ids": retrieval["returned_memory_candidate_ids"],
    }


def memory_decision_ack(action: str, record: dict) -> dict:
    return {
        "kind": "memory_decision_ack",
        "reply": (
            f"Memory candidate `{record['memory_candidate_id']}` recorded as `{action}` "
            f"for task `{record['task_id']}`."
        ),
        "action": action,
        "task_id": record["task_id"],
        "memory_candidate_id": record["memory_candidate_id"],
        "lifecycle_state": record["lifecycle_state"],
        "decision_status": record.get("decision_status"),
    }
