"""Tests for runtime.quant.rejection_ledger."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from runtime.quant.rejection_ledger import RejectionLedger
from runtime.quant.rejection_types import RejectionRecord


def _make_record(rejection_id: str = "rej_test001", **overrides) -> RejectionRecord:
    defaults = dict(
        rejection_id=rejection_id,
        created_at="2026-03-19T12:00:00+00:00",
        strategy_id="test_strat_001",
        candidate_id="test_cand_001",
        run_id="run_001",
        source="test",
        family="test_family",
        symbol="NQ",
        timeframe="15m",
        source_lane="strategy_factory",
        rejection_stage="gate",
        primary_reason="low_trade_count",
        secondary_reasons=["low_sharpe"],
        regime_tags=["trending"],
        metrics={"sharpe": {"value": 0.3, "threshold": 0.5}},
        failure_summary="Test rejection",
        raw_reason="TEST_REASON",
        next_action_hint="mutate_family",
        confidence=0.9,
        evidence_refs=["ref_001"],
    )
    defaults.update(overrides)
    return RejectionRecord(**defaults)


@pytest.fixture
def tmp_ledger(tmp_path):
    return RejectionLedger(tmp_path)


def test_write_and_read(tmp_ledger):
    rec = _make_record()
    path = tmp_ledger.write(rec)
    assert path.exists()

    loaded = tmp_ledger.read(rec.rejection_id)
    assert loaded is not None
    assert loaded.rejection_id == rec.rejection_id
    assert loaded.strategy_id == rec.strategy_id
    assert loaded.secondary_reasons == ["low_sharpe"]
    assert loaded.metrics == rec.metrics


def test_write_idempotent(tmp_ledger):
    rec = _make_record()
    tmp_ledger.write(rec)
    tmp_ledger.write(rec)  # second write should be no-op
    assert tmp_ledger.count() == 1

    # Index should only have one entry (no duplicate)
    # Rebuild to clean any duplicates from append-only behavior
    tmp_ledger.rebuild_index()
    assert len(tmp_ledger.read_index()) == 1


def test_write_overwrite(tmp_ledger):
    rec1 = _make_record(failure_summary="v1")
    tmp_ledger.write(rec1)

    rec2 = _make_record(failure_summary="v2")
    tmp_ledger.write(rec2, overwrite=True)

    loaded = tmp_ledger.read(rec1.rejection_id)
    assert loaded.failure_summary == "v2"


def test_write_many(tmp_ledger):
    recs = [_make_record(f"rej_test{i:03d}") for i in range(5)]
    count = tmp_ledger.write_many(recs)
    assert count == 5
    assert tmp_ledger.count() == 5


def test_write_many_skips_existing(tmp_ledger):
    recs = [_make_record(f"rej_test{i:03d}") for i in range(3)]
    tmp_ledger.write_many(recs)
    # Write again with 2 new
    recs2 = recs + [_make_record("rej_test003"), _make_record("rej_test004")]
    count = tmp_ledger.write_many(recs2)
    assert count == 2  # only the 2 new ones
    assert tmp_ledger.count() == 5


def test_read_nonexistent(tmp_ledger):
    assert tmp_ledger.read("rej_nonexistent") is None


def test_read_all(tmp_ledger):
    for i in range(3):
        tmp_ledger.write(_make_record(f"rej_{i:03d}"))
    all_recs = tmp_ledger.read_all()
    assert len(all_recs) == 3
    ids = {r.rejection_id for r in all_recs}
    assert ids == {"rej_000", "rej_001", "rej_002"}


def test_index_appended_on_write(tmp_ledger):
    rec = _make_record()
    tmp_ledger.write(rec)
    entries = tmp_ledger.read_index()
    assert len(entries) == 1
    assert entries[0]["rejection_id"] == rec.rejection_id
    assert entries[0]["primary_reason"] == "low_trade_count"


def test_rebuild_index(tmp_ledger):
    for i in range(3):
        tmp_ledger.write(_make_record(f"rej_{i:03d}"))

    # Corrupt index
    tmp_ledger.index_path.write_text("garbage\n")
    assert len(tmp_ledger.read_index()) == 0

    # Rebuild
    count = tmp_ledger.rebuild_index()
    assert count == 3
    entries = tmp_ledger.read_index()
    assert len(entries) == 3


def test_summary(tmp_ledger):
    tmp_ledger.write(_make_record("rej_001", family="fam_a", primary_reason="low_sharpe"))
    tmp_ledger.write(_make_record("rej_002", family="fam_a", primary_reason="low_sharpe"))
    tmp_ledger.write(_make_record("rej_003", family="fam_b", primary_reason="high_drawdown"))

    s = tmp_ledger.summary()
    assert s["total"] == 3
    assert s["by_reason"]["low_sharpe"] == 2
    assert s["by_family"]["fam_a"] == 2


def test_exists(tmp_ledger):
    rec = _make_record()
    assert not tmp_ledger.exists(rec.rejection_id)
    tmp_ledger.write(rec)
    assert tmp_ledger.exists(rec.rejection_id)


def test_record_roundtrip():
    rec = _make_record()
    d = rec.to_dict()
    rec2 = RejectionRecord.from_dict(d)
    assert rec == rec2
