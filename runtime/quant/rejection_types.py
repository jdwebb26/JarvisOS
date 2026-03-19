"""Canonical types for the Quant Rejection Intelligence subsystem."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


class PrimaryReason(str, enum.Enum):
    LOW_TRADE_COUNT = "low_trade_count"
    LOW_SHARPE = "low_sharpe"
    LOW_PROFIT_FACTOR = "low_profit_factor"
    HIGH_DRAWDOWN = "high_drawdown"
    REGIME_INSTABILITY = "regime_instability"
    STRESS_FAILURE = "stress_failure"
    OVERFIT_SUSPECTED = "overfit_suspected"
    EXECUTION_MISMATCH = "execution_mismatch"
    RISK_LIMIT_BREACH = "risk_limit_breach"
    DATA_QUALITY_ISSUE = "data_quality_issue"
    UNKNOWN = "unknown"


class NextActionHint(str, enum.Enum):
    AVOID_FAMILY = "avoid_family"
    MUTATE_FAMILY = "mutate_family"
    STRESS_IN_REGIME = "stress_in_regime"
    NEEDS_MORE_DATA = "needs_more_data"
    ARCHIVE_CANDIDATE = "archive_candidate"
    RETRY_WITH_FIX = "retry_with_fix"
    PROMISING_NEAR_MISS = "promising_near_miss"


class SourceLane(str, enum.Enum):
    STRATEGY_FACTORY = "strategy_factory"
    SIGMA = "sigma"
    EXECUTOR = "executor"
    REVIEW = "review"


class RejectionStage(str, enum.Enum):
    GATE = "gate"
    VALIDATION = "validation"
    EXECUTION = "execution"
    REVIEW = "review"


@dataclass
class RejectionRecord:
    rejection_id: str
    created_at: str
    strategy_id: str
    candidate_id: str
    run_id: str
    source: str
    family: str
    symbol: str
    timeframe: str
    source_lane: str
    rejection_stage: str
    primary_reason: str
    secondary_reasons: list[str] = field(default_factory=list)
    regime_tags: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    failure_summary: str = ""
    raw_reason: str = ""
    next_action_hint: str = ""
    confidence: float = 0.0
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RejectionRecord:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
