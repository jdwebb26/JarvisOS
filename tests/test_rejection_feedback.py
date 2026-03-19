"""Tests for runtime.quant.rejection_feedback."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from runtime.quant.rejection_types import RejectionRecord
from runtime.quant.rejection_feedback import (
    build_atlas_feedback,
    build_feedback_snapshot,
    build_fish_feedback,
    build_kitt_feedback,
    export_feedback,
    render_feedback_markdown,
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


class TestAtlasFeedback:
    def test_basic(self):
        records = [
            _rec("ema", "low_sharpe", "mutate_family", rejection_id="r1"),
            _rec("ema", "low_sharpe", "mutate_family", rejection_id="r2"),
            _rec("breakout", "high_drawdown", "archive_candidate", rejection_id="r3"),
        ]
        fb = build_atlas_feedback(records)
        assert fb["target"] == "atlas"
        assert fb["total_rejections"] == 3
        assert "ema" in fb["families"]
        assert fb["families"]["ema"]["rejection_count"] == 2
        assert fb["families"]["ema"]["dominant_reason"] == "low_sharpe"

    def test_cooldown_families(self):
        records = [_rec("bad_fam", rejection_id=f"r{i}") for i in range(6)]
        fb = build_atlas_feedback(records)
        assert "bad_fam" in fb["cooldown_families"]

    def test_near_miss_families(self):
        records = [_rec("good_fam", hint="promising_near_miss", rejection_id="r1")]
        fb = build_atlas_feedback(records)
        assert "good_fam" in fb["near_miss_families"]


class TestFishFeedback:
    def test_basic(self):
        records = [
            _rec(regime_tags=["trending"], rejection_id="r1"),
            _rec(regime_tags=["volatile"], rejection_id="r2"),
        ]
        fb = build_fish_feedback(records)
        assert fb["target"] == "fish"
        assert "trending" in fb["regimes"]
        assert "volatile" in fb["regimes"]

    def test_untagged_regime(self):
        records = [_rec(regime_tags=[], rejection_id="r1")]
        fb = build_fish_feedback(records)
        assert "untagged" in fb["regimes"]


class TestKittFeedback:
    def test_basic(self):
        records = [_rec(rejection_id="r1"), _rec(rejection_id="r2")]
        fb = build_kitt_feedback(records)
        assert fb["target"] == "kitt"
        assert fb["total_rejections"] == 2
        assert len(fb["top_rejection_reasons"]) > 0

    def test_exploration_shifts(self):
        records = [_rec(reason="low_trade_count", rejection_id=f"r{i}") for i in range(3)]
        fb = build_kitt_feedback(records)
        assert len(fb["exploration_shifts"]) > 0


class TestFeedbackSnapshot:
    def test_structure(self):
        records = [_rec(rejection_id="r1")]
        snap = build_feedback_snapshot(records)
        assert "atlas" in snap
        assert "fish" in snap
        assert "kitt" in snap
        assert snap["atlas"]["target"] == "atlas"

    def test_render_markdown(self):
        records = [
            _rec("ema", "low_sharpe", rejection_id="r1"),
            _rec("bo", "high_drawdown", regime_tags=["trending"], rejection_id="r2"),
        ]
        snap = build_feedback_snapshot(records)
        md = render_feedback_markdown(snap)
        assert "# Rejection Feedback Snapshot" in md
        assert "## Atlas" in md
        assert "## Fish" in md
        assert "## Kitt" in md
        assert "ema" in md


class TestExportFeedback:
    def test_writes_files(self, tmp_path):
        ledger = RejectionLedger(tmp_path)
        for i in range(3):
            ledger.write(_rec(rejection_id=f"rej_{i:03d}"))

        paths = export_feedback(ledger=ledger)
        assert paths["json"].exists()
        assert paths["md"].exists()

        data = json.loads(paths["json"].read_text())
        assert "atlas" in data
        assert "fish" in data
        assert "kitt" in data

        md = paths["md"].read_text()
        assert "Rejection Feedback Snapshot" in md
