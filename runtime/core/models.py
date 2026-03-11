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


class MemoryEligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    REVIEW_REQUIRED = "review_required"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED_BY_CONTROL = "blocked_by_control"
    REVOKED_UPSTREAM = "revoked_upstream"
    INELIGIBLE = "ineligible"


class ReplayResultKind(StrEnum):
    MATCH = "match"
    DRIFT = "drift"
    BLOCKED_BY_CONTROL = "blocked_by_control"
    MISSING_SOURCE = "missing_source"
    INVALID_REPLAY = "invalid_replay"


class DegradationEventStatus(StrEnum):
    RECORDED = "recorded"
    APPLIED = "applied"
    BLOCKED = "blocked"


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
    assigned_model: str = "unassigned"
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
    blocked_dependency_refs: list[str] = field(default_factory=list)
    related_review_ids: list[str] = field(default_factory=list)
    related_approval_ids: list[str] = field(default_factory=list)
    checkpoint_summary: str = ""
    error_count: int = 0
    last_error: str = ""
    final_outcome: str = ""
    publish_readiness_status: str = "pending"
    publish_readiness_reason: str = ""
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
        data.setdefault("assigned_model", "unassigned")
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
        data.setdefault("blocked_dependency_refs", [])
        data.setdefault("related_review_ids", [])
        data.setdefault("related_approval_ids", [])
        data.setdefault("checkpoint_summary", "")
        data.setdefault("error_count", 0)
        data.setdefault("last_error", "")
        data.setdefault("final_outcome", "")
        data.setdefault("publish_readiness_status", "pending")
        data.setdefault("publish_readiness_reason", "")
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
    execution_freeze: bool = False
    promotion_freeze: bool = False
    approval_freeze: bool = False
    memory_freeze: bool = False
    recovery_only_mode: bool = False
    operator_only_mode: bool = False
    disabled_provider_ids: list[str] = field(default_factory=list)
    disabled_execution_backends: list[str] = field(default_factory=list)
    latest_control_event_id: Optional[str] = None
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
        data.setdefault("execution_freeze", False)
        data.setdefault("promotion_freeze", False)
        data.setdefault("approval_freeze", False)
        data.setdefault("memory_freeze", False)
        data.setdefault("recovery_only_mode", False)
        data.setdefault("operator_only_mode", False)
        data.setdefault("disabled_provider_ids", [])
        data.setdefault("disabled_execution_backends", [])
        data.setdefault("latest_control_event_id", None)
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
class ControlEventRecord:
    control_event_id: str
    control_id: str
    scope_type: str
    scope_id: str
    created_at: str
    actor: str
    lane: str
    control_kind: str
    enabled: bool = True
    reason: str = ""
    target_provider_id: Optional[str] = None
    target_execution_backend: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ControlEventRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("enabled", True)
        data.setdefault("reason", "")
        data.setdefault("target_provider_id", None)
        data.setdefault("target_execution_backend", None)
        data.setdefault("metadata", {})
        return cls(**data)


@dataclass
class ControlBlockedActionRecord:
    blocked_action_id: str
    created_at: str
    action: str
    task_id: Optional[str] = None
    subsystem: Optional[str] = None
    provider_id: Optional[str] = None
    actor: str = "system"
    lane: str = "controls"
    effective_status: str = ControlRunState.ACTIVE.value
    reason: str = ""
    control_scope_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ControlBlockedActionRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("task_id", None)
        data.setdefault("subsystem", None)
        data.setdefault("provider_id", None)
        data.setdefault("actor", "system")
        data.setdefault("lane", "controls")
        data.setdefault("effective_status", ControlRunState.ACTIVE.value)
        data.setdefault("reason", "")
        data.setdefault("control_scope_refs", [])
        data.setdefault("metadata", {})
        return cls(**data)


@dataclass
class DegradationPolicyRecord:
    degradation_policy_id: str
    subsystem: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    degradation_mode: str
    fallback_action: str
    requires_operator_notification: bool
    auto_recover: bool
    retry_policy: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DegradationPolicyRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("retry_policy", {})
        return cls(**data)


