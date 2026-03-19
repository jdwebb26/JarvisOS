#!/usr/bin/env python3
"""Tests for quant_lanes.py doctor and acceptance commands."""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from io import StringIO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest


# ---------------------------------------------------------------------------
# Proof-artifact filter
# ---------------------------------------------------------------------------

from scripts.quant_lanes import _is_proof_artifact


def test_proof_artifact_detected():
    assert _is_proof_artifact("atlas-live-proof-002")
    assert _is_proof_artifact("atlas-smoke-001")
    assert _is_proof_artifact("phase0-test")
    assert _is_proof_artifact("test-abc")


def test_real_strategy_not_filtered():
    assert not _is_proof_artifact("atlas-cycle-8135d368")
    assert not _is_proof_artifact("nq-mean-rev-001")
    assert not _is_proof_artifact("sigma-trend-follow")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_quant_root(tmp_path):
    """Minimal quant directory tree for doctor/acceptance."""
    for d in [
        "workspace/quant/shared/latest",
        "workspace/quant/shared/config",
        "workspace/quant/shared/registries",
        "workspace/quant/shared/scheduler",
        "state/discord_outbox",
        "state/dispatch_events",
        "config",
    ]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    # Governor state
    (tmp_path / "workspace/quant/shared/config/governor_state.json").write_text(
        json.dumps({"atlas": {"paused": False, "batch_size": 1}})
    )
    # Kill switch
    (tmp_path / "workspace/quant/shared/config/kill_switch.json").write_text(
        json.dumps({"engaged": False})
    )
    # Empty registries
    (tmp_path / "workspace/quant/shared/registries/strategies.jsonl").write_text("")
    (tmp_path / "workspace/quant/shared/registries/approvals.jsonl").write_text("")
    # Scheduler
    (tmp_path / "workspace/quant/shared/scheduler/active_jobs.json").write_text("[]")
    # Channel map (for brief/emit)
    (tmp_path / "config/agent_channel_map.json").write_text(json.dumps({
        "agents": {"kitt": {"channel_id": "k", "voice_only": False}},
        "logical_channels": {"worklog": {"channel_id": "w"}, "jarvis": {"channel_id": "j"}},
        "voice_only_event_kinds": [],
        "worklog_mirror_event_kinds": [],
        "jarvis_forward_event_kinds": [],
    }))
    return tmp_path


# ---------------------------------------------------------------------------
# doctor tests
# ---------------------------------------------------------------------------

def test_doctor_runs_without_crash(tmp_path):
    """Doctor should produce output and not crash even with mocked systemctl."""
    root = _make_quant_root(tmp_path)

    from scripts.quant_lanes import cmd_doctor

    mock_args = MagicMock()

    # Mock systemctl calls and delivery health
    def fake_run(*a, **kw):
        m = MagicMock()
        m.stdout = "active\n"
        return m

    with patch("scripts.quant_lanes.ROOT", root), \
         patch("subprocess.run", fake_run), \
         patch("workspace.quant.shared.discord_bridge.check_delivery_health",
               return_value={"sigma": "ok", "kitt": "ok", "atlas": "ok",
                             "fish": "ok", "review": "ok", "worklog": "ok"}):
        captured = StringIO()
        sys.stdout = captured
        try:
            cmd_doctor(mock_args)
        finally:
            sys.stdout = sys.__stdout__

    output = captured.getvalue()
    assert "OVERALL" in output
    assert "PASS" in output


def test_doctor_reports_fail_on_missing_webhook(tmp_path):
    """Doctor should FAIL when a webhook is missing."""
    root = _make_quant_root(tmp_path)

    from scripts.quant_lanes import cmd_doctor

    def fake_run(*a, **kw):
        m = MagicMock()
        m.stdout = "active\n"
        return m

    with patch("scripts.quant_lanes.ROOT", root), \
         patch("subprocess.run", fake_run), \
         patch("workspace.quant.shared.discord_bridge.check_delivery_health",
               return_value={"sigma": "ok", "kitt": "ok", "atlas": "missing_webhook",
                             "fish": "ok", "review": "ok", "worklog": "ok"}):
        captured = StringIO()
        sys.stdout = captured
        try:
            cmd_doctor(MagicMock())
        finally:
            sys.stdout = sys.__stdout__

    output = captured.getvalue()
    assert "FAIL" in output
    assert "delivery" in output


# ---------------------------------------------------------------------------
# acceptance tests
# ---------------------------------------------------------------------------

def test_acceptance_runs_without_crash(tmp_path):
    """Acceptance should produce output and not crash."""
    root = _make_quant_root(tmp_path)

    from scripts.quant_lanes import cmd_acceptance

    with patch("scripts.quant_lanes.ROOT", root), \
         patch("workspace.quant.shared.discord_bridge.check_delivery_health",
               return_value={"sigma": "ok", "kitt": "ok", "atlas": "ok",
                             "fish": "ok", "review": "ok", "worklog": "ok"}):
        captured = StringIO()
        sys.stdout = captured
        try:
            cmd_acceptance(MagicMock())
        finally:
            sys.stdout = sys.__stdout__

    output = captured.getvalue()
    assert "ACCEPTANCE" in output
    assert "pass" in output


def test_acceptance_brief_generation(tmp_path):
    """Acceptance should verify brief generation works."""
    root = _make_quant_root(tmp_path)

    from scripts.quant_lanes import cmd_acceptance

    with patch("scripts.quant_lanes.ROOT", root), \
         patch("workspace.quant.shared.discord_bridge.check_delivery_health",
               return_value={"sigma": "ok", "kitt": "ok", "atlas": "ok",
                             "fish": "ok", "review": "ok", "worklog": "ok"}):
        captured = StringIO()
        sys.stdout = captured
        try:
            cmd_acceptance(MagicMock())
        finally:
            sys.stdout = sys.__stdout__

    output = captured.getvalue()
    assert "brief generation" in output
    assert "PASS" in output


# ---------------------------------------------------------------------------
# brief proof filtering
# ---------------------------------------------------------------------------

def test_brief_filters_proof_strategies(tmp_path):
    """Brief should not show proof strategies in pipeline."""
    root = _make_quant_root(tmp_path)

    # Add a proof strategy to registry
    from workspace.quant.shared.registries.strategy_registry import create_strategy
    create_strategy(root, "atlas-live-proof-099", initial_state="IDEA", actor="atlas")

    from workspace.quant.kitt.brief_producer import produce_brief
    brief = produce_brief(root, market_read="test")
    assert "atlas-live-proof-099" not in (brief.notes or "")
