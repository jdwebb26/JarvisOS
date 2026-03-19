#!/usr/bin/env python3
"""Tests for Lane B cycle runner — repeatable invocation safety."""
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.run_lane_b_cycle import run_cycle
from workspace.quant.shared.restart import check_latest_coherence
from workspace.quant.shared.packet_store import get_all_latest
from workspace.quant.shared.registries.strategy_registry import load_all_strategies
from workspace.quant.shared.governor import load_governor_state


@pytest.fixture
def cycle_root(tmp_path):
    """Minimal quant directory for cycle testing."""
    for d in [
        "workspace/quant/shared/registries",
        "workspace/quant/shared/config",
        "workspace/quant/shared/latest",
        "workspace/quant/shared/scheduler",
        "workspace/quant/hermes",
        "workspace/quant/atlas",
        "workspace/quant/fish",
        "workspace/quant/sigma",
        "workspace/quant/kitt",
        "workspace/quant/executor",
        "workspace/quant/tradefloor",
        "state/quant/executor",
    ]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    # Write minimal configs
    (tmp_path / "workspace/quant/shared/config/kill_switch.json").write_text('{"engaged": false}')
    (tmp_path / "workspace/quant/shared/config/risk_limits.json").write_text(
        '{"per_strategy": {"max_position_size": 2}, "portfolio": {}}')
    (tmp_path / "workspace/quant/shared/config/hosts.json").write_text(json.dumps({
        "hosts": {"NIMO": {"heavy_job_cap": 2}, "SonLM": {"heavy_job_cap": 1}},
        "global_heavy_job_cap": 3,
        "lane_placement": {
            "atlas": {"primary": "NIMO", "overflow": "SonLM"},
            "fish": {"primary": "SonLM", "overflow": "cloud"},
            "hermes": {"primary": "mixed", "overflow": "either"},
            "tradefloor": {"primary": "strongest_available", "overflow": "cloud"},
        },
    }))
    (tmp_path / "workspace/quant/shared/config/governor_state.json").write_text(json.dumps({
        "atlas": {"batch_size": 1, "cadence_multiplier": 1.0, "paused": False, "consecutive_backoffs": 0},
        "fish": {"batch_size": 1, "cadence_multiplier": 1.0, "paused": False, "consecutive_backoffs": 0},
        "hermes": {"batch_size": 1, "cadence_multiplier": 1.0, "paused": False, "consecutive_backoffs": 0},
    }))
    return tmp_path


def test_single_cycle_runs_clean(cycle_root):
    """One cycle should produce packets without errors."""
    s = run_cycle(cycle_root)
    assert s["errors"] == [], f"Cycle errors: {s['errors']}"
    assert s["brief"] is True
    assert s["hermes"]["emitted"] >= 0
    assert s["atlas"]["generated"] >= 0


def test_double_cycle_no_corruption(cycle_root):
    """Two consecutive cycles should not corrupt state."""
    s1 = run_cycle(cycle_root)
    assert s1["errors"] == []

    s2 = run_cycle(cycle_root)
    assert s2["errors"] == []

    # Hermes dedup should kick in on second cycle (same source within 24h)
    # Atlas should get a different strategy_id (hash-based)
    coherent, issues = check_latest_coherence(cycle_root)
    assert coherent, f"Coherence issues after 2 cycles: {issues}"


def test_tradefloor_cadence_across_cycles(cycle_root):
    """TradeFloor should run on first cycle but not second (6h cadence)."""
    s1 = run_cycle(cycle_root)
    assert s1["errors"] == []
    tf1_ran = s1["tradefloor"]["ran"]

    s2 = run_cycle(cycle_root)
    assert s2["errors"] == []

    # If first ran, second should be cadence-refused
    if tf1_ran:
        assert s2["tradefloor"]["cadence_refused"] is True


def test_kitt_brief_reflects_lane_b(cycle_root):
    """After a cycle, Kitt brief should include Lane B lane activity."""
    run_cycle(cycle_root)
    latest = get_all_latest(cycle_root)
    brief_pkt = None
    for key, pkt in latest.items():
        if pkt.packet_type == "brief_packet":
            brief_pkt = pkt
    assert brief_pkt is not None, "No brief after cycle"
    notes = brief_pkt.notes or ""
    assert "FEEDBACK LOOPS" in notes or "LANES" in notes


def test_governor_state_persists(cycle_root):
    """Governor state should persist across cycles."""
    run_cycle(cycle_root)
    state1 = load_governor_state(cycle_root)
    assert "atlas" in state1

    run_cycle(cycle_root)
    state2 = load_governor_state(cycle_root)
    assert "atlas" in state2


def test_cycle_with_paused_lane(cycle_root):
    """Paused lanes should be skipped gracefully."""
    # Pause atlas
    gov_path = cycle_root / "workspace/quant/shared/config/governor_state.json"
    state = json.loads(gov_path.read_text())
    state["atlas"]["paused"] = True
    gov_path.write_text(json.dumps(state))

    s = run_cycle(cycle_root)
    assert s["errors"] == []
    assert s["atlas"]["skipped"] is True