@dataclass
class DegradationEventRecord:
    degradation_event_id: str
    subsystem: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    degradation_policy_id: Optional[str] = None
    task_id: Optional[str] = None
    failure_category: str = ""
    degradation_mode: str = ""
    fallback_action: str = ""
    requires_operator_notification: bool = False
    auto_recover: bool = False
    retry_policy: dict[str, Any] = field(default_factory=dict)
    status: str = DegradationEventStatus.RECORDED.value
    reason: str = ""
    source_refs: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DegradationEventRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("degradation_policy_id", None)
        data.setdefault("task_id", None)
        data.setdefault("failure_category", "")
        data.setdefault("degradation_mode", "")
        data.setdefault("fallback_action", "")
        data.setdefault("requires_operator_notification", False)
        data.setdefault("auto_recover", False)
        data.setdefault("retry_policy", {})
        data.setdefault("status", DegradationEventStatus.RECORDED.value)
        data.setdefault("reason", "")
        data.setdefault("source_refs", {})
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
    source_candidate_ids: list[str] = field(default_factory=list)
    source_output_ids: list[str] = field(default_factory=list)
    source_task_event_ids: list[str] = field(default_factory=list)
    source_provenance_refs: dict[str, Any] = field(default_factory=dict)
    eligibility_status: str = MemoryEligibilityStatus.ELIGIBLE.value
    eligibility_reason: str = ""
    validation_record_ids: list[str] = field(default_factory=list)
    latest_validation_id: Optional[str] = None
    latest_promotion_decision_id: Optional[str] = None
    latest_rejection_decision_id: Optional[str] = None
    latest_revocation_decision_id: Optional[str] = None
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
        data.setdefault("source_candidate_ids", [])
        data.setdefault("source_output_ids", [])
        data.setdefault("source_task_event_ids", [])
        data.setdefault("source_provenance_refs", {})
        data.setdefault("eligibility_status", MemoryEligibilityStatus.ELIGIBLE.value)
        data.setdefault("eligibility_reason", "")
        data.setdefault("validation_record_ids", [])
        data.setdefault("latest_validation_id", None)
        data.setdefault("latest_promotion_decision_id", None)
        data.setdefault("latest_rejection_decision_id", None)
        data.setdefault("latest_revocation_decision_id", None)
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


@dataclass
class MemoryValidationRecord:
    memory_validation_id: str
    memory_candidate_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    validator_kind: str
    status: str = "passed"
    summary: str = ""
    details: str = ""
    evidence_refs: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryValidationRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("status", "passed")
        data.setdefault("summary", "")
        data.setdefault("details", "")
        data.setdefault("evidence_refs", {})
        return cls(**data)


@dataclass
class MemoryPromotionDecisionRecord:
    memory_promotion_decision_id: str
    memory_candidate_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    decision: str = "promoted"
    reason: str = ""
    validation_record_ids: list[str] = field(default_factory=list)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryPromotionDecisionRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("decision", "promoted")
        data.setdefault("reason", "")
        data.setdefault("validation_record_ids", [])
        return cls(**data)


@dataclass
class MemoryRejectionDecisionRecord:
    memory_rejection_decision_id: str
    memory_candidate_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    decision: str = "rejected"
    reason: str = ""
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryRejectionDecisionRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("decision", "rejected")
        data.setdefault("reason", "")
        return cls(**data)


@dataclass
class MemoryRevocationDecisionRecord:
    memory_revocation_decision_id: str
    memory_candidate_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    decision: str = "revoked"
    reason: str = ""
    trigger_ref: str = ""
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryRevocationDecisionRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("decision", "revoked")
        data.setdefault("reason", "")
        data.setdefault("trigger_ref", "")
        return cls(**data)


