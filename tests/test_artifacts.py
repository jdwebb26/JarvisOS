import json
import os
import tempfile

from strategy_factory.artifacts import (
    write_summary,
    write_json,
    append_to_strategy_registry,
    STRATEGIES_REGISTRY,
)


def test_write_summary_produces_valid_json(tmp_path):
    """write_summary should produce a valid summary.json."""
    summary_obj = {
        "command": "run",
        "candidate_id": "test_cand",
        "family": "breakout",
        "params": {"lookback": 20, "atr_stop_mult": 1.5},
        "status": "PASS",
        "score": 1.234,
        "data_source": "synthetic",
        "refit": True,
    }
    write_summary(tmp_path, summary_obj)

    # summary.json should exist and parse cleanly
    summary_json = tmp_path / "summary.json"
    assert summary_json.exists()
    parsed = json.loads(summary_json.read_text())
    assert parsed["command"] == "run"
    assert parsed["score"] == 1.234
    assert parsed["data_source"] == "synthetic"

    # manifest.json should also exist and match
    manifest = tmp_path / "manifest.json"
    assert manifest.exists()
    manifest_parsed = json.loads(manifest.read_text())
    assert manifest_parsed == parsed

    # summary.md should exist
    md = tmp_path / "summary.md"
    assert md.exists()
    assert "Strategy Factory Summary" in md.read_text()


def test_write_summary_handles_none_values(tmp_path):
    """summary.json should handle None values without error."""
    summary_obj = {
        "status": "REJECT",
        "reject_reason": None,
        "score": None,
        "gate_overall": None,
    }
    write_summary(tmp_path, summary_obj)
    parsed = json.loads((tmp_path / "summary.json").read_text())
    assert parsed["reject_reason"] is None


def test_append_to_strategy_registry(tmp_path):
    """Test appending entries to STRATEGIES.jsonl."""
    import strategy_factory.artifacts as art_mod
    orig = art_mod.STRATEGIES_REGISTRY
    reg_path = tmp_path / "STRATEGIES.jsonl"
    art_mod.STRATEGIES_REGISTRY = reg_path

    try:
        entry = append_to_strategy_registry(
            candidate_id="test_cand_001",
            logic_family_id="breakout",
            params={"lookback": 20},
            stage="BACKTESTED",
            score=1.5,
            gate_overall="PASS",
            artifact_dir=tmp_path,
            data_source="synthetic",
            fold_count=8,
            perturbation_robust=True,
            stress_overall="PASS",
        )

        assert entry["candidate_id"] == "test_cand_001"
        assert entry["stage"] == "BACKTESTED"

        # File should exist and contain valid JSONL
        assert reg_path.exists()
        lines = reg_path.read_text().strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["candidate_id"] == "test_cand_001"
        assert parsed["stage"] == "BACKTESTED"

        # Append another
        append_to_strategy_registry(
            candidate_id="test_cand_002",
            logic_family_id="ema_crossover",
            params={"atr_stop_mult": 2.0},
            stage="CANDIDATE",
            score=0.8,
            gate_overall="FAIL",
            artifact_dir=tmp_path,
            data_source="real",
            fold_count=5,
        )
        lines = reg_path.read_text().strip().split("\n")
        assert len(lines) == 2
    finally:
        art_mod.STRATEGIES_REGISTRY = orig


def test_registry_with_per_fold_params(tmp_path):
    """Registry entry should include per_fold_params when provided."""
    import strategy_factory.artifacts as art_mod
    orig = art_mod.STRATEGIES_REGISTRY
    reg_path = tmp_path / "STRATEGIES.jsonl"
    art_mod.STRATEGIES_REGISTRY = reg_path

    try:
        per_fold = [{"lookback": 18}, {"lookback": 22}, {"lookback": 20}]
        entry = append_to_strategy_registry(
            candidate_id="test_wf_001",
            logic_family_id="breakout",
            params={"lookback": 20},
            stage="BACKTESTED",
            score=1.3,
            gate_overall="PASS",
            artifact_dir=tmp_path,
            data_source="synthetic",
            fold_count=3,
            per_fold_params=per_fold,
        )
        assert "per_fold_params" in entry
        assert len(entry["per_fold_params"]) == 3

        parsed = json.loads(reg_path.read_text().strip())
        assert "per_fold_params" in parsed
    finally:
        art_mod.STRATEGIES_REGISTRY = orig
