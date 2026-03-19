#!/usr/bin/env python3
"""Tests for Lane B timer/scheduler safety."""
import sys
import json
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.run_lane_b_cycle import run_cycle, acquire_cycle_lock, LOCK_PATH
from workspace.quant.shared.restart import check_latest_coherence
from workspace.quant.shared.packet_store import get_all_latest


@pytest.fixture
def timer_root(tmp_path):
    """Minimal quant directory for timer testing."""
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


def test_cycle_lock_prevents_overlap():
    """Two concurrent lock attempts: first succeeds, second gets None."""
    lock1 = acquire_cycle_lock()
    assert lock1 is not None, "First lock should succeed"
    try:
        lock2 = acquire_cycle_lock()
        assert lock2 is None, "Second lock should fail (overlap)"
    finally:
        lock1.close()


def test_cycle_lock_released_after_close():
    """Lock should be re-acquirable after release."""
    lock1 = acquire_cycle_lock()
    assert lock1 is not None
    lock1.close()

    lock2 = acquire_cycle_lock()
    assert lock2 is not None, "Lock should be available after close"
    lock2.close()


def test_three_rapid_cycles_coherent(timer_root):
    """Three rapid cycles should not corrupt state."""
    for i in range(3):
        s = run_cycle(timer_root)
        assert s["errors"] == [], f"Cycle {i+1} errors: {s['errors']}"
        assert s["brief"] is True

    coherent, issues = check_latest_coherence(timer_root)
    assert coherent, f"Coherence issues: {issues}"


def test_service_unit_contents():
    """Service unit file should have correct paths."""
    svc = ROOT / "ops" / "systemd" / "quant-lane-b-cycle.service"
    assert svc.exists()
    text = svc.read_text()
    assert "Type=oneshot" in text
    assert "quant_lanes.py" in text
    assert "lane-b-cycle" in text
    assert "EnvironmentFile" in text


def test_timer_unit_contents():
    """Timer unit file should have sensible cadence."""
    timer = ROOT / "ops" / "systemd" / "quant-lane-b-cycle.timer"
    assert timer.exists()
    text = timer.read_text()
    assert "OnUnitActiveSec=" in text
    assert "timers.target" in text