@dataclass
class CapabilityProfileRecord:
    capability_profile_id: str
    created_at: str
    updated_at: str
    profile_name: str
    provider_id: str
    model_family: str
    capabilities: list[str] = field(default_factory=list)
    supported_task_types: list[str] = field(default_factory=list)
    supported_risk_levels: list[str] = field(default_factory=list)
    preferred_execution_backend: str = "unassigned"
    active: bool = True
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CapabilityProfileRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("capabilities", [])
        data.setdefault("supported_task_types", [])
        data.setdefault("supported_risk_levels", [])
        data.setdefault("preferred_execution_backend", "unassigned")
        data.setdefault("active", True)
        return cls(**data)


@dataclass
class ModelRegistryEntryRecord:
    model_registry_entry_id: str
    created_at: str
    updated_at: str
    provider_id: str
    provider_kind: str
    model_family: str
    model_name: str
    display_name: str
    capability_profile_ids: list[str] = field(default_factory=list)
    policy_tags: list[str] = field(default_factory=list)
    priority_rank: int = 100
    default_execution_backend: str = "unassigned"
    active: bool = True
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ModelRegistryEntryRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("capability_profile_ids", [])
        data.setdefault("policy_tags", [])
        data.setdefault("priority_rank", 100)
        data.setdefault("default_execution_backend", "unassigned")
        data.setdefault("active", True)
        return cls(**data)


@dataclass
class RoutingRequestRecord:
    routing_request_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    normalized_request: str
    task_type: str
    risk_level: str
    priority: str
    required_capabilities: list[str] = field(default_factory=list)
    policy_constraints: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RoutingRequestRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("required_capabilities", [])
        data.setdefault("policy_constraints", {})
        data.setdefault("status", "pending")
        return cls(**data)


@dataclass
class RoutingDecisionRecord:
    routing_decision_id: str
    routing_request_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    selected_model_registry_entry_id: str
    selected_capability_profile_id: str
    selected_provider_id: str
    selected_model_name: str
    selected_execution_backend: str
    selection_reason: str
    candidate_model_names: list[str] = field(default_factory=list)
    policy_constraints: dict[str, Any] = field(default_factory=dict)
    status: str = "selected"
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RoutingDecisionRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("candidate_model_names", [])
        data.setdefault("policy_constraints", {})
        data.setdefault("status", "selected")
        return cls(**data)


@dataclass
class ProviderAdapterResultRecord:
    provider_adapter_result_id: str
    routing_decision_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    provider_id: str
    model_name: str
    execution_backend: str
    adapter_kind: str = "routing_binding"
    status: str = "ready"
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProviderAdapterResultRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("adapter_kind", "routing_binding")
        data.setdefault("status", "ready")
        data.setdefault("summary", "")
        data.setdefault("metadata", {})
        return cls(**data)


@dataclass
class BackendExecutionRequestRecord:
    backend_execution_request_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    request_kind: str
    execution_backend: str
    provider_id: str
    model_name: str
    routing_decision_id: Optional[str] = None
    provider_adapter_result_id: Optional[str] = None
    backend_run_id: Optional[str] = None
    input_summary: str = ""
    input_refs: dict[str, Any] = field(default_factory=dict)
    source_refs: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BackendExecutionRequestRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("routing_decision_id", None)
        data.setdefault("provider_adapter_result_id", None)
        data.setdefault("backend_run_id", None)
        data.setdefault("input_summary", "")
        data.setdefault("input_refs", {})
        data.setdefault("source_refs", {})
        data.setdefault("status", "pending")
        return cls(**data)


@dataclass
class BackendExecutionResultRecord:
    backend_execution_result_id: str
    backend_execution_request_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    request_kind: str
    execution_backend: str
    provider_id: str
    model_name: str
    status: str
    backend_run_id: Optional[str] = None
    candidate_artifact_id: Optional[str] = None
    trace_id: Optional[str] = None
    outcome_summary: str = ""
    error: str = ""
    source_refs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BackendExecutionResultRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("backend_run_id", None)
        data.setdefault("candidate_artifact_id", None)
        data.setdefault("trace_id", None)
        data.setdefault("outcome_summary", "")
        data.setdefault("error", "")
        data.setdefault("source_refs", {})
        data.setdefault("metadata", {})
        return cls(**data)


