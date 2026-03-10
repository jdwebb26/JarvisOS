#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid


CORE_SCHEMA_VERSION = "v5.1"
LEGACY_RECORD_VERSION = "v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class StrEnum(str, Enum):
    @classmethod
    def values(cls) -> set[str]:
        return {item.value for item in cls}

    @classmethod
    def has_value(cls, value: str) -> bool:
        return value in cls.values()

    @classmethod
    def coerce(cls, value: Any, default: Optional["StrEnum"] = None) -> "StrEnum":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            for item in cls:
                if item.value == value:
                    return item
        if default is not None:
            return default
        raise ValueError(f"Invalid {cls.__name__}: {value!r}")


class TaskTriggerType(StrEnum):
    CHAT = "chat"
    EXPLICIT_TASK_COLON = "explicit_task_colon"


class TaskType(StrEnum):
    GENERAL = "general"
    CODE = "code"
    DEPLOY = "deploy"
    RESEARCH = "research"
    REVIEW = "review"
    APPROVAL = "approval"
    FLOWSTATE = "flowstate"
    OUTPUT = "output"


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TaskRiskLevel(StrEnum):
    NORMAL = "normal"
    RISKY = "risky"
    HIGH_STAKES = "high_stakes"


Priority = TaskPriority
RiskLevel = TaskRiskLevel
TriggerType = TaskTriggerType


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    WAITING_REVIEW = "waiting_review"
    WAITING_APPROVAL = "waiting_approval"
    READY_TO_SHIP = "ready_to_ship"
    SHIPPED = "shipped"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class RecordLifecycleState(StrEnum):
    WORKING = "working"
    CANDIDATE = "candidate"
    PROMOTED = "promoted"
    DEMOTED = "demoted"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    REJECTED = "rejected"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ArtifactType(StrEnum):
    NOTE = "note"
    MARKDOWN = "markdown"
    JSON = "json"
    TEXT = "text"
    REPORT = "report"
    CODE = "code"


class OutputStatus(StrEnum):
    PUBLISHED = "published"
    IMPACTED = "impacted"
    REVOKED = "revoked"


class ControlScopeType(StrEnum):
    GLOBAL = "global"
    SUBSYSTEM = "subsystem"
    TASK = "task"


