#!/usr/bin/env python3

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.models import (
    Priority,
    RiskLevel,
    TaskProvenanceRecord,
    TaskRecord,
    TaskStatus,
    TriggerType,
    new_id,
    now_iso,
)
from runtime.core.provenance_store import save_task_provenance
from runtime.core.routing import build_routing_failure_summary, latest_failed_routing_request, route_task_intent
from runtime.core.task_dedupe import find_active_duplicate_task
from runtime.core.task_store import create_task, load_task
from runtime.controls.control_store import assert_control_allows


@dataclass
class ParsedIntent:
    is_task: bool
    trigger_type: str
    raw_request: str
    normalized_request: str


class TaskCreationRefusalError(ValueError):
    def __init__(self, message: str, *, refusal: dict[str, Any]):
        super().__init__(message)
        self.refusal = refusal


def parse_explicit_task(text: str) -> ParsedIntent:
    raw = text.strip()
    lower = raw.lower()

    if lower.startswith("task:"):
        normalized = raw[5:].strip()
        if normalized:
            return ParsedIntent(True, TriggerType.EXPLICIT_TASK_COLON.value, raw, normalized)

    return ParsedIntent(False, TriggerType.CHAT.value, raw, raw)


def infer_task_type(normalized_request: str, *, channel: str = "") -> str:
    text = normalized_request.lower()
    tokens = set(re.findall(r"[a-z0-9_]+", text))

    def has_any(*terms: str) -> bool:
        for term in terms:
            if " " in term:
                if term in text:
                    return True
            elif term in tokens:
                return True
        return False

    # Lane-aware override: messages from the #muse channel are always creative,
    # even if they mention trading/market terms (e.g. "design a logo for our
    # NQ trading dashboard").  This prevents creative prompts from being
    # misclassified as quant/high_stakes.
    if channel.lower() in {"muse", "creative"}:
        return "creative"

    # Explicit creative intent (any channel).
    if has_any("creative", "poem", "brainstorm", "tagline", "slogan",
               "marketing copy", "write a story", "brand", "logo",
               "illustration", "mood board"):
        return "creative"

    # Browser check runs before quant/code because the execution modality
    # (browser_backend) is more specific than a content-domain hint like "nq".
    if has_any("browse", "browser", "navigate", "webpage", "website", "crawl", "scrape", "screenshot"):
        return "browser"
    if has_any("python", "code", "bug", "patch", "refactor", "script", "function", "test"):
        return "code"
    if has_any("nq", "quant", "trading", "prop account", "strategy", "backtest"):
        return "quant"
    if has_any("deploy", "release", "ship", "systemd", "service"):
        return "deploy"
    if has_any("doc", "report", "writeup", "summary", "spec"):
        return "docs"
    return "general"


def infer_priority(normalized_request: str) -> str:
    text = normalized_request.lower()
    if any(word in text for word in ["critical", "urgent", "asap", "immediately"]):
        return Priority.CRITICAL.value
    if any(word in text for word in ["high priority", "today", "important", "soon"]):
        return Priority.HIGH.value
    return Priority.NORMAL.value


def infer_risk(task_type: str, normalized_request: str) -> str:
    text = normalized_request.lower()

    if task_type in {"deploy", "quant"}:
        return RiskLevel.HIGH_STAKES.value
    if task_type == "code":
        return RiskLevel.RISKY.value
    if any(word in text for word in ["publish", "production", "live", "real money", "execute"]):
        return RiskLevel.HIGH_STAKES.value
    return RiskLevel.NORMAL.value


def review_required(task_type: str, risk_level: str) -> bool:
    if task_type == "code":
        return True
    if risk_level in {RiskLevel.RISKY.value, RiskLevel.HIGH_STAKES.value}:
        return True
    return False


def approval_required(task_type: str, risk_level: str) -> bool:
    if task_type in {"deploy", "quant"}:
        return True
    if risk_level == RiskLevel.HIGH_STAKES.value:
        return True
    return False


def normalize_workload_type(
    *,
    lane: str,
    channel: str,
    explicit_workload_type: Optional[str],
) -> str:
    if explicit_workload_type:
        return str(explicit_workload_type).strip()
    normalized_channel = str(channel or "").strip().lower()
    normalized_lane = str(lane or "").strip().lower()
    if normalized_channel == "local_embeddings":
        return "embeddings"
    if normalized_lane == "scout":
        return "research"
    return "general"