@dataclass
class TokenBudgetRecord:
    token_budget_id: str
    scope: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    scope_ref: Optional[str] = None
    max_tokens_per_task: int = 0
    max_tokens_per_cycle: int = 0
    max_cost_usd_per_cycle: float = 0.0
    current_usage: dict[str, Any] = field(default_factory=dict)
    alert_threshold: dict[str, Any] = field(default_factory=dict)
    hard_stop_threshold: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TokenBudgetRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("scope_ref", None)
        data.setdefault("max_tokens_per_task", 0)
        data.setdefault("max_tokens_per_cycle", 0)
        data.setdefault("max_cost_usd_per_cycle", 0.0)
        data.setdefault("current_usage", {})
        data.setdefault("alert_threshold", {})
        data.setdefault("hard_stop_threshold", {})
        return cls(**data)


@dataclass
class CandidateRecord:
    candidate_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    candidate_kind: str
    source_record_type: str
    source_record_id: str
    artifact_id: Optional[str] = None
    execution_backend: Optional[str] = None
    provider_id: Optional[str] = None
    model_name: Optional[str] = None
    routing_decision_id: Optional[str] = None
    lifecycle_state: str = RecordLifecycleState.CANDIDATE.value
    validation_record_ids: list[str] = field(default_factory=list)
    latest_validation_id: Optional[str] = None
    latest_promotion_decision_id: Optional[str] = None
    latest_rejection_decision_id: Optional[str] = None
    latest_revocation_id: Optional[str] = None
    revoked_at: Optional[str] = None
    revoked_by: Optional[str] = None
    revocation_reason: str = ""
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CandidateRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("artifact_id", None)
        data.setdefault("execution_backend", None)
        data.setdefault("provider_id", None)
        data.setdefault("model_name", None)
        data.setdefault("routing_decision_id", None)
        data.setdefault("lifecycle_state", RecordLifecycleState.CANDIDATE.value)
        data.setdefault("validation_record_ids", [])
        data.setdefault("latest_validation_id", None)
        data.setdefault("latest_promotion_decision_id", None)
        data.setdefault("latest_rejection_decision_id", None)
        data.setdefault("latest_revocation_id", None)
        data.setdefault("revoked_at", None)
        data.setdefault("revoked_by", None)
        data.setdefault("revocation_reason", "")
        return cls(**data)


@dataclass
class ValidationRecord:
    validation_id: str
    candidate_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    validator_kind: str
    status: str = "passed"
    summary: str = ""
    details: str = ""
    evidence_refs: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ValidationRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("status", "passed")
        data.setdefault("summary", "")
        data.setdefault("details", "")
        data.setdefault("evidence_refs", {})
        return cls(**data)


@dataclass
class PromotionDecisionRecord:
    promotion_decision_id: str
    candidate_id: str
    task_id: str
    artifact_id: Optional[str]
    created_at: str
    updated_at: str
    actor: str
    lane: str
    decision: str = "promoted"
    reason: str = ""
    provenance_ref: Optional[str] = None
    validation_record_ids: list[str] = field(default_factory=list)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PromotionDecisionRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("decision", "promoted")
        data.setdefault("reason", "")
        data.setdefault("provenance_ref", None)
        data.setdefault("validation_record_ids", [])
        return cls(**data)


@dataclass
class RejectionDecisionRecord:
    rejection_decision_id: str
    candidate_id: str
    task_id: str
    artifact_id: Optional[str]
    created_at: str
    updated_at: str
    actor: str
    lane: str
    decision: str = "rejected"
    reason: str = ""
    trigger_event: str = ""
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RejectionDecisionRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("decision", "rejected")
        data.setdefault("reason", "")
        data.setdefault("trigger_event", "")
        return cls(**data)