class ControlRunState(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"


class ControlSafetyMode(StrEnum):
    NORMAL = "normal"
    DEGRADED = "degraded"
    REVOKED = "revoked"


class ControlAction(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    REVOKE = "revoke"
    DEGRADE = "degrade"


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return dataclass_to_dict(value)
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    return value


def dataclass_to_dict(instance: Any) -> dict[str, Any]:
    raw = asdict(instance)
    return {key: _serialize_value(value) for key, value in raw.items()}


def _extract_known_fields(cls: type, payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {f.name for f in fields(cls)}
    return {key: value for key, value in payload.items() if key in allowed}


def _apply_record_defaults(data: dict[str, Any]) -> dict[str, Any]:
    data.setdefault("schema_version", CORE_SCHEMA_VERSION)
    data.setdefault("version", LEGACY_RECORD_VERSION)
    return data


@dataclass
class TaskRecord:
    task_id: str
    created_at: str
    updated_at: str
    source_lane: str
    source_channel: str
    source_message_id: str
    source_user: str
    trigger_type: str
    raw_request: str
    normalized_request: str
    task_type: str = TaskType.GENERAL.value
    priority: str = TaskPriority.NORMAL.value
    risk_level: str = TaskRiskLevel.NORMAL.value
    status: str = TaskStatus.QUEUED.value
    lifecycle_state: str = RecordLifecycleState.WORKING.value
    assigned_role: str = "executor"
    assigned_model: str = "Qwen3.5-35B"
    execution_backend: str = "unassigned"
    backend_run_id: Optional[str] = None
    backend_metadata: dict[str, Any] = field(default_factory=dict)
    review_required: bool = False
    approval_required: bool = False
    parent_task_id: Optional[str] = None
    related_artifact_ids: list[str] = field(default_factory=list)
    candidate_artifact_ids: list[str] = field(default_factory=list)
    promoted_artifact_id: Optional[str] = None
    demoted_artifact_ids: list[str] = field(default_factory=list)
    revoked_artifact_ids: list[str] = field(default_factory=list)
    impacted_output_ids: list[str] = field(default_factory=list)
    related_review_ids: list[str] = field(default_factory=list)
    related_approval_ids: list[str] = field(default_factory=list)
    checkpoint_summary: str = ""
    error_count: int = 0
    last_error: str = ""
    final_outcome: str = ""
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("task_type", TaskType.GENERAL.value)
        data.setdefault("priority", TaskPriority.NORMAL.value)
        data.setdefault("risk_level", TaskRiskLevel.NORMAL.value)
        data.setdefault("status", TaskStatus.QUEUED.value)
        data.setdefault("lifecycle_state", RecordLifecycleState.WORKING.value)
        data.setdefault("assigned_role", "executor")
        data.setdefault("assigned_model", "Qwen3.5-35B")
        data.setdefault("execution_backend", "unassigned")
        data.setdefault("backend_run_id", None)
        data.setdefault("backend_metadata", {})
        data.setdefault("review_required", False)
        data.setdefault("approval_required", False)
        data.setdefault("parent_task_id", None)
        data.setdefault("related_artifact_ids", [])
        data.setdefault("candidate_artifact_ids", [])
        data.setdefault("promoted_artifact_id", None)
        data.setdefault("demoted_artifact_ids", [])
        data.setdefault("revoked_artifact_ids", [])
        data.setdefault("impacted_output_ids", [])
        data.setdefault("related_review_ids", [])
        data.setdefault("related_approval_ids", [])
        data.setdefault("checkpoint_summary", "")
        data.setdefault("error_count", 0)
        data.setdefault("last_error", "")
        data.setdefault("final_outcome", "")
        return cls(**data)


@dataclass
class ReviewRecord:
    review_id: str
    task_id: str
    requested_at: str
    updated_at: str
    reviewer_role: str
    requested_by: str
    lane: str
    status: str = ReviewStatus.PENDING.value
    summary: str = ""
    details: str = ""
    linked_artifact_ids: list[str] = field(default_factory=list)
    verdict_reason: str = ""
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReviewRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("status", ReviewStatus.PENDING.value)
        data.setdefault("summary", "")
        data.setdefault("details", "")
        data.setdefault("linked_artifact_ids", [])
        data.setdefault("verdict_reason", "")
        return cls(**data)


@dataclass
class ApprovalRecord:
    approval_id: str
    task_id: str
    requested_at: str
    updated_at: str
    requested_by: str
    requested_reviewer: str
    lane: str
    approval_type: str
    status: str = ApprovalStatus.PENDING.value
    summary: str = ""
    details: str = ""
    linked_artifact_ids: list[str] = field(default_factory=list)
    decision_reason: str = ""
    resumable_checkpoint_id: Optional[str] = None
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApprovalRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("status", ApprovalStatus.PENDING.value)
        data.setdefault("summary", "")
        data.setdefault("details", "")
        data.setdefault("linked_artifact_ids", [])
        data.setdefault("decision_reason", "")
        data.setdefault("resumable_checkpoint_id", None)
        return cls(**data)


@dataclass
class ApprovalCheckpointRecord:
    checkpoint_id: str
    approval_id: str
    task_id: str
    created_at: str
    updated_at: str
    created_by: str
    lane: str
    status: str = "pending"
    linked_artifact_ids: list[str] = field(default_factory=list)
    task_status_when_paused: str = TaskStatus.WAITING_APPROVAL.value
    task_lifecycle_state_when_paused: str = RecordLifecycleState.WORKING.value
    checkpoint_summary: str = ""
    final_outcome_snapshot: str = ""
    execution_backend: str = "unassigned"
    backend_run_id: Optional[str] = None
    resume_target_status: str = TaskStatus.QUEUED.value
    resume_reason: str = ""
    resume_count: int = 0
    resumed_at: Optional[str] = None
    task_snapshot: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApprovalCheckpointRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("status", "pending")
        data.setdefault("linked_artifact_ids", [])
        data.setdefault("task_status_when_paused", TaskStatus.WAITING_APPROVAL.value)
        data.setdefault("task_lifecycle_state_when_paused", RecordLifecycleState.WORKING.value)
        data.setdefault("checkpoint_summary", "")
        data.setdefault("final_outcome_snapshot", "")
        data.setdefault("execution_backend", "unassigned")
        data.setdefault("backend_run_id", None)
        data.setdefault("resume_target_status", TaskStatus.QUEUED.value)
        data.setdefault("resume_reason", "")
        data.setdefault("resume_count", 0)
        data.setdefault("resumed_at", None)
        data.setdefault("task_snapshot", {})
        return cls(**data)


@dataclass
class TaskEventRecord:
    event_id: str
    task_id: str
    event_type: str
    actor: str
    lane: str
    created_at: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    from_lifecycle_state: Optional[str] = None
    to_lifecycle_state: Optional[str] = None
    checkpoint_summary: Optional[str] = None
    reason: Optional[str] = None
    final_outcome: Optional[str] = None
    artifact_id: Optional[str] = None
    artifact_type: Optional[str] = None
    artifact_title: Optional[str] = None
    execution_backend: Optional[str] = None
    backend_run_id: Optional[str] = None
    already_linked: Optional[bool] = None
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskEventRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("from_status", None)
        data.setdefault("to_status", None)
        data.setdefault("from_lifecycle_state", None)
        data.setdefault("to_lifecycle_state", None)
        data.setdefault("checkpoint_summary", None)
        data.setdefault("reason", None)
        data.setdefault("final_outcome", None)
        data.setdefault("artifact_id", None)
        data.setdefault("artifact_type", None)
        data.setdefault("artifact_title", None)
        data.setdefault("execution_backend", None)
        data.setdefault("backend_run_id", None)
        data.setdefault("already_linked", None)
        return cls(**data)


TaskEvent = TaskEventRecord


@dataclass
class ArtifactRecord:
    artifact_id: str
    task_id: str
    artifact_type: str
    title: str
    summary: str
    content: str
    created_at: str
    updated_at: str
    created_by: str
    lane: str
    lifecycle_state: str = RecordLifecycleState.PROMOTED.value
    producer_kind: str = "operator"
    execution_backend: Optional[str] = None
    backend_run_id: Optional[str] = None
    provenance_ref: Optional[str] = None
    promoted_at: Optional[str] = None
    promoted_by: Optional[str] = None
    demoted_at: Optional[str] = None
    demoted_by: Optional[str] = None
    revoked_at: Optional[str] = None
    revoked_by: Optional[str] = None
    revocation_reason: str = ""
    downstream_impacted_output_ids: list[str] = field(default_factory=list)
    superseded_by_artifact_id: Optional[str] = None
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ArtifactRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("lifecycle_state", RecordLifecycleState.PROMOTED.value)
        data.setdefault("producer_kind", "operator")
        data.setdefault("execution_backend", None)
        data.setdefault("backend_run_id", None)
        data.setdefault("provenance_ref", None)
        data.setdefault("promoted_at", None)
        data.setdefault("promoted_by", None)
        data.setdefault("demoted_at", None)
        data.setdefault("demoted_by", None)
        data.setdefault("revoked_at", None)
        data.setdefault("revoked_by", None)
        data.setdefault("revocation_reason", "")
        data.setdefault("downstream_impacted_output_ids", [])
        data.setdefault("superseded_by_artifact_id", None)
        return cls(**data)


@dataclass
class OutputRecord:
    output_id: str
    task_id: str
    artifact_id: str
    title: str
    summary: str
    markdown_path: str
    json_path: str
    published_at: str
    published_by: str
    lane: str
    status: str = OutputStatus.PUBLISHED.value
    impacted_by_artifact_ids: list[str] = field(default_factory=list)
    superseded_by_artifact_id: Optional[str] = None
    revoked_at: Optional[str] = None
    revocation_reason: str = ""
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OutputRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("status", OutputStatus.PUBLISHED.value)
        data.setdefault("impacted_by_artifact_ids", [])
        data.setdefault("superseded_by_artifact_id", None)
        data.setdefault("revoked_at", None)
        data.setdefault("revocation_reason", "")
        return cls(**data)


@dataclass
class ControlRecord:
    control_id: str
    scope_type: str
    scope_id: str
    created_at: str
    updated_at: str
    run_state: str = ControlRunState.ACTIVE.value
    safety_mode: str = ControlSafetyMode.NORMAL.value
    last_action: str = ControlAction.RESUME.value
    last_actor: str = "system"
    lane: str = "controls"
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ControlRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("run_state", ControlRunState.ACTIVE.value)
        data.setdefault("safety_mode", ControlSafetyMode.NORMAL.value)
        data.setdefault("last_action", ControlAction.RESUME.value)
        data.setdefault("last_actor", "system")
        data.setdefault("lane", "controls")
        data.setdefault("reason", "")
        data.setdefault("metadata", {})
        return cls(**data)


@dataclass
class ControlActionRecord:
    action_id: str
    control_id: str
    scope_type: str
    scope_id: str
    action: str
    actor: str
    lane: str
    created_at: str
    reason: str = ""
    previous_run_state: str = ControlRunState.ACTIVE.value
    previous_safety_mode: str = ControlSafetyMode.NORMAL.value
    new_run_state: str = ControlRunState.ACTIVE.value
    new_safety_mode: str = ControlSafetyMode.NORMAL.value
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ControlActionRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("reason", "")
        data.setdefault("previous_run_state", ControlRunState.ACTIVE.value)
        data.setdefault("previous_safety_mode", ControlSafetyMode.NORMAL.value)
        data.setdefault("new_run_state", ControlRunState.ACTIVE.value)
        data.setdefault("new_safety_mode", ControlSafetyMode.NORMAL.value)
        data.setdefault("metadata", {})
        return cls(**data)


@dataclass
class ResearchCampaignRecord:
    campaign_id: str
    task_id: str
    created_at: str
    updated_at: str
    requested_by: str
    lane: str
    objective: str
    objective_metrics: list[str]
    primary_metric: str
    metric_directions: dict[str, str] = field(default_factory=dict)
    baseline_ref: Optional[str] = None
    benchmark_slice_ref: Optional[str] = None
    max_passes: int = 1
    max_budget_units: int = 1
    budget_used: int = 0
    stop_conditions: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    completed_passes: int = 0
    best_run_id: Optional[str] = None
    best_score: Optional[float] = None
    comparison_summary: str = ""
    latest_recommendation_id: Optional[str] = None
    linked_artifact_ids: list[str] = field(default_factory=list)
    execution_backend: str = "autoresearch_adapter"
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchCampaignRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("objective_metrics", [])
        data.setdefault("primary_metric", "")
        data.setdefault("metric_directions", {})
        data.setdefault("baseline_ref", None)
        data.setdefault("benchmark_slice_ref", None)
        data.setdefault("max_passes", 1)
        data.setdefault("max_budget_units", 1)
        data.setdefault("budget_used", 0)
        data.setdefault("stop_conditions", {})
        data.setdefault("status", "pending")
        data.setdefault("completed_passes", 0)
        data.setdefault("best_run_id", None)
        data.setdefault("best_score", None)
        data.setdefault("comparison_summary", "")
        data.setdefault("latest_recommendation_id", None)
        data.setdefault("linked_artifact_ids", [])
        data.setdefault("execution_backend", "autoresearch_adapter")
        return cls(**data)


@dataclass
class ExperimentRunRecord:
    run_id: str
    campaign_id: str
    task_id: str
    pass_index: int
    created_at: str
    updated_at: str
    actor: str
    lane: str
    status: str = "pending"
    budget_used: int = 0
    summary: str = ""
    hypothesis: str = ""
    comparison_summary: str = ""
    candidate_artifact_id: Optional[str] = None
    trace_id: Optional[str] = None
    stop_reason: str = ""
    raw_result: dict[str, Any] = field(default_factory=dict)
    execution_backend: str = "autoresearch_adapter"
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExperimentRunRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("status", "pending")
        data.setdefault("budget_used", 0)
        data.setdefault("summary", "")
        data.setdefault("hypothesis", "")
        data.setdefault("comparison_summary", "")
        data.setdefault("candidate_artifact_id", None)
        data.setdefault("trace_id", None)
        data.setdefault("stop_reason", "")
        data.setdefault("raw_result", {})
        data.setdefault("execution_backend", "autoresearch_adapter")
        return cls(**data)


@dataclass
class MetricResultRecord:
    metric_result_id: str
    campaign_id: str
    run_id: str
    task_id: str
    metric_name: str
    metric_value: float
    direction: str
    created_at: str
    updated_at: str
    baseline_value: Optional[float] = None
    delta_value: Optional[float] = None
    summary: str = ""
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MetricResultRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("baseline_value", None)
        data.setdefault("delta_value", None)
        data.setdefault("summary", "")
        return cls(**data)


@dataclass
class ResearchRecommendationRecord:
    recommendation_id: str
    campaign_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    action: str
    summary: str
    rationale: str = ""
    status: str = "candidate"
    best_run_id: Optional[str] = None
    recommended_artifact_id: Optional[str] = None
    linked_artifact_ids: list[str] = field(default_factory=list)
    execution_backend: str = "autoresearch_adapter"
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchRecommendationRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("rationale", "")
        data.setdefault("status", "candidate")
        data.setdefault("best_run_id", None)
        data.setdefault("recommended_artifact_id", None)
        data.setdefault("linked_artifact_ids", [])
        data.setdefault("execution_backend", "autoresearch_adapter")
        return cls(**data)


@dataclass
class RunTraceRecord:
    trace_id: str
    task_id: str
    trace_kind: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    execution_backend: str
    backend_run_id: Optional[str] = None
    status: str = "completed"
    request_summary: str = ""
    response_summary: str = ""
    decision_summary: str = ""
    request_payload: dict[str, Any] = field(default_factory=dict)
    response_payload: dict[str, Any] = field(default_factory=dict)
    replay_payload: dict[str, Any] = field(default_factory=dict)
    source_refs: dict[str, Any] = field(default_factory=dict)
    candidate_artifact_id: Optional[str] = None
    error: str = ""
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunTraceRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("backend_run_id", None)
        data.setdefault("status", "completed")
        data.setdefault("request_summary", "")
        data.setdefault("response_summary", "")
        data.setdefault("decision_summary", "")
        data.setdefault("request_payload", {})
        data.setdefault("response_payload", {})
        data.setdefault("replay_payload", {})
        data.setdefault("source_refs", {})
        data.setdefault("candidate_artifact_id", None)
        data.setdefault("error", "")
        return cls(**data)


@dataclass
class EvalCaseRecord:
    eval_case_id: str
    trace_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    evaluator_kind: str
    objective: str
    criteria: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    latest_eval_result_id: Optional[str] = None
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvalCaseRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("criteria", {})
        data.setdefault("status", "pending")
        data.setdefault("latest_eval_result_id", None)
        return cls(**data)


@dataclass
class EvalResultRecord:
    eval_result_id: str
    eval_case_id: str
    trace_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    evaluator_kind: str
    status: str = "completed"
    score: float = 0.0
    passed: bool = False
    summary: str = ""
    details: str = ""
    compared_values: dict[str, Any] = field(default_factory=dict)
    report_artifact_id: Optional[str] = None
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvalResultRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("status", "completed")
        data.setdefault("score", 0.0)
        data.setdefault("passed", False)
        data.setdefault("summary", "")
        data.setdefault("details", "")
        data.setdefault("compared_values", {})
        data.setdefault("report_artifact_id", None)
        return cls(**data)


@dataclass
class ConsolidationRunRecord:
    consolidation_run_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    status: str = "pending"
    summary: str = ""
    source_artifact_ids: list[str] = field(default_factory=list)
    source_trace_ids: list[str] = field(default_factory=list)
    source_eval_result_ids: list[str] = field(default_factory=list)
    digest_artifact_id: Optional[str] = None
    memory_candidate_ids: list[str] = field(default_factory=list)
    execution_backend: str = "ralph_adapter"
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ConsolidationRunRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("status", "pending")
        data.setdefault("summary", "")
        data.setdefault("source_artifact_ids", [])
        data.setdefault("source_trace_ids", [])
        data.setdefault("source_eval_result_ids", [])
        data.setdefault("digest_artifact_id", None)
        data.setdefault("memory_candidate_ids", [])
        data.setdefault("execution_backend", "ralph_adapter")
        return cls(**data)


@dataclass
class DigestArtifactLinkRecord:
    digest_link_id: str
    consolidation_run_id: str
    task_id: str
    artifact_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    link_role: str = "operator_digest"
    execution_backend: str = "ralph_adapter"
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DigestArtifactLinkRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("link_role", "operator_digest")
        data.setdefault("execution_backend", "ralph_adapter")
        return cls(**data)


@dataclass
class MemoryCandidateRecord:
    memory_candidate_id: str
    consolidation_run_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    candidate_kind: str
    memory_type: str
    title: str
    summary: str
    content: str
    decision_status: str = "candidate"
    confidence_score: float = 0.5
    decision_reason: str = ""
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    contradiction_status: str = "none"
    contradiction_reason: str = ""
    contradicted_at: Optional[str] = None
    contradicted_by: Optional[str] = None
    superseded_by_memory_candidate_id: Optional[str] = None
    promoted_at: Optional[str] = None
    promoted_by: Optional[str] = None
    source_artifact_ids: list[str] = field(default_factory=list)
    source_trace_ids: list[str] = field(default_factory=list)
    source_eval_result_ids: list[str] = field(default_factory=list)
    lifecycle_state: str = RecordLifecycleState.CANDIDATE.value
    execution_backend: str = "ralph_adapter"
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryCandidateRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("decision_status", "candidate")
        data.setdefault("confidence_score", 0.5)
        data.setdefault("decision_reason", "")
        data.setdefault("decided_at", None)
        data.setdefault("decided_by", None)
        data.setdefault("contradiction_status", "none")
        data.setdefault("contradiction_reason", "")
        data.setdefault("contradicted_at", None)
        data.setdefault("contradicted_by", None)
        data.setdefault("superseded_by_memory_candidate_id", None)
        data.setdefault("promoted_at", None)
        data.setdefault("promoted_by", None)
        data.setdefault("source_artifact_ids", [])
        data.setdefault("source_trace_ids", [])
        data.setdefault("source_eval_result_ids", [])
        data.setdefault("lifecycle_state", RecordLifecycleState.CANDIDATE.value)
        data.setdefault("execution_backend", "ralph_adapter")
        return cls(**data)


@dataclass
class MemoryRetrievalRecord:
    memory_retrieval_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    promoted_only: bool
    task_id: Optional[str] = None
    memory_type: Optional[str] = None
    source_artifact_id: Optional[str] = None
    source_trace_id: Optional[str] = None
    source_eval_result_id: Optional[str] = None
    include_contradicted: bool = False
    returned_memory_candidate_ids: list[str] = field(default_factory=list)
    result_count: int = 0
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryRetrievalRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("task_id", None)
        data.setdefault("memory_type", None)
        data.setdefault("source_artifact_id", None)
        data.setdefault("source_trace_id", None)
        data.setdefault("source_eval_result_id", None)
        data.setdefault("include_contradicted", False)
        data.setdefault("returned_memory_candidate_ids", [])
        data.setdefault("result_count", 0)
        return cls(**data)


TERMINAL_TASK_STATUSES = {
    TaskStatus.COMPLETED.value,
    TaskStatus.FAILED.value,
    TaskStatus.CANCELLED.value,
    TaskStatus.ARCHIVED.value,
    TaskStatus.SHIPPED.value,
}

ACTIVE_TASK_STATUSES = {
    TaskStatus.QUEUED.value,
    TaskStatus.RUNNING.value,
    TaskStatus.BLOCKED.value,
    TaskStatus.WAITING_REVIEW.value,
    TaskStatus.WAITING_APPROVAL.value,
    TaskStatus.READY_TO_SHIP.value,
}


def is_terminal_task_status(status: str) -> bool:
    return status in TERMINAL_TASK_STATUSES


def is_active_task_status(status: str) -> bool:
    return status in ACTIVE_TASK_STATUSES
