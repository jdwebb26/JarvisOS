"""Deterministic rule-based normalizer that maps raw rejection outputs to canonical RejectionRecords.

Supports three source formats:
  - Strategy Factory candidate_result.json / STRATEGIES.jsonl
  - Sigma strategy_rejection_packet
  - Executor execution_rejection_packet
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from runtime.quant.rejection_types import (
    NextActionHint,
    PrimaryReason,
    RejectionRecord,
    RejectionStage,
    SourceLane,
)

# ---------------------------------------------------------------------------
# Gate-text → PrimaryReason mapping (deterministic)
# ---------------------------------------------------------------------------

_GATE_REASON_MAP: dict[str, PrimaryReason] = {
    "ANY_FOLD_TRADES_LT_50": PrimaryReason.LOW_TRADE_COUNT,
    "MIN_TRADES": PrimaryReason.LOW_TRADE_COUNT,
    "min_trades_per_oos_fold": PrimaryReason.LOW_TRADE_COUNT,
    "SHARPE_BELOW_THRESHOLD": PrimaryReason.LOW_SHARPE,
    "sharpe": PrimaryReason.LOW_SHARPE,
    "PROFIT_FACTOR_BELOW_THRESHOLD": PrimaryReason.LOW_PROFIT_FACTOR,
    "profit_factor": PrimaryReason.LOW_PROFIT_FACTOR,
    "MAX_DRAWDOWN_EXCEEDED": PrimaryReason.HIGH_DRAWDOWN,
    "max_drawdown_proxy": PrimaryReason.HIGH_DRAWDOWN,
    "REGIME_INSTABILITY": PrimaryReason.REGIME_INSTABILITY,
    "STRESS_FAILURE": PrimaryReason.STRESS_FAILURE,
    "OVERFIT": PrimaryReason.OVERFIT_SUSPECTED,
}

_SIGMA_REASON_MAP: dict[str, PrimaryReason] = {
    "poor_oos": PrimaryReason.LOW_PROFIT_FACTOR,
    "low_sharpe": PrimaryReason.LOW_SHARPE,
    "high_drawdown": PrimaryReason.HIGH_DRAWDOWN,
    "insufficient_trades": PrimaryReason.LOW_TRADE_COUNT,
    "regime_fragile": PrimaryReason.REGIME_INSTABILITY,
    "stress_fail": PrimaryReason.STRESS_FAILURE,
}

_EXECUTOR_REASON_MAP: dict[str, PrimaryReason] = {
    "kill_switch_engaged": PrimaryReason.RISK_LIMIT_BREACH,
    "strategy_limit_breach": PrimaryReason.RISK_LIMIT_BREACH,
    "invalid_approval": PrimaryReason.EXECUTION_MISMATCH,
    "position_limit_exceeded": PrimaryReason.RISK_LIMIT_BREACH,
    "data_stale": PrimaryReason.DATA_QUALITY_ISSUE,
}

# ---------------------------------------------------------------------------
# Reason → default next-action hint
# ---------------------------------------------------------------------------

_REASON_TO_HINT: dict[PrimaryReason, NextActionHint] = {
    PrimaryReason.LOW_TRADE_COUNT: NextActionHint.NEEDS_MORE_DATA,
    PrimaryReason.LOW_SHARPE: NextActionHint.MUTATE_FAMILY,
    PrimaryReason.LOW_PROFIT_FACTOR: NextActionHint.MUTATE_FAMILY,
    PrimaryReason.HIGH_DRAWDOWN: NextActionHint.MUTATE_FAMILY,
    PrimaryReason.REGIME_INSTABILITY: NextActionHint.STRESS_IN_REGIME,
    PrimaryReason.STRESS_FAILURE: NextActionHint.STRESS_IN_REGIME,
    PrimaryReason.OVERFIT_SUSPECTED: NextActionHint.ARCHIVE_CANDIDATE,
    PrimaryReason.EXECUTION_MISMATCH: NextActionHint.RETRY_WITH_FIX,
    PrimaryReason.RISK_LIMIT_BREACH: NextActionHint.RETRY_WITH_FIX,
    PrimaryReason.DATA_QUALITY_ISSUE: NextActionHint.NEEDS_MORE_DATA,
    PrimaryReason.UNKNOWN: NextActionHint.ARCHIVE_CANDIDATE,
}


def _make_id(source_lane: str, strategy_id: str, created_at: str) -> str:
    h = hashlib.sha256(f"{source_lane}:{strategy_id}:{created_at}".encode()).hexdigest()[:12]
    return f"rej_{h}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Strategy Factory normalizer
# ---------------------------------------------------------------------------

def _extract_factory_secondary(gate_results: dict[str, Any]) -> list[str]:
    """Extract all failing gates as secondary reasons."""
    secondary: list[str] = []
    for gate_name, gate_data in gate_results.items():
        if gate_name == "overall":
            continue
        if isinstance(gate_data, dict) and not gate_data.get("pass", True):
            reason = _GATE_REASON_MAP.get(gate_name)
            if reason:
                secondary.append(reason.value)
    return secondary


def _extract_factory_metrics(gate_results: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for gate_name, gate_data in gate_results.items():
        if gate_name == "overall":
            continue
        if isinstance(gate_data, dict) and "value" in gate_data:
            metrics[gate_name] = {
                "value": gate_data["value"],
                "threshold": gate_data.get("threshold"),
                "pass": gate_data.get("pass"),
            }
    return metrics


def _build_factory_summary(candidate_id: str, reject_reason: str, gate_results: dict[str, Any]) -> str:
    parts = [f"{candidate_id} rejected at gate"]
    failing = []
    for gate_name, gate_data in gate_results.items():
        if gate_name == "overall":
            continue
        if isinstance(gate_data, dict) and not gate_data.get("pass", True):
            val = gate_data.get("value", "?")
            thresh = gate_data.get("threshold", "?")
            failing.append(f"{gate_name}={val} (need {thresh})")
    if failing:
        parts.append(": " + ", ".join(failing))
    return "".join(parts)


def normalize_factory_candidate(raw: dict[str, Any]) -> RejectionRecord | None:
    """Normalize a Strategy Factory candidate_result.json record."""
    status = raw.get("status", "")
    gate_overall = raw.get("gate_results", {}).get("overall", raw.get("gate_overall", ""))
    if status != "REJECT" and gate_overall != "FAIL":
        return None

    candidate_id = raw.get("candidate_id", "")
    strategy_id = candidate_id
    family = raw.get("logic_family_id", "")
    reject_reason = raw.get("reject_reason", "")
    gate_results = raw.get("gate_results", {})
    created_at = raw.get("produced_at", _now_iso())

    # Determine primary reason: explicit reject_reason > failing gates > heuristic from score/evidence
    primary = _GATE_REASON_MAP.get(reject_reason, None)
    if primary is None:
        # Try to infer from failing gates
        failing_reasons = _extract_factory_secondary(gate_results)
        primary = PrimaryReason(failing_reasons[0]) if failing_reasons else None
    if primary is None:
        # Heuristic: check score and perturbation/stress fields
        primary = _infer_reason_from_evidence(raw)
    secondary = [r for r in _extract_factory_secondary(gate_results) if r != primary.value]
    metrics = _extract_factory_metrics(gate_results)

    evidence = raw.get("evidence", {})
    timeframe = evidence.get("data_granularity", "")
    run_id = evidence.get("run_id", "")
    symbol = "NQ"

    # Near-miss detection: overall fail but most gates pass
    gate_pass_count = sum(
        1 for k, v in gate_results.items()
        if k != "overall" and isinstance(v, dict) and v.get("pass", False)
    )
    gate_total = sum(1 for k in gate_results if k != "overall")
    is_near_miss = gate_total > 0 and gate_pass_count >= gate_total - 1

    hint = NextActionHint.PROMISING_NEAR_MISS if is_near_miss else _REASON_TO_HINT.get(primary, NextActionHint.ARCHIVE_CANDIDATE)
    confidence = 0.9 if reject_reason else (0.7 if primary != PrimaryReason.UNKNOWN else 0.3)

    return RejectionRecord(
        rejection_id=_make_id("strategy_factory", strategy_id, created_at),
        created_at=created_at,
        strategy_id=strategy_id,
        candidate_id=candidate_id,
        run_id=run_id,
        source="candidate_result",
        family=family,
        symbol=symbol,
        timeframe=timeframe,
        source_lane=SourceLane.STRATEGY_FACTORY.value,
        rejection_stage=RejectionStage.GATE.value,
        primary_reason=primary.value,
        secondary_reasons=secondary,
        regime_tags=[],
        metrics=metrics,
        failure_summary=_build_factory_summary(candidate_id, reject_reason, gate_results),
        raw_reason=reject_reason,
        next_action_hint=hint.value,
        confidence=confidence,
        evidence_refs=[raw.get("artifact_dir", "")] if raw.get("artifact_dir") else [],
    )


# ---------------------------------------------------------------------------
# Sigma normalizer
# ---------------------------------------------------------------------------

def _parse_sigma_detail_metrics(detail: str) -> dict[str, Any]:
    """Parse 'PF 0.9 < 1.3; Sharpe 0.4 < 0.8; DD 20.0% > 15.0%; Trades 12 < 20'."""
    metrics: dict[str, Any] = {}
    _METRIC_NAMES = {"PF": "profit_factor", "Sharpe": "sharpe", "DD": "max_drawdown", "Trades": "trade_count"}
    for segment in detail.split(";"):
        segment = segment.strip()
        for prefix, name in _METRIC_NAMES.items():
            if segment.startswith(prefix):
                nums = re.findall(r"[\d.]+", segment)
                if len(nums) >= 2:
                    metrics[name] = {"value": float(nums[0]), "threshold": float(nums[1])}
                break
    return metrics


def _sigma_secondary_from_detail(detail: str) -> list[str]:
    reasons: list[str] = []
    if re.search(r"Trades\s+\d+\s*<", detail):
        reasons.append(PrimaryReason.LOW_TRADE_COUNT.value)
    if re.search(r"Sharpe\s+[\d.]+\s*<", detail):
        reasons.append(PrimaryReason.LOW_SHARPE.value)
    if re.search(r"PF\s+[\d.]+\s*<", detail):
        reasons.append(PrimaryReason.LOW_PROFIT_FACTOR.value)
    if re.search(r"DD\s+[\d.]+%?\s*>", detail):
        reasons.append(PrimaryReason.HIGH_DRAWDOWN.value)
    return reasons


def normalize_sigma_rejection(raw: dict[str, Any]) -> RejectionRecord | None:
    """Normalize a Sigma strategy_rejection_packet."""
    if raw.get("packet_type") != "strategy_rejection_packet":
        return None

    strategy_id = raw.get("strategy_id", "")
    rejection_reason = raw.get("rejection_reason", "")
    rejection_detail = raw.get("rejection_detail", "")
    created_at = raw.get("created_at", _now_iso())

    primary = _SIGMA_REASON_MAP.get(rejection_reason, PrimaryReason.UNKNOWN)
    secondary_all = _sigma_secondary_from_detail(rejection_detail)
    secondary = [r for r in secondary_all if r != primary.value]
    metrics = _parse_sigma_detail_metrics(rejection_detail)

    # Infer family from strategy_id prefix (e.g. "atlas-mr-001" → "mr" / "mean_reversion")
    family = _infer_family_from_id(strategy_id)

    summary = f"{strategy_id} rejected by Sigma: {rejection_detail}" if rejection_detail else f"{strategy_id} rejected by Sigma: {rejection_reason}"

    return RejectionRecord(
        rejection_id=_make_id("sigma", strategy_id, created_at),
        created_at=created_at,
        strategy_id=strategy_id,
        candidate_id=strategy_id,
        run_id="",
        source="sigma_rejection_packet",
        family=family,
        symbol="NQ",
        timeframe="",
        source_lane=SourceLane.SIGMA.value,
        rejection_stage=RejectionStage.VALIDATION.value,
        primary_reason=primary.value,
        secondary_reasons=secondary,
        regime_tags=[],
        metrics=metrics,
        failure_summary=summary,
        raw_reason=rejection_reason,
        next_action_hint=_REASON_TO_HINT.get(primary, NextActionHint.ARCHIVE_CANDIDATE).value,
        confidence=0.85,
        evidence_refs=raw.get("evidence_refs", []),
    )


# ---------------------------------------------------------------------------
# Executor normalizer
# ---------------------------------------------------------------------------

def normalize_executor_rejection(raw: dict[str, Any]) -> RejectionRecord | None:
    """Normalize an Executor execution_rejection_packet."""
    if raw.get("packet_type") != "execution_rejection_packet":
        return None

    strategy_id = raw.get("strategy_id", "")
    reason = raw.get("execution_rejection_reason", "")
    detail = raw.get("execution_rejection_detail", "")
    created_at = raw.get("created_at", _now_iso())
    order = raw.get("order_details", {})

    primary = _EXECUTOR_REASON_MAP.get(reason, PrimaryReason.UNKNOWN)
    family = _infer_family_from_id(strategy_id)
    symbol = order.get("symbol", "NQ")

    summary = f"{strategy_id} execution rejected: {detail}" if detail else f"{strategy_id} execution rejected: {reason}"

    return RejectionRecord(
        rejection_id=_make_id("executor", strategy_id, created_at),
        created_at=created_at,
        strategy_id=strategy_id,
        candidate_id=strategy_id,
        run_id="",
        source="executor_rejection_packet",
        family=family,
        symbol=symbol,
        timeframe="",
        source_lane=SourceLane.EXECUTOR.value,
        rejection_stage=RejectionStage.EXECUTION.value,
        primary_reason=primary.value,
        secondary_reasons=[],
        regime_tags=[],
        metrics={"order_details": order} if order else {},
        failure_summary=summary,
        raw_reason=reason,
        next_action_hint=_REASON_TO_HINT.get(primary, NextActionHint.RETRY_WITH_FIX).value,
        confidence=0.95,
        evidence_refs=raw.get("evidence_refs", []),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAMILY_PREFIX_MAP: dict[str, str] = {
    "mr": "mean_reversion",
    "ema": "ema_crossover",
    "gap": "gap_fade",
    "bo": "breakout",
    "brk": "breakout",
    "mom": "momentum",
    "rev": "mean_reversion",
}


def _infer_reason_from_evidence(raw: dict[str, Any]) -> PrimaryReason:
    """Best-effort reason inference when no explicit reject_reason or gate_results exist.

    Uses heuristic signals from STRATEGIES.jsonl-style records:
    - stress_overall == "FAIL" → stress_failure
    - perturbation_robust == False → overfit_suspected
    - score < 0.3 → low_profit_factor (weak overall)
    - fold_count == 0 or 1 with low score → low_trade_count
    """
    stress = raw.get("stress_overall", "")
    if stress == "FAIL":
        return PrimaryReason.STRESS_FAILURE
    if raw.get("perturbation_robust") is False:
        return PrimaryReason.OVERFIT_SUSPECTED
    score = raw.get("score")
    if isinstance(score, (int, float)):
        if score < 0.3:
            return PrimaryReason.LOW_PROFIT_FACTOR
        if score < 0.5:
            return PrimaryReason.LOW_SHARPE
    fold_count = raw.get("fold_count", 0)
    if fold_count <= 1:
        return PrimaryReason.LOW_TRADE_COUNT
    return PrimaryReason.UNKNOWN


def _infer_family_from_id(strategy_id: str) -> str:
    """Best-effort family extraction from strategy IDs like 'atlas-mr-001'."""
    parts = strategy_id.replace("_", "-").split("-")
    for part in parts:
        if part in _FAMILY_PREFIX_MAP:
            return _FAMILY_PREFIX_MAP[part]
    return strategy_id.split("-")[0] if "-" in strategy_id else ""


def normalize_any(raw: dict[str, Any]) -> RejectionRecord | None:
    """Auto-detect source type and normalize."""
    ptype = raw.get("packet_type", "")
    if ptype == "strategy_rejection_packet":
        return normalize_sigma_rejection(raw)
    if ptype == "execution_rejection_packet":
        return normalize_executor_rejection(raw)
    # Strategy Factory: has status or gate_overall
    if raw.get("status") == "REJECT" or raw.get("gate_overall") == "FAIL":
        return normalize_factory_candidate(raw)
    return None
