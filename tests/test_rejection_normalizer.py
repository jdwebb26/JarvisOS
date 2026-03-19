"""Tests for runtime.quant.rejection_normalizer."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.quant.rejection_normalizer import (
    normalize_any,
    normalize_executor_rejection,
    normalize_factory_candidate,
    normalize_sigma_rejection,
)
from runtime.quant.rejection_types import PrimaryReason, NextActionHint


# ---------------------------------------------------------------------------
# Strategy Factory normalization
# ---------------------------------------------------------------------------

FACTORY_CANDIDATE = {
    "candidate_id": "ema_crossover_cd_default",
    "logic_family_id": "ema_crossover_cd",
    "status": "REJECT",
    "reject_reason": "ANY_FOLD_TRADES_LT_50",
    "fold_count": 1,
    "gate_results": {
        "min_trades_per_oos_fold": {"value": 12, "threshold": 50, "pass": False},
        "profit_factor": {"value": 2.9774, "threshold": 1.2, "pass": True},
        "sharpe": {"value": 0.37, "threshold": 0.5, "pass": False},
        "sortino": {"value": 1.01, "threshold": 0.5, "pass": True},
        "max_drawdown_proxy": {"value": 0.08, "threshold": 0.25, "pass": True},
        "overall": "FAIL",
    },
    "produced_at": "2026-03-19T17:50:36.938706+00:00",
    "evidence": {
        "data_granularity": "15m",
        "run_id": "run_abc123",
    },
}


def test_factory_basic():
    rec = normalize_factory_candidate(FACTORY_CANDIDATE)
    assert rec is not None
    assert rec.strategy_id == "ema_crossover_cd_default"
    assert rec.candidate_id == "ema_crossover_cd_default"
    assert rec.family == "ema_crossover_cd"
    assert rec.primary_reason == PrimaryReason.LOW_TRADE_COUNT.value
    assert rec.source_lane == "strategy_factory"
    assert rec.rejection_stage == "gate"
    assert rec.symbol == "NQ"
    assert rec.timeframe == "15m"
    assert rec.run_id == "run_abc123"
    assert rec.raw_reason == "ANY_FOLD_TRADES_LT_50"
    assert rec.rejection_id.startswith("rej_")


def test_factory_secondary_reasons():
    rec = normalize_factory_candidate(FACTORY_CANDIDATE)
    assert rec is not None
    # sharpe also failed, so should appear in secondary
    assert PrimaryReason.LOW_SHARPE.value in rec.secondary_reasons
    # primary reason should NOT be duplicated in secondary
    assert PrimaryReason.LOW_TRADE_COUNT.value not in rec.secondary_reasons


def test_factory_metrics():
    rec = normalize_factory_candidate(FACTORY_CANDIDATE)
    assert rec is not None
    assert "profit_factor" in rec.metrics
    assert rec.metrics["profit_factor"]["value"] == 2.9774
    assert rec.metrics["sharpe"]["pass"] is False


def test_factory_near_miss():
    """Single gate failure → near-miss → promising_near_miss hint."""
    candidate = {
        "candidate_id": "test_nm_001",
        "logic_family_id": "test_fam",
        "status": "REJECT",
        "reject_reason": "sharpe",
        "gate_results": {
            "profit_factor": {"value": 1.8, "threshold": 1.2, "pass": True},
            "sharpe": {"value": 0.45, "threshold": 0.5, "pass": False},
            "sortino": {"value": 1.5, "threshold": 0.5, "pass": True},
            "overall": "FAIL",
        },
        "produced_at": "2026-03-19T12:00:00+00:00",
    }
    rec = normalize_factory_candidate(candidate)
    assert rec is not None
    assert rec.next_action_hint == NextActionHint.PROMISING_NEAR_MISS.value


def test_factory_pass_returns_none():
    candidate = {
        "candidate_id": "pass_001",
        "status": "PASS",
        "gate_results": {"overall": "PASS"},
    }
    assert normalize_factory_candidate(candidate) is None


def test_factory_strategies_jsonl_format():
    """STRATEGIES.jsonl uses gate_overall instead of status."""
    entry = {
        "candidate_id": "mean_reversion_eb20bd43",
        "logic_family_id": "mean_reversion",
        "gate_overall": "FAIL",
        "produced_at": "2026-03-19T11:17:09+00:00",
        "gate_results": {
            "sharpe": {"value": 0.3, "threshold": 0.5, "pass": False},
            "overall": "FAIL",
        },
        "evidence": {"data_granularity": "1h", "run_id": "run_xyz"},
    }
    rec = normalize_factory_candidate(entry)
    assert rec is not None
    assert rec.family == "mean_reversion"


# ---------------------------------------------------------------------------
# Sigma normalization
# ---------------------------------------------------------------------------

SIGMA_REJECTION = {
    "packet_id": "sigma-strategy-rejection-2026-03-19T051458-8002cefb",
    "packet_type": "strategy_rejection_packet",
    "lane": "sigma",
    "created_at": "2026-03-19T05:14:58.487949+00:00",
    "thesis": "Strategy atlas-mr-001 rejected: PF 0.9 < 1.3; Sharpe 0.4 < 0.8; DD 20.0% > 15.0%; Trades 12 < 20",
    "strategy_id": "atlas-mr-001",
    "rejection_reason": "poor_oos",
    "rejection_detail": "PF 0.9 < 1.3; Sharpe 0.4 < 0.8; DD 20.0% > 15.0%; Trades 12 < 20",
    "evidence_refs": ["atlas-candidate-2026-03-19T051458-f44159f7"],
}


def test_sigma_basic():
    rec = normalize_sigma_rejection(SIGMA_REJECTION)
    assert rec is not None
    assert rec.strategy_id == "atlas-mr-001"
    assert rec.primary_reason == PrimaryReason.LOW_PROFIT_FACTOR.value
    assert rec.source_lane == "sigma"
    assert rec.rejection_stage == "validation"
    assert rec.family == "mean_reversion"  # inferred from "mr"
    assert len(rec.evidence_refs) == 1


def test_sigma_secondary_from_detail():
    rec = normalize_sigma_rejection(SIGMA_REJECTION)
    assert rec is not None
    # Detail mentions Sharpe, DD, and Trades failures too
    assert PrimaryReason.LOW_SHARPE.value in rec.secondary_reasons
    assert PrimaryReason.HIGH_DRAWDOWN.value in rec.secondary_reasons
    assert PrimaryReason.LOW_TRADE_COUNT.value in rec.secondary_reasons


def test_sigma_metrics_parsed():
    rec = normalize_sigma_rejection(SIGMA_REJECTION)
    assert rec is not None
    assert "profit_factor" in rec.metrics
    assert rec.metrics["profit_factor"]["value"] == 0.9
    assert rec.metrics["profit_factor"]["threshold"] == 1.3


def test_sigma_non_rejection_returns_none():
    validation = {"packet_type": "validation_packet", "strategy_id": "x"}
    assert normalize_sigma_rejection(validation) is None


# ---------------------------------------------------------------------------
# Executor normalization
# ---------------------------------------------------------------------------

EXECUTOR_REJECTION = {
    "packet_id": "executor-execution-rejection-2026-03-19T093321-17278396",
    "packet_type": "execution_rejection_packet",
    "lane": "executor",
    "created_at": "2026-03-19T09:33:21.026360+00:00",
    "thesis": "Execution refused for atlas-gap-65f8a3d6: kill switch engaged",
    "strategy_id": "atlas-gap-65f8a3d6",
    "execution_rejection_reason": "kill_switch_engaged",
    "execution_rejection_detail": "Kill switch is currently engaged. All execution halted.",
    "order_details": {"symbol": "NQ", "side": "long", "quantity": 1},
    "evidence_refs": [],
}


def test_executor_basic():
    rec = normalize_executor_rejection(EXECUTOR_REJECTION)
    assert rec is not None
    assert rec.strategy_id == "atlas-gap-65f8a3d6"
    assert rec.primary_reason == PrimaryReason.RISK_LIMIT_BREACH.value
    assert rec.source_lane == "executor"
    assert rec.rejection_stage == "execution"
    assert rec.family == "gap_fade"  # inferred from "gap"
    assert rec.symbol == "NQ"
    assert rec.confidence == 0.95


def test_executor_invalid_approval():
    raw = dict(EXECUTOR_REJECTION)
    raw["execution_rejection_reason"] = "invalid_approval"
    raw["strategy_id"] = "atlas-ema-test"
    rec = normalize_executor_rejection(raw)
    assert rec is not None
    assert rec.primary_reason == PrimaryReason.EXECUTION_MISMATCH.value


def test_executor_non_rejection_returns_none():
    intent = {"packet_type": "execution_intent_packet", "strategy_id": "x"}
    assert normalize_executor_rejection(intent) is None


# ---------------------------------------------------------------------------
# normalize_any auto-detection
# ---------------------------------------------------------------------------

def test_normalize_any_factory():
    rec = normalize_any(FACTORY_CANDIDATE)
    assert rec is not None
    assert rec.source_lane == "strategy_factory"


def test_normalize_any_sigma():
    rec = normalize_any(SIGMA_REJECTION)
    assert rec is not None
    assert rec.source_lane == "sigma"


def test_normalize_any_executor():
    rec = normalize_any(EXECUTOR_REJECTION)
    assert rec is not None
    assert rec.source_lane == "executor"


def test_normalize_any_unknown():
    assert normalize_any({"some": "data"}) is None


# ---------------------------------------------------------------------------
# Deterministic ID generation
# ---------------------------------------------------------------------------

def test_id_deterministic():
    rec1 = normalize_factory_candidate(FACTORY_CANDIDATE)
    rec2 = normalize_factory_candidate(FACTORY_CANDIDATE)
    assert rec1 is not None and rec2 is not None
    assert rec1.rejection_id == rec2.rejection_id


def test_id_unique_across_sources():
    rec_factory = normalize_factory_candidate(FACTORY_CANDIDATE)
    rec_sigma = normalize_sigma_rejection(SIGMA_REJECTION)
    rec_executor = normalize_executor_rejection(EXECUTOR_REJECTION)
    ids = {r.rejection_id for r in [rec_factory, rec_sigma, rec_executor] if r}
    assert len(ids) == 3