def create_task_from_message(
    *,
    text: str,
    user: str,
    lane: str,
    channel: str,
    message_id: str,
    workload_type: Optional[str] = None,
    autonomy_mode: str = "step_mode",
    task_envelope: Optional[dict] = None,
    parent_task_id: Optional[str] = None,
    speculative_downstream: bool = False,
    root: Optional[Path] = None,
) -> dict:
    root_path = Path(root or ROOT).resolve()
    parsed = parse_explicit_task(text)

    if not parsed.is_task:
        return {
            "kind": "chat_only",
            "task_created": False,
            "message": "No task created. Ordinary chat remains conversational unless the explicit `task:` trigger is used.",
            "accepted_triggers": ["task: ..."],
        }

    duplicate = find_active_duplicate_task(
        normalized_request=parsed.normalized_request,
        root=root_path,
    )
    if duplicate:
        return {
            "kind": "duplicate_task_existing",
            "task_created": False,
            "existing_task_id": duplicate["task_id"],
            "short_summary": duplicate["summary"],
            "existing_status": duplicate["status"],
            "existing_task_type": duplicate["task_type"],
            "existing_priority": duplicate["priority"],
            "existing_risk_level": duplicate["risk_level"],
            "existing_assigned_model": duplicate["assigned_model"],
            "message": "A matching active task already exists, so no new task was created.",
        }

    task_type = infer_task_type(parsed.normalized_request, channel=channel)
    priority = infer_priority(parsed.normalized_request)
    risk = infer_risk(task_type, parsed.normalized_request)
    normalized_workload_type = normalize_workload_type(
        lane=lane,
        channel=channel,
        explicit_workload_type=workload_type,
    )
    assert_control_allows(
        action="task_create",
        root=root_path,
        actor=user,
        lane=lane,
    )

    # --- Browser tasks bypass LLM model routing: PinchTab needs no model ---
    if task_type == "browser":
        from runtime.core.browser_task import create_browser_task_from_text
        return create_browser_task_from_text(
            text=parsed.normalized_request,
            actor=user,
            lane=lane,
            source_channel=channel,
            source_message_id=message_id,
            parent_task_id=parent_task_id,
            root=root_path,
        )

    task_id = new_id("task")
    try:
        route_contract = route_task_intent(
            task_id=task_id,
            normalized_request=parsed.normalized_request,
            task_type=task_type,
            risk_level=risk,
            priority=priority,
            actor=user,
            lane=lane,
            agent_id=lane,
            channel=channel,
            workload_type=normalized_workload_type,
            root=root_path,
        )
    except ValueError as exc:
        failed_request = latest_failed_routing_request(root=root_path)
        failed_payload = failed_request.to_dict() if failed_request and failed_request.task_id == task_id else None
        refusal = build_routing_failure_summary(failed_payload) or {
            "routing_request_id": None,
            "task_id": task_id,
            "lane": lane,
            "channel": channel,
            "workload_type": normalized_workload_type,
            "task_type": task_type,
            "risk_level": risk,
            "preferred_provider": None,
            "preferred_model": None,
            "preferred_host_role": None,
            "allowed_host_roles": [],
            "forbidden_host_roles": [],
            "allowed_fallbacks": [],
            "eligible_provider_ids": [],
            "failure_code": "routing_refused_before_summary",
            "failure_reason": str(exc),
            "status": "failed",
        }
        raise TaskCreationRefusalError(
            "Task creation refused because routing found no legal candidate.",
            refusal=refusal,
        ) from exc
    routing_decision = route_contract["decision"]
    provider_adapter_result = route_contract["provider_adapter_result"]
    backend_assignment = route_contract["backend_assignment"]

    record = TaskRecord(
        task_id=task_id,
        created_at=now_iso(),
        updated_at=now_iso(),
        source_lane=lane,
        source_channel=channel,
        source_message_id=message_id,
        source_user=user,
        trigger_type=parsed.trigger_type,
        raw_request=parsed.raw_request,
        normalized_request=parsed.normalized_request,
        task_type=task_type,
        priority=priority,
        risk_level=risk,
        status=TaskStatus.QUEUED.value,
        assigned_role="executor",
        assigned_model=routing_decision["selected_model_name"],
        backend_assignment_id=backend_assignment["backend_assignment_id"],
        execution_backend=routing_decision["selected_execution_backend"],
        backend_metadata={
            "routing_policy": "provider_agnostic_qwen_first",
            "routing": {
                "routing_request_id": route_contract["request"]["routing_request_id"],
                "routing_decision_id": routing_decision["routing_decision_id"],
                "provider_adapter_result_id": provider_adapter_result["provider_adapter_result_id"],
                "backend_assignment_id": backend_assignment["backend_assignment_id"],
                "provider_id": routing_decision["selected_provider_id"],
                "model_name": routing_decision["selected_model_name"],
                "selected_node_role": routing_decision["selected_node_role"],
                "selected_host_name": routing_decision["selected_host_name"],
                "model_registry_entry_id": routing_decision["selected_model_registry_entry_id"],
                "capability_profile_id": routing_decision["selected_capability_profile_id"],
                "workload_type": route_contract["request"]["policy_constraints"].get("workload_type"),
                "required_capabilities": list(route_contract["request"]["required_capabilities"]),
                "policy_constraints": dict(route_contract["request"]["policy_constraints"]),
            },
        },
        review_required=review_required(task_type, risk),
        approval_required=approval_required(task_type, risk),
        autonomy_mode=autonomy_mode,
        task_envelope=dict(task_envelope or {}),
        parent_task_id=parent_task_id,
        speculative_downstream=speculative_downstream,
    )

    create_task(record, root=root_path)
    task_provenance = save_task_provenance(
        TaskProvenanceRecord(
            task_provenance_id=new_id("tprov"),
            task_id=record.task_id,
            created_at=now_iso(),
            updated_at=now_iso(),
            actor=user,
            lane=lane,
            source_lane=lane,
            source_channel=channel,
            source_message_id=message_id,
            source_user=user,
            routing_decision_id=routing_decision["routing_decision_id"],
            replay_input={
                "text": text,
                "normalized_request": parsed.normalized_request,
                "task_type": task_type,
                "priority": priority,
                "risk_level": risk,
            },
        ),
        root=root_path,
    )

    route_result = None
    route_error = ""
    try:
        from runtime.core.decision_router import route_task_for_decision

        route_result = route_task_for_decision(
            task_id=record.task_id,
            actor=user,
            lane=lane,
            root=root_path,
        )
    except Exception as e:
        route_error = f"{type(e).__name__}: {e}"

    final_record = load_task(record.task_id, root=root_path)

    return {
        "kind": "task_created",
        "ok": True,
        "task_created": True,
        "task_id": record.task_id,
        "short_summary": record.normalized_request,
        "initial_status": record.status,
        "final_status": final_record.status if final_record else record.status,
        "progress_lane": "#tasks",
        "review_expected": record.review_required,
        "approval_expected": record.approval_required,
        "task_type": record.task_type,
        "priority": record.priority,
        "risk_level": record.risk_level,
        "assigned_model": record.assigned_model,
        "routing_contract": route_contract,
        "task_provenance": task_provenance.to_dict(),
        "route_result": route_result,
        "route_error": route_error,
    }


def create_task_from_message_result(**kwargs: Any) -> dict[str, Any]:
    try:
        return create_task_from_message(**kwargs)
    except TaskCreationRefusalError as exc:
        return {
            "ok": False,
            "task_created": False,
            "error_type": "routing_refused",
            "message": str(exc),
            "refusal": dict(exc.refusal),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse explicit task requests into durable task records.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--text", required=True, help="Incoming message text")
    parser.add_argument("--user", default="operator", help="Source user")
    parser.add_argument("--lane", default="jarvis", help="Source lane")
    parser.add_argument("--channel", default="jarvis", help="Source channel")
    parser.add_argument("--message-id", default="manual_cli", help="Source message id")
    args = parser.parse_args()

    result = create_task_from_message_result(
        text=args.text,
        user=args.user,
        lane=args.lane,
        channel=args.channel,
        message_id=args.message_id,
        root=Path(args.root).resolve(),
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