@dataclass
class CandidateRevocationRecord:
    revocation_id: str
    candidate_id: str
    task_id: str
    artifact_id: Optional[str]
    created_at: str
    updated_at: str
    actor: str
    lane: str
    reason: str = ""
    impacted_output_ids: list[str] = field(default_factory=list)
    hook_status: str = "recorded"
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CandidateRevocationRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("reason", "")
        data.setdefault("impacted_output_ids", [])
        data.setdefault("hook_status", "recorded")
        return cls(**data)


@dataclass
class OutputDependencyRecord:
    output_dependency_id: str
    output_id: str
    task_id: str
    artifact_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    dependency_kind: str = "promoted_artifact_output"
    output_status: str = OutputStatus.PUBLISHED.value
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OutputDependencyRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("dependency_kind", "promoted_artifact_output")
        data.setdefault("output_status", OutputStatus.PUBLISHED.value)
        return cls(**data)


@dataclass
class RevocationImpactRecord:
    revocation_impact_id: str
    rollback_execution_id: str
    artifact_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    output_id: Optional[str] = None
    impacted_task_id: Optional[str] = None
    impacted_record_type: Optional[str] = None
    impacted_record_id: Optional[str] = None
    impact_kind: str = "output_invalidated"
    impact_status: str = "recorded"
    reason: str = ""
    source_ref: str = ""
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RevocationImpactRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("output_id", None)
        data.setdefault("impacted_task_id", None)
        data.setdefault("impacted_record_type", None)
        data.setdefault("impacted_record_id", None)
        data.setdefault("impact_kind", "output_invalidated")
        data.setdefault("impact_status", "recorded")
        data.setdefault("reason", "")
        data.setdefault("source_ref", "")
        return cls(**data)


@dataclass
class RollbackPlanRecord:
    rollback_plan_id: str
    task_id: str
    artifact_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    action_kind: str
    reason: str = ""
    affected_output_ids: list[str] = field(default_factory=list)
    affected_task_ids: list[str] = field(default_factory=list)
    source_event_ids: list[str] = field(default_factory=list)
    status: str = "planned"
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RollbackPlanRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("reason", "")
        data.setdefault("affected_output_ids", [])
        data.setdefault("affected_task_ids", [])
        data.setdefault("source_event_ids", [])
        data.setdefault("status", "planned")
        return cls(**data)


@dataclass
class RollbackExecutionRecord:
    rollback_execution_id: str
    rollback_plan_id: str
    task_id: str
    artifact_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    action_kind: str
    status: str = "completed"
    ok: bool = True
    reason: str = ""
    affected_output_ids: list[str] = field(default_factory=list)
    revocation_impact_ids: list[str] = field(default_factory=list)
    result_summary: str = ""
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RollbackExecutionRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("status", "completed")
        data.setdefault("ok", True)
        data.setdefault("reason", "")
        data.setdefault("affected_output_ids", [])
        data.setdefault("revocation_impact_ids", [])
        data.setdefault("result_summary", "")
        return cls(**data)


@dataclass
class ApprovalSessionRecord:
    approval_session_id: str
    approval_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    approval_type: str
    session_state: str = "pending"
    resumable: bool = True
    terminal: bool = False
    latest_checkpoint_id: Optional[str] = None
    latest_context_snapshot_id: Optional[str] = None
    latest_resume_token_id: Optional[str] = None
    linked_artifact_ids: list[str] = field(default_factory=list)
    decision_status: str = ApprovalStatus.PENDING.value
    decision_reason: str = ""
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApprovalSessionRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("session_state", "pending")
        data.setdefault("resumable", True)
        data.setdefault("terminal", False)
        data.setdefault("latest_checkpoint_id", None)
        data.setdefault("latest_context_snapshot_id", None)
        data.setdefault("latest_resume_token_id", None)
        data.setdefault("linked_artifact_ids", [])
        data.setdefault("decision_status", ApprovalStatus.PENDING.value)
        data.setdefault("decision_reason", "")
        return cls(**data)


