#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.backend_assignments import allowed_models_by_task_class, route_legality_for_task
from runtime.core.approval_store import latest_approval_for_task, request_approval
from runtime.core.models import (
    AuthorityClass,
    BackendRuntime,
    ModelFamily,
    ModelTier,
    RoutingDecision,
    RoutingReason,
    TaskClass,
    TaskRecord,
    new_id,
    now_iso,
)
from runtime.core.review_store import latest_review_for_task, request_review
from runtime.core.task_store import load_task


def choose_reviewer(task_type: str, risk_level: str) -> str:
    if task_type == "code":
        return "archimedes"
    if task_type in {"deploy", "quant"}:
        return "anton"
    if risk_level in {"risky", "high_stakes"}:
        return "anton"
    return "archimedes"


def choose_approval_reviewer(task_type: str, risk_level: str) -> str:
    if task_type in {"deploy", "quant"}:
        return "anton"
    if risk_level == "high_stakes":
        return "anton"
    return "operator"


def routing_decision_logs_dir(root: Path) -> Path:
    path = root / "state" / "logs" / "routing_decisions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _normalize_task_class(task: TaskRecord) -> str:
    raw = (task.task_type or TaskClass.GENERAL.value).strip().lower()
    if raw == "quant":
        raw = TaskClass.DEPLOY.value
    return TaskClass.coerce(raw, default=TaskClass.GENERAL).value


def _normalize_authority_class(task: TaskRecord) -> str:
    if task.approval_required:
        return AuthorityClass.APPROVAL_REQUIRED.value
    if task.review_required:
        return AuthorityClass.REVIEW_REQUIRED.value
    return AuthorityClass.SUGGEST_ONLY.value


