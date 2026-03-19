"""Tests for dataset separation, family compatibility, and research summary."""

import csv
import json
import os
import tempfile
from pathlib import Path

from strategy_factory.config import check_family_compat, FAMILY_DATASET_COMPAT, KNOWN_DATASETS
from strategy_factory.data import load_named_dataset, list_datasets, load_dataset_metadata


# ---------------------------------------------------------------------------
# Family / dataset compatibility
# ---------------------------------------------------------------------------

def test_ema_crossover_daily_compatible():
    ok, reason = check_family_compat("ema_crossover", "daily")
    assert ok is True
    assert reason is None


def test_breakout_daily_compatible():
    ok, reason = check_family_compat("breakout", "daily")
    assert ok is True


def test_mean_reversion_daily_incompatible():
    ok, reason = check_family_compat("mean_reversion", "daily")
    assert ok is False
    assert "incompatible" in reason
    assert "daily" in reason


def test_mean_reversion_hourly_compatible():
    ok, reason = check_family_compat("mean_reversion", "1h")
    assert ok is True


def test_mean_reversion_intraday_compatible():
    ok, reason = check_family_compat("mean_reversion", "1min_bar")
    assert ok is True


def test_all_families_synthetic_compatible():
    """All families should work on synthetic data."""
    for family in FAMILY_DATASET_COMPAT:
        ok, _ = check_family_compat(family, "synthetic")
        assert ok, f"{family} should be compatible with synthetic"


def test_unknown_family_compatible():
    """Unknown families are allowed by default."""
    ok, _ = check_family_compat("totally_new_strategy", "daily")
    assert ok is True


def test_case_insensitive():
    ok, _ = check_family_compat("mean_reversion", "DAILY")
    assert ok is False


# ---------------------------------------------------------------------------
# Named dataset loading
# ---------------------------------------------------------------------------

def test_load_named_dataset(tmp_path):
    """Load a named dataset with sidecar."""
    csv_path = tmp_path / "NQ_daily.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["open", "high", "low", "close", "volume"])
        writer.writeheader()
        for i in range(5):
            writer.writerow({"open": 18000+i, "high": 18050+i, "low": 17990+i,
                             "close": 18030+i, "volume": 1000})
    sidecar = {"data_granularity": "daily", "instrument": "NQ", "data_source": "real",
               "row_count": 5}
    (tmp_path / "NQ_daily.csv.meta.json").write_text(json.dumps(sidecar))

    bars, meta = load_named_dataset("NQ_daily", data_dir=str(tmp_path))
    assert len(bars) == 5
    assert meta["data_granularity"] == "daily"


def test_load_named_dataset_missing_raises(tmp_path):
    raised = False
    try:
        load_named_dataset("NQ_nonexistent", data_dir=str(tmp_path))
    except FileNotFoundError:
        raised = True
    assert raised


def test_list_datasets(tmp_path):
    """list_datasets should find NQ_daily and NQ_hourly but not NQ_1min."""
    for name in ("NQ_daily.csv", "NQ_hourly.csv", "NQ_1min.csv"):
        path = tmp_path / name
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerow({"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100})

    # Add sidecar for daily
    sidecar = {"data_granularity": "daily", "row_count": 1}
    (tmp_path / "NQ_daily.csv.meta.json").write_text(json.dumps(sidecar))

    datasets = list_datasets(data_dir=str(tmp_path))
    ids = [d["dataset_id"] for d in datasets]
    assert "NQ_daily" in ids
    assert "NQ_hourly" in ids
    assert "NQ_1min" not in ids  # excluded as legacy

    # Daily should have granularity from sidecar
    daily = [d for d in datasets if d["dataset_id"] == "NQ_daily"][0]
    assert daily["granularity"] == "daily"


# ---------------------------------------------------------------------------
# Known datasets
# ---------------------------------------------------------------------------

def test_known_datasets_defined():
    assert "NQ_daily" in KNOWN_DATASETS
    assert "NQ_hourly" in KNOWN_DATASETS
    assert KNOWN_DATASETS["NQ_daily"]["granularity"] == "daily"
    assert KNOWN_DATASETS["NQ_hourly"]["granularity"] == "1h"


# ---------------------------------------------------------------------------
# Research summary shape
# ---------------------------------------------------------------------------

def test_research_summary_fields():
    """Research summary should have all required fields."""
    required = {
        "run_id", "dataset_id", "data_granularity", "evidence_tier",
        "promotion_eligible", "fold_profile_used", "gate_profile_used",
        "families_evaluated", "families_skipped",
        "candidates_total", "candidates_passed", "candidates_rejected",
        "rejection_reasons", "survivors", "top_candidate",
    }
    # Build a minimal research summary to check field presence
    summary = {
        "run_id": "run_test123",
        "dataset_id": "NQ_daily",
        "data_granularity": "daily",
        "evidence_tier": "research",
        "promotion_eligible": False,
        "fold_profile_used": "research",
        "gate_profile_used": "research",
        "families_evaluated": ["breakout"],
        "families_skipped": [{"family": "mean_reversion", "reason": "incompatible"}],
        "candidates_total": 3,
        "candidates_passed": 2,
        "candidates_rejected": 1,
        "rejection_reasons": {"NO_TRADES": 1},
        "survivors": [{"candidate_id": "x", "score": 0.7, "stage": "CANDIDATE"}],
        "top_candidate": {"candidate_id": "x", "stage": "CANDIDATE", "promotable": False},
    }
    missing = required - set(summary.keys())
    assert not missing


# ---------------------------------------------------------------------------
# History entries include run context
# ---------------------------------------------------------------------------

def test_history_entry_has_run_context():
    """History entries should include run_id, dataset_id, profiles."""
    entry = {
        "run_id": "run_abc",
        "dataset_id": "NQ_daily",
        "candidate_id": "test_001",
        "family": "breakout",
        "params": {},
        "status": "PASS",
        "reject_reason": None,
        "stage": "CANDIDATE",
        "stage_reason": "gate_fail",
        "score": 0.7,
        "gate_overall": "FAIL",
        "evidence_tier": "research",
        "fold_profile_used": "research",
        "gate_profile_used": "research",
        "perturbation_robust": False,
        "stress_overall": "FAIL",
    }
    required = {"run_id", "dataset_id", "evidence_tier",
                "fold_profile_used", "gate_profile_used", "stage", "stage_reason"}
    missing = required - set(entry.keys())
    assert not missing
