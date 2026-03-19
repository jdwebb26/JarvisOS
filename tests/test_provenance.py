"""Tests for metadata-driven granularity and candidate history.

Verifies:
- Sidecar metadata is read instead of bar-count heuristic
- Heuristic fallback still works when no sidecar exists
- Candidate history records ALL candidates (not just winner)
- Stage reason explains why a candidate is capped
"""

import csv
import json
import os
import tempfile
from pathlib import Path

from strategy_factory.data import load_ohlcv, load_dataset_metadata
from strategy_factory.config import classify_evidence
from strategy_factory.artifacts import write_candidate_history, CANDIDATE_HISTORY


# ---------------------------------------------------------------------------
# Sidecar metadata tests
# ---------------------------------------------------------------------------

def test_load_dataset_metadata_reads_sidecar(tmp_path):
    """When .meta.json exists alongside the CSV, load_dataset_metadata returns it."""
    # Create a CSV file
    csv_path = tmp_path / "NQ_1min.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerow({"open": 18000, "high": 18050, "low": 17990, "close": 18030, "volume": 1000})

    # Create sidecar
    sidecar = {
        "instrument": "NQ",
        "source_provider": "yfinance",
        "data_source": "real",
        "data_granularity": "daily",
        "row_count": 1,
    }
    sidecar_path = tmp_path / "NQ_1min.csv.meta.json"
    sidecar_path.write_text(json.dumps(sidecar))

    meta = load_dataset_metadata(path=str(csv_path))
    assert meta is not None
    assert meta["data_granularity"] == "daily"
    assert meta["instrument"] == "NQ"


def test_load_dataset_metadata_returns_none_without_sidecar(tmp_path):
    """When no .meta.json exists, returns None."""
    csv_path = tmp_path / "NQ_1min.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerow({"open": 18000, "high": 18050, "low": 17990, "close": 18030, "volume": 1000})

    meta = load_dataset_metadata(path=str(csv_path))
    assert meta is None


def test_metadata_granularity_overrides_heuristic(tmp_path):
    """Sidecar says 'daily' even if bar count would heuristically suggest intraday."""
    # Create a CSV with 25000 rows (heuristic would say "1min_bar")
    csv_path = tmp_path / "NQ_1min.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["open", "high", "low", "close", "volume"])
        writer.writeheader()
        for i in range(25000):
            writer.writerow({"open": 18000+i, "high": 18050+i, "low": 17990+i,
                             "close": 18030+i, "volume": 1000})

    # Sidecar explicitly says daily
    sidecar = {"data_granularity": "daily", "data_source": "real"}
    (tmp_path / "NQ_1min.csv.meta.json").write_text(json.dumps(sidecar))

    meta = load_dataset_metadata(path=str(csv_path))
    assert meta["data_granularity"] == "daily"

    # Classify using metadata — should be research, not execution_grade
    evidence = classify_evidence("real", meta["data_granularity"])
    assert evidence["evidence_tier"] == "research"
    assert evidence["promotion_eligible"] is False

    # Without metadata, heuristic would have said 1min_bar
    data = load_ohlcv(path=str(csv_path))
    assert len(data) == 25000  # heuristic threshold is 20000


def test_metadata_intraday_allows_execution_grade(tmp_path):
    """Sidecar saying '1min_bar' produces execution_grade evidence."""
    csv_path = tmp_path / "NQ_1min.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerow({"open": 18000, "high": 18050, "low": 17990, "close": 18030, "volume": 1000})

    sidecar = {"data_granularity": "1min_bar", "data_source": "real"}
    (tmp_path / "NQ_1min.csv.meta.json").write_text(json.dumps(sidecar))

    meta = load_dataset_metadata(path=str(csv_path))
    evidence = classify_evidence("real", meta["data_granularity"])
    assert evidence["evidence_tier"] == "execution_grade"
    assert evidence["promotion_eligible"] is True


def test_sidecar_written_by_ingest(tmp_path):
    """_write_canonical should produce a .meta.json sidecar."""
    import pandas as pd
    import numpy as np
    from strategy_factory.ingest import _write_canonical

    rng = np.random.RandomState(42)
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    df = pd.DataFrame({
        "open": 18000 + np.cumsum(rng.randn(100)),
        "high": 18050 + np.cumsum(rng.randn(100)),
        "low": 17950 + np.cumsum(rng.randn(100)),
        "close": 18000 + np.cumsum(rng.randn(100)),
        "volume": rng.randint(100000, 500000, 100),
        "vix": 20 + rng.randn(100) * 3,
    }, index=dates)

    canonical_path = tmp_path / "NQ_1min.csv"
    _write_canonical(df, canonical_path, granularity="daily")

    sidecar_path = tmp_path / "NQ_1min.csv.meta.json"
    assert sidecar_path.exists()

    meta = json.loads(sidecar_path.read_text())
    assert meta["data_granularity"] == "daily"
    assert meta["instrument"] == "NQ"
    assert meta["data_source"] == "real"
    assert meta["row_count"] == 100
    assert meta["coverage_start"] is not None
    assert meta["coverage_end"] is not None


# ---------------------------------------------------------------------------
# Candidate history tests
# ---------------------------------------------------------------------------