def collect_route_candidates(
    *,
    task: TaskRecord,
    latest_review,
    latest_approval,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    task_class = _normalize_task_class(task)
    authority_class = _normalize_authority_class(task)

    def add(
        *,
        ordinal: int,
        kind: str,
        eligible: bool,
        reason: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        candidates.append(
            {
                "ordinal": ordinal,
                "kind": kind,
                "eligible": eligible,
                "reason": reason,
                "summary": summary,
                "task_class": task_class,
                "authority_class": authority_class,
                "metadata": dict(metadata or {}),
            }
        )

    add(
        ordinal=10,
        kind="review_requested",
        eligible=bool(task.review_required and latest_review is None),
        reason="review_required_missing_record",
        summary=f"Review required for task {task.task_id}: {task.normalized_request}",
        metadata={"reviewer_role": choose_reviewer(task.task_type, task.risk_level)},
    )
    add(
        ordinal=20,
        kind="waiting_review",
        eligible=bool(task.review_required and latest_review is not None and latest_review.status == "pending"),
        reason="review_pending",
        summary="A review already exists and is still pending.",
        metadata={
            "review_id": getattr(latest_review, "review_id", None),
            "reviewer_role": getattr(latest_review, "reviewer_role", None),
            "status": getattr(latest_review, "status", None),
        },
    )
    add(
        ordinal=30,
        kind="blocked_by_review",
        eligible=bool(task.review_required and latest_review is not None and latest_review.status != "approved"),
        reason="review_not_approved",
        summary="The latest review is not approved, so the task cannot proceed.",
        metadata={
            "review_id": getattr(latest_review, "review_id", None),
            "reviewer_role": getattr(latest_review, "reviewer_role", None),
            "status": getattr(latest_review, "status", None),
        },
    )

    review_cleared = (not task.review_required) or (
        latest_review is not None and getattr(latest_review, "status", None) == "approved"
    )
    add(
        ordinal=40,
        kind="approval_requested",
        eligible=bool(review_cleared and task.approval_required and latest_approval is None),
        reason="approval_required_missing_record",
        summary=f"Approval required for task {task.task_id}: {task.normalized_request}",
        metadata={"requested_reviewer": choose_approval_reviewer(task.task_type, task.risk_level)},
    )
    add(
        ordinal=50,
        kind="waiting_approval",
        eligible=bool(review_cleared and task.approval_required and latest_approval is not None and latest_approval.status == "pending"),
        reason="approval_pending",
        summary="An approval request already exists and is still pending.",
        metadata={
            "approval_id": getattr(latest_approval, "approval_id", None),
            "requested_reviewer": getattr(latest_approval, "requested_reviewer", None),
            "status": getattr(latest_approval, "status", None),
        },
    )
    add(
        ordinal=60,
        kind="blocked_by_approval",
        eligible=bool(review_cleared and task.approval_required and latest_approval is not None and latest_approval.status != "approved"),
        reason="approval_not_approved",
        summary="The latest approval is not approved, so the task cannot proceed.",
        metadata={
            "approval_id": getattr(latest_approval, "approval_id", None),
            "requested_reviewer": getattr(latest_approval, "requested_reviewer", None),
            "status": getattr(latest_approval, "status", None),
        },
    )
    add(
        ordinal=70,
        kind="no_action",
        eligible=bool(
            (not task.review_required or (latest_review is not None and latest_review.status == "approved"))
            and (not task.approval_required or (latest_approval is not None and latest_approval.status == "approved"))
        ),
        reason="no_new_review_or_approval_needed",
        summary="No new review or approval request was needed.",
    )
    return candidates


def score_route_candidate(candidate: dict[str, Any]) -> int:
    if not candidate.get("eligible", False):
        return -1
    return 1000 - int(candidate.get("ordinal", 1000))


def select_best_route(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [
        {
            **candidate,
            "score": score_route_candidate(candidate),
        }
        for candidate in candidates
    ]
    eligible = [row for row in scored if row["score"] >= 0]
    if not eligible:
        return {
            "kind": "no_action",
            "reason": "no_eligible_candidate",
            "summary": "No eligible route candidate was found.",
            "score": -1,
            "metadata": {},
        }
    eligible.sort(key=lambda row: (row["score"], -int(row.get("ordinal", 1000))), reverse=True)
    return eligible[0]


def explain_routing_decision(
    *,
    task: TaskRecord,
    selected_candidate: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    allowed_models = allowed_models_by_task_class(_normalize_task_class(task), root=ROOT)
    inferred_model = next(
        (row for row in allowed_models if row.get("model_name") == task.assigned_model),
        allowed_models[0] if allowed_models else None,
    )
    routing_bridge = RoutingDecision(
        task_id=task.task_id,
        lane=task.source_lane,
        task_class=_normalize_task_class(task),
        authority_class=_normalize_authority_class(task),
        selected_family=(inferred_model or {}).get("family", ModelFamily.UNASSIGNED.value),
        selected_tier=(inferred_model or {}).get("tier", ModelTier.GENERAL.value),
        selected_backend_runtime=(
            task.execution_backend
            if task.execution_backend != BackendRuntime.UNASSIGNED.value
            else (inferred_model or {}).get("backend_runtime", BackendRuntime.UNASSIGNED.value)
        ),
        routing_reason=RoutingReason.POLICY_DEFAULT.value,
        candidate_backends=[row.get("backend_runtime", "") for row in allowed_models if row.get("backend_runtime")],
        source_refs={
            "decision_kind": selected_candidate.get("kind"),
            "decision_reason": selected_candidate.get("reason"),
        },
        metadata={
            "selected_model_name": task.assigned_model if task.assigned_model != "unassigned" else (inferred_model or {}).get("model_name"),
        },
    )
    legality = None
    if task.execution_backend != "unassigned" or task.assigned_model != "unassigned":
        legality = route_legality_for_task(task=task, route=routing_bridge.to_dict(), root=ROOT)
    return {
        "task_id": task.task_id,
        "task_class": routing_bridge.task_class,
        "authority_class": routing_bridge.authority_class,
        "selected_backend_runtime": routing_bridge.selected_backend_runtime or None,
        "selected_model_name": routing_bridge.metadata.get("selected_model_name"),
        "selected_model_family": routing_bridge.selected_family if routing_bridge.selected_family != ModelFamily.UNASSIGNED.value else None,
        "selected_model_tier": routing_bridge.selected_tier if routing_bridge.selected_tier != ModelTier.GENERAL.value or allowed_models else None,
        "routing_reason": routing_bridge.routing_reason,
        "decision_kind": selected_candidate.get("kind"),
        "decision_reason": selected_candidate.get("reason"),
        "candidate_routes": candidates,
        "degraded_mode_hint": (task.backend_metadata or {}).get("degraded_mode_hint"),
        "shared_routing_decision": routing_bridge.to_dict(),
        "route_legality": legality,
    }


def persist_routing_decision(
    *,
    task: TaskRecord,
    explanation: dict[str, Any],
    result: dict[str, Any],
    actor: str,
    lane: str,
    root: Path,
) -> Path:
    log_id = new_id("routeexpl")
    payload = {
        "routing_log_id": log_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "actor": actor,
        "lane": lane,
        "task_id": task.task_id,
        "result_kind": result.get("kind"),
        "result_status": result.get("status"),
        **explanation,
    }
    path = routing_decision_logs_dir(root) / f"{log_id}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def route_task_for_decision_explainable(
    *,
    task_id: str,
    actor: str,
    lane: str,
    root: Path,
) -> dict[str, Any]:
    task = load_task(task_id, root=root)
    if task is None:
        raise ValueError(f"Task not found: {task_id}")

    latest_review = latest_review_for_task(task_id, root=root)
    latest_approval = latest_approval_for_task(task_id, root=root)
    candidates = collect_route_candidates(task=task, latest_review=latest_review, latest_approval=latest_approval)
    selected = select_best_route(candidates)

    if selected["kind"] == "review_requested":
        review = request_review(
            task_id=task_id,
            reviewer_role=selected["metadata"]["reviewer_role"],
            requested_by=actor,
            lane=lane,
            summary=selected["summary"],
            root=root,
        )
        result = {
            "kind": "review_requested",
            "task_id": task_id,
            "review_id": review.review_id,
            "reviewer_role": review.reviewer_role,
            "status": review.status,
        }
    elif selected["kind"] == "waiting_review":
        result = {
            "kind": "waiting_review",
            "task_id": task_id,
            "review_id": selected["metadata"].get("review_id"),
            "reviewer_role": selected["metadata"].get("reviewer_role"),
            "status": selected["metadata"].get("status"),
            "message": selected["summary"],
        }
    elif selected["kind"] == "blocked_by_review":
        result = {
            "kind": "blocked_by_review",
            "task_id": task_id,
            "review_id": selected["metadata"].get("review_id"),
            "reviewer_role": selected["metadata"].get("reviewer_role"),
            "status": selected["metadata"].get("status"),
            "message": selected["summary"],
        }
    elif selected["kind"] == "approval_requested":
        approval = request_approval(
            task_id=task_id,
            approval_type=task.task_type,
            requested_by=actor,
            requested_reviewer=selected["metadata"]["requested_reviewer"],
            lane=lane,
            summary=selected["summary"],
            root=root,
        )
        result = {
            "kind": "approval_requested",
            "task_id": task_id,
            "approval_id": approval.approval_id,
            "requested_reviewer": approval.requested_reviewer,
            "status": approval.status,
        }
    elif selected["kind"] == "waiting_approval":
        result = {
            "kind": "waiting_approval",
            "task_id": task_id,
            "approval_id": selected["metadata"].get("approval_id"),
            "requested_reviewer": selected["metadata"].get("requested_reviewer"),
            "status": selected["metadata"].get("status"),
            "message": selected["summary"],
        }
    elif selected["kind"] == "blocked_by_approval":
        result = {
            "kind": "blocked_by_approval",
            "task_id": task_id,
            "approval_id": selected["metadata"].get("approval_id"),
            "requested_reviewer": selected["metadata"].get("requested_reviewer"),
            "status": selected["metadata"].get("status"),
            "message": selected["summary"],
        }
    else:
        result = {
            "kind": "no_action",
            "task_id": task_id,
            "message": selected["summary"],
        }

    explanation = explain_routing_decision(task=task, selected_candidate=selected, candidates=candidates)
    log_path = persist_routing_decision(
        task=task,
        explanation=explanation,
        result=result,
        actor=actor,
        lane=lane,
        root=root,
    )

    # Memory write — episodic record of routing decisions at dispatch points.
    # Only fires for review_requested and approval_requested (the decisive dispatch moments).
    # Skips waiting/blocked states (intermediate, not actionable for future routing).
    _write_routing_memory(task=task, result=result, explanation=explanation, actor=actor, root=root)

    return {
        "result": result,
        "routing_decision_log_path": str(log_path),
        "routing_decision": explanation,
    }


_ROUTING_DISPATCH_KINDS = {"review_requested", "approval_requested"}


def _write_routing_memory(
    *,
    task: "TaskRecord",
    result: dict[str, Any],
    explanation: dict[str, Any],
    actor: str,
    root: Path,
) -> None:
    """Write an episodic memory entry when a task is dispatched into review or approval.

    Captures: actor, task_class, destination (reviewer/approver), request summary.
    Only fires for decisive dispatch moments — review_requested, approval_requested.
    Never raises.
    """
    kind = result.get("kind", "")
    if kind not in _ROUTING_DISPATCH_KINDS:
        return

    req = str(task.normalized_request or "").strip()
    if not req or len(req) < 8:
        return

    task_class = str(explanation.get("task_class") or task.task_type or "general")
    decision_reason = str(explanation.get("decision_reason") or "").strip()

    if kind == "review_requested":
        reviewer = str(result.get("reviewer_role") or "reviewer")
        title = f"{actor} routed {task_class} to {reviewer} review: {req[:70]}"
        summary = (
            f"Routing: {actor} dispatched {task_class} task {task.task_id} "
            f"to {reviewer} for review. Request: {req[:150]}."
            + (f" Reason: {decision_reason[:80]}." if decision_reason else "")
        )
        confidence = 0.70
    else:  # approval_requested
        approver = str(result.get("requested_reviewer") or "operator")
        title = f"{actor} routed {task_class} to {approver} approval: {req[:70]}"
        summary = (
            f"Routing: {actor} dispatched {task_class} task {task.task_id} "
            f"to {approver} for approval. Request: {req[:150]}."
            + (f" Reason: {decision_reason[:80]}." if decision_reason else "")
        )
        confidence = 0.75

    try:
        from runtime.memory.governance import write_session_memory_entry
        write_session_memory_entry(
            actor=actor,
            lane="routing",
            memory_type="routing_decision",
            memory_class="decision_memory",
            structural_type="episodic",
            title=title[:160],
            summary=summary[:400],
            confidence_score=confidence,
            root=root,
        )
    except Exception:
        pass


def route_task_for_decision(
    *,
    task_id: str,
    actor: str,
    lane: str,
    root: Path,
) -> dict:
    explained = route_task_for_decision_explainable(
        task_id=task_id,
        actor=actor,
        lane=lane,
        root=root,
    )
    return explained["result"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Route a task into review or approval if policy requires it.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--task-id", required=True, help="Task id")
    parser.add_argument("--actor", default="operator", help="Requester")
    parser.add_argument("--lane", default="review", help="Lane")
    args = parser.parse_args()

    result = route_task_for_decision(
        task_id=args.task_id,
        actor=args.actor,
        lane=args.lane,
        root=Path(args.root).resolve(),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