@dataclass
class ApprovalDecisionContextRecord:
    context_snapshot_id: str
    approval_session_id: str
    approval_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    task_snapshot: dict[str, Any] = field(default_factory=dict)
    linked_artifact_ids: list[str] = field(default_factory=list)
    checkpoint_summary: str = ""
    pending_reason: str = ""
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApprovalDecisionContextRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("task_snapshot", {})
        data.setdefault("linked_artifact_ids", [])
        data.setdefault("checkpoint_summary", "")
        data.setdefault("pending_reason", "")
        return cls(**data)


@dataclass
class ApprovalResumeTokenRecord:
    resume_token_id: str
    approval_session_id: str
    approval_id: str
    checkpoint_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    token_ref: str
    status: str = "active"
    consumed_at: Optional[str] = None
    consumed_by: Optional[str] = None
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApprovalResumeTokenRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("status", "active")
        data.setdefault("consumed_at", None)
        data.setdefault("consumed_by", None)
        return cls(**data)


@dataclass
class SubsystemContractRecord:
    subsystem_contract_id: str
    subsystem_kind: str
    contract_name: str
    created_at: str
    updated_at: str
    version_tag: str
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    state_refs: list[str] = field(default_factory=list)
    active: bool = True
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SubsystemContractRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("input_contract", {})
        data.setdefault("output_contract", {})
        data.setdefault("state_refs", [])
        data.setdefault("active", True)
        return cls(**data)


@dataclass
class TaskProvenanceRecord:
    task_provenance_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    source_lane: str
    source_channel: str
    source_message_id: str
    source_user: str
    parent_task_id: Optional[str] = None
    routing_decision_id: Optional[str] = None
    source_event_ids: list[str] = field(default_factory=list)
    replay_input: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskProvenanceRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("parent_task_id", None)
        data.setdefault("routing_decision_id", None)
        data.setdefault("source_event_ids", [])
        data.setdefault("replay_input", {})
        return cls(**data)


@dataclass
class ArtifactProvenanceRecord:
    artifact_provenance_id: str
    artifact_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    producer_kind: str
    lifecycle_state: str
    execution_backend: Optional[str] = None
    backend_run_id: Optional[str] = None
    candidate_id: Optional[str] = None
    source_event_ids: list[str] = field(default_factory=list)
    source_refs: dict[str, Any] = field(default_factory=dict)
    replay_input: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ArtifactProvenanceRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("execution_backend", None)
        data.setdefault("backend_run_id", None)
        data.setdefault("candidate_id", None)
        data.setdefault("source_event_ids", [])
        data.setdefault("source_refs", {})
        data.setdefault("replay_input", {})
        return cls(**data)


@dataclass
class RoutingProvenanceRecord:
    routing_provenance_id: str
    routing_request_id: str
    routing_decision_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    selected_provider_id: str
    selected_model_name: str
    selected_execution_backend: str
    source_refs: dict[str, Any] = field(default_factory=dict)
    replay_input: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RoutingProvenanceRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("source_refs", {})
        data.setdefault("replay_input", {})
        return cls(**data)


@dataclass
class DecisionProvenanceRecord:
    decision_provenance_id: str
    decision_kind: str
    decision_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    source_artifact_ids: list[str] = field(default_factory=list)
    source_event_ids: list[str] = field(default_factory=list)
    source_refs: dict[str, Any] = field(default_factory=dict)
    replay_input: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DecisionProvenanceRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("source_artifact_ids", [])
        data.setdefault("source_event_ids", [])
        data.setdefault("source_refs", {})
        data.setdefault("replay_input", {})
        return cls(**data)


@dataclass
class PublishProvenanceRecord:
    publish_provenance_id: str
    output_id: str
    task_id: str
    artifact_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    output_status: str
    source_refs: dict[str, Any] = field(default_factory=dict)
    replay_input: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PublishProvenanceRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("source_refs", {})
        data.setdefault("replay_input", {})
        return cls(**data)