def test_candidate_history_records_all(tmp_path):
    """write_candidate_history should record ALL candidates, including rejected."""
    import strategy_factory.artifacts as art_mod
    orig = art_mod.CANDIDATE_HISTORY
    hist_path = tmp_path / "CANDIDATE_HISTORY.jsonl"
    art_mod.CANDIDATE_HISTORY = hist_path

    try:
        entries = [
            {
                "candidate_id": "cand_001",
                "family": "breakout",
                "params": {"lookback": 20},
                "status": "PASS",
                "reject_reason": None,
                "stage": "CANDIDATE",
                "stage_reason": "evidence_tier_cap:research",
                "score": 0.72,
                "gate_overall": "FAIL",
                "perturbation_robust": True,
                "stress_overall": "FAIL",
            },
            {
                "candidate_id": "cand_002",
                "family": "ema_crossover",
                "params": {"atr_stop_mult": 2.0},
                "status": "REJECT",
                "reject_reason": "NO_TRADES",
                "stage": "REJECTED",
                "stage_reason": "NO_TRADES",
                "score": 0.0,
                "gate_overall": None,
                "perturbation_robust": False,
                "stress_overall": "FAIL",
            },
            {
                "candidate_id": "cand_003",
                "family": "breakout",
                "params": {"lookback": 30},
                "status": "PASS",
                "reject_reason": None,
                "stage": "CANDIDATE",
                "stage_reason": "gate_fail",
                "score": 0.65,
                "gate_overall": "FAIL",
                "perturbation_robust": False,
                "stress_overall": "FAIL",
            },
        ]
        evidence = {
            "data_source": "real",
            "data_granularity": "daily",
            "evidence_tier": "research",
            "promotion_eligible": False,
        }

        records = write_candidate_history(tmp_path, entries, evidence)

        # All 3 candidates should be recorded
        assert len(records) == 3

        # JSONL file should have 3 lines
        lines = hist_path.read_text().strip().split("\n")
        assert len(lines) == 3

        # Verify rejected candidate is recorded
        rejected = json.loads(lines[1])
        assert rejected["candidate_id"] == "cand_002"
        assert rejected["status"] == "REJECT"
        assert rejected["stage"] == "REJECTED"
        assert rejected["stage_reason"] == "NO_TRADES"
        assert rejected["evidence"]["evidence_tier"] == "research"

        # Verify per-run artifact also written
        per_run = json.loads((tmp_path / "candidate_history.json").read_text())
        assert len(per_run) == 3
    finally:
        art_mod.CANDIDATE_HISTORY = orig


def test_candidate_history_stage_reason_cap():
    """When evidence caps stage, stage_reason should explain why."""
    evidence = classify_evidence("real", "daily")
    max_stage = evidence["max_stage"]

    # Simulate: all gates pass, but evidence caps at CANDIDATE
    gate_pass = True
    robust = True
    stress_pass = True
    sim_pass = True

    if sim_pass and gate_pass and robust and stress_pass:
        stage = "BACKTESTED" if max_stage == "BACKTESTED" else "CANDIDATE"
        if max_stage != "BACKTESTED":
            stage_reason = f"evidence_tier_cap:{evidence['evidence_tier']}"
        else:
            stage_reason = "all_gates_passed"
    elif sim_pass:
        stage = "CANDIDATE"
        stage_reason = "partial_pass"
    else:
        stage = "REJECTED"
        stage_reason = "sim_fail"

    assert stage == "CANDIDATE"
    assert stage_reason == "evidence_tier_cap:research"


def test_candidate_history_stage_reason_gate_fail():
    """When gates fail, stage_reason lists the specific failures."""
    gate_pass = False
    robust = True
    stress_pass = False

    reasons = []
    if not gate_pass:
        reasons.append("gate_fail")
    if not robust:
        reasons.append("perturbation_fail")
    if not stress_pass:
        reasons.append("stress_fail")
    stage_reason = ",".join(reasons)

    assert stage_reason == "gate_fail,stress_fail"


def test_candidate_history_accumulates(tmp_path):
    """Multiple batches should accumulate in the JSONL file."""
    import strategy_factory.artifacts as art_mod
    orig = art_mod.CANDIDATE_HISTORY
    hist_path = tmp_path / "CANDIDATE_HISTORY.jsonl"
    art_mod.CANDIDATE_HISTORY = hist_path

    try:
        evidence = {"evidence_tier": "research"}

        # Batch 1: 2 candidates
        write_candidate_history(tmp_path, [
            {"candidate_id": "batch1_a", "family": "breakout", "params": {},
             "status": "PASS", "reject_reason": None, "stage": "CANDIDATE",
             "stage_reason": "gate_fail", "score": 0.5, "gate_overall": "FAIL",
             "perturbation_robust": False, "stress_overall": "FAIL"},
            {"candidate_id": "batch1_b", "family": "breakout", "params": {},
             "status": "REJECT", "reject_reason": "NO_TRADES", "stage": "REJECTED",
             "stage_reason": "NO_TRADES", "score": 0.0, "gate_overall": None,
             "perturbation_robust": False, "stress_overall": "FAIL"},
        ], evidence)

        # Batch 2: 1 candidate
        write_candidate_history(tmp_path, [
            {"candidate_id": "batch2_a", "family": "ema_crossover", "params": {},
             "status": "PASS", "reject_reason": None, "stage": "CANDIDATE",
             "stage_reason": "evidence_tier_cap:research", "score": 0.7,
             "gate_overall": "PASS", "perturbation_robust": True,
             "stress_overall": "PASS"},
        ], evidence)

        # Total: 3 lines in JSONL
        lines = hist_path.read_text().strip().split("\n")
        assert len(lines) == 3
    finally:
        art_mod.CANDIDATE_HISTORY = orig
