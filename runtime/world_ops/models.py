#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from runtime.core.models import CORE_SCHEMA_VERSION


@dataclass
class WorldFeedRecord:
    feed_id: str
    created_at: str
    updated_at: str
    label: str
    purpose: str
    ingestion_kind: str = "manual"
    configured_url: str = ""
    enabled: bool = True
    collection_interval_hint: str = ""
    backend_ref: str = ""
    parser_ref: str = ""
    tags: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    allowed_operations: list[str] = field(default_factory=lambda: ["collect", "summarize"])
    status: str = "active"
    owner: str = ""
    runtime_notes: str = ""
    last_collection_status: str = ""
    last_collected_at: str = ""
    last_error: str = ""
    last_backend_health: dict[str, Any] = field(default_factory=dict)
    last_real_event_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorldFeedRecord":
        return cls(**payload)


@dataclass
class WorldEventRecord:
    event_id: str
    created_at: str
    updated_at: str
    collected_at: str
    normalized_at: str
    feed_id: str
    status: str
    title: str
    summary: str
    region: str = ""
    event_type: str = ""
    risk_posture: str = "unknown"
    external_ref: str = ""
    source_records: list[dict[str, Any]] = field(default_factory=list)
    result_records: list[dict[str, Any]] = field(default_factory=list)
    evidence_bundle_ref: Optional[dict[str, Any]] = None
    raw_event: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorldEventRecord":
        return cls(**payload)


@dataclass
class WorldStatusSnapshotRecord:
    snapshot_id: str
    created_at: str
    updated_at: str
    actor: str
    status: str
    event_count: int
    degraded_feed_count: int
    risk_posture_summary: dict[str, int] = field(default_factory=dict)
    region_summary: dict[str, int] = field(default_factory=dict)
    event_type_summary: dict[str, int] = field(default_factory=dict)
    latest_event_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorldStatusSnapshotRecord":
        return cls(**payload)


@dataclass
class WorldOpsBriefRecord:
    brief_id: str
    created_at: str
    updated_at: str
    actor: str
    title: str
    status: str
    markdown_path: str
    summary: str
    snapshot_id: str = ""
    latest_event_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CORE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorldOpsBriefRecord":
        return cls(**payload)
