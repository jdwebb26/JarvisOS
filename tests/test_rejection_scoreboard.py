"""Tests for runtime.quant.rejection_scoreboard."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from runtime.quant.rejection_types import RejectionRecord
from runtime.quant.rejection_scoreboard import (
    COOLDOWN_THRESHOLD,
    build_family_scoreboard,
    build_learning_summary,
    build_regime_scoreboard,
    write_scoreboards,
)
from runtime.quant.rejection_ledger import RejectionLedger


def _rec(
    family: str = "ema_crossover",
    reason: str = "low_trade_count",
    hint: str = "mutate_family",
    regime_tags: list[str] | None = None,
    **kw,
) -> RejectionRecord:
    return RejectionRecord(
        rejection_id=kw.get("rejection_id", f"rej_{id(kw)}"),
        created_at="2026-03-19T12:00:00+00:00",
        strategy_id=kw.get("strategy_id", "strat_001"),
        candidate_id="cand_001",
        run_id="run_001",
        source="test",
        family=family,
        symbol="NQ",
        timeframe="15m",
        source_lane="strategy_factory",
        rejection_stage="gate",
        primary_reason=reason,
        secondary_reasons=[],
        regime_tags=regime_tags or [],
        metrics={},
        failure_summary="test",
        raw_reason="TEST",
        next_action_hint=hint,
        confidence=0.9,
        evidence_refs=[],
    )


class TestFamilyScoreboard:
    def test_basic(self):
        records = [
            _rec("ema", "low_sharpe", rejection_id="r1"),
            _rec("ema", "low_sharpe", rejection_id="r2"),
            _rec("breakout", "high_drawdown", rejection_id="r3"),
        ]
        sb = build_family_scoreboard(records)
        assert sb["total_families"] == 2
        assert sb["families"]["ema"]["rejected_count"] == 2
        assert sb["families"]["ema"]["dominant_rejection_reason"] == "low_sharpe"
        assert sb["families"]["breakout"]["rejected_count"] == 1

    def test_promoted_counts(self):
        records = [_rec("ema", rejection_id="r1")]
        sb = build_family_scoreboard(records, promoted_families={"ema"}, paper_families={"ema"})
        assert sb["families"]["ema"]["promoted_count"] == 1
        assert sb["families"]["ema"]["paper_approved_count"] == 1

    def test_near_miss_counted(self):
        records = [_rec("ema", hint="promising_near_miss", rejection_id="r1")]
        sb = build_family_scoreboard(records)
        assert sb["families"]["ema"]["near_miss_count"] == 1

    def test_cooldown_flag(self):
        records = [_rec("ema", rejection_id=f"r{i}") for i in range(COOLDOWN_THRESHOLD)]
        sb = build_family_scoreboard(records)
        assert sb["families"]["ema"]["cooldown"] is True

    def test_no_cooldown_if_promoted(self):
        records = [_rec("ema", rejection_id=f"r{i}") for i in range(COOLDOWN_THRESHOLD)]
        sb = build_family_scoreboard(records, promoted_families={"ema"})
        assert sb["families"]["ema"]["cooldown"] is False


class TestRegimeScoreboard:
    def test_basic(self):
        records = [
            _rec(regime_tags=["trending"], rejection_id="r1"),
            _rec(regime_tags=["trending", "volatile"], rejection_id="r2"),
            _rec(regime_tags=["sideways"], rejection_id="r3"),
        ]
        sb = build_regime_scoreboard(records)
        assert sb["regimes"]["trending"]["total_rejections"] == 2
        assert sb["regimes"]["volatile"]["total_rejections"] == 1
        assert sb["regimes"]["sideways"]["total_rejections"] == 1

    def test_untagged(self):
        records = [_rec(regime_tags=[], rejection_id="r1")]
        sb = build_regime_scoreboard(records)
        assert "untagged" in sb["regimes"]


class TestLearningSummary:
    def test_basic(self):
        records = [
            _rec("ema", "low_sharpe", rejection_id="r1"),
            _rec("ema", "low_sharpe", rejection_id="r2"),
            _rec("bo", "high_drawdown", rejection_id="r3"),
        ]
        ls = build_learning_summary(records)
        assert ls["total_rejections"] == 3
        assert ls["top_rejection_reasons"][0]["reason"] == "low_sharpe"
        assert ls["top_failing_families"][0]["family"] == "ema"

    def test_regime_blind_spots(self):
        records = [_rec(regime_tags=["trending"], rejection_id="r1")]
        ls = build_learning_summary(records, promoted_families=set())
        assert "trending" in ls["top_regime_blind_spots"]

    def test_no_blind_spot_if_promoted(self):
        records = [_rec("ema", regime_tags=["trending"], rejection_id="r1")]
        ls = build_learning_summary(records, promoted_families={"ema"})
        assert "trending" not in ls["top_regime_blind_spots"]

    def test_shifts_for_low_trade_count(self):
        records = [_rec(reason="low_trade_count", rejection_id=f"r{i}") for i in range(3)]
        ls = build_learning_summary(records)
        assert any("trade count" in s.lower() for s in ls["recommended_exploration_shifts"])


class TestWriteScoreboards:
    def test_writes_files(self, tmp_path):
        ledger = RejectionLedger(tmp_path)
        for i in range(3):
            ledger.write(_rec(rejection_id=f"rej_{i:03d}"))

        paths = write_scoreboards(ledger=ledger)
        assert "family_scoreboard" in paths
        assert "regime_scoreboard" in paths
        assert "learning_summary" in paths
        for p in paths.values():
            assert p.exists()
            data = json.loads(p.read_text())
            assert "generated_at" in data