@dataclass
class RollbackProvenanceRecord:
    rollback_provenance_id: str
    rollback_plan_id: str
    rollback_execution_id: Optional[str]
    task_id: str
    artifact_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    action_kind: str
    source_refs: dict[str, Any] = field(default_factory=dict)
    replay_input: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RollbackProvenanceRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("rollback_execution_id", None)
        data.setdefault("source_refs", {})
        data.setdefault("replay_input", {})
        return cls(**data)


@dataclass
class MemoryProvenanceRecord:
    memory_provenance_id: str
    memory_candidate_id: str
    task_id: str
    created_at: str
    updated_at: str
    actor: str
    lane: str
    memory_type: str
    decision_kind: str = "candidate"
    source_refs: dict[str, Any] = field(default_factory=dict)
    replay_input: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryProvenanceRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("decision_kind", "candidate")
        data.setdefault("source_refs", {})
        data.setdefault("replay_input", {})
        return cls(**data)


@dataclass
class ReplayPlanRecord:
    replay_plan_id: str
    replay_kind: str
    source_record_type: str
    source_record_id: str
    task_id: Optional[str]
    created_at: str
    updated_at: str
    actor: str
    lane: str
    mode: str = "plan_only"
    replay_allowed: bool = True
    replay_input: dict[str, Any] = field(default_factory=dict)
    source_refs: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReplayPlanRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("task_id", None)
        data.setdefault("mode", "plan_only")
        data.setdefault("replay_allowed", True)
        data.setdefault("replay_input", {})
        data.setdefault("source_refs", {})
        data.setdefault("reason", "")
        return cls(**data)


@dataclass
class ReplayExecutionRecord:
    replay_execution_id: str
    replay_plan_id: str
    replay_kind: str
    task_id: Optional[str]
    created_at: str
    updated_at: str
    actor: str
    lane: str
    mode: str
    ok: bool = True
    source_record_id: str = ""
    result_kind: str = ReplayResultKind.MATCH.value
    reason: str = ""
    result_ref_id: Optional[str] = None
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReplayExecutionRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("task_id", None)
        data.setdefault("ok", True)
        data.setdefault("source_record_id", "")
        data.setdefault("result_kind", ReplayResultKind.MATCH.value)
        data.setdefault("reason", "")
        data.setdefault("result_ref_id", None)
        return cls(**data)


@dataclass
class ReplayResultRecord:
    replay_result_id: str
    replay_execution_id: str
    replay_kind: str
    source_record_id: str
    task_id: Optional[str]
    created_at: str
    updated_at: str
    result_kind: str = ReplayResultKind.MATCH.value
    expected_snapshot: dict[str, Any] = field(default_factory=dict)
    observed_snapshot: dict[str, Any] = field(default_factory=dict)
    drift_fields: list[str] = field(default_factory=list)
    reason: str = ""
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReplayResultRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("task_id", None)
        data.setdefault("result_kind", ReplayResultKind.MATCH.value)
        data.setdefault("expected_snapshot", {})
        data.setdefault("observed_snapshot", {})
        data.setdefault("drift_fields", [])
        data.setdefault("reason", "")
        return cls(**data)


@dataclass
class ModalityContractRecord:
    modality_contract_id: str
    contract_name: str
    created_at: str
    updated_at: str
    provider_id: str
    model_family: str
    input_modalities: list[str] = field(default_factory=list)
    output_modalities: list[str] = field(default_factory=list)
    enabled: bool = False
    policy_tags: list[str] = field(default_factory=list)
    control_flags: list[str] = field(default_factory=list)
    bounded_rules: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION
    version: str = LEGACY_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ModalityContractRecord":
        data = _apply_record_defaults(_extract_known_fields(cls, payload))
        data.setdefault("input_modalities", [])
        data.setdefault("output_modalities", [])
        data.setdefault("enabled", False)
        data.setdefault("policy_tags", [])
        data.setdefault("control_flags", [])
        data.setdefault("bounded_rules", {})
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
