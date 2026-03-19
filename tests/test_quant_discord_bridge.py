#!/usr/bin/env python3
"""Tests for quant lanes Discord bridge and live runtime integration."""
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet
from workspace.quant.shared.discord_bridge import (
    emit_quant_event, _PACKET_TO_EVENT_KIND, check_delivery_health,
)
from runtime.core.discord_event_router import _render_status_text, _EMOJI


def test_all_mapped_packet_types_have_emoji():
    """Every quant event kind in the mapping should have an emoji defined."""
    for packet_type, event_kind in _PACKET_TO_EVENT_KIND.items():
        assert event_kind in _EMOJI, f"Event kind {event_kind} (from {packet_type}) missing from _EMOJI"


def test_emit_quant_event_promotion(tmp_path):
    """Promotion event should route to sigma channel."""
    # Set up minimal config
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    state_dirs = [tmp_path / "state" / d for d in ["dispatch_events", "discord_outbox"]]
    for d in state_dirs:
        d.mkdir(parents=True)
    # Write channel map
    (config_dir / "agent_channel_map.json").write_text(json.dumps({
        "agents": {
            "kitt": {"channel_id": "kitt_ch", "voice_only": False},
            "sigma": {"channel_id": "sigma_ch", "voice_only": False},
        },
        "logical_channels": {"worklog": {"channel_id": "wl_ch"}, "jarvis": {"channel_id": "j_ch"}},
        "voice_only_event_kinds": [],
        "worklog_mirror_event_kinds": ["quant_strategy_promoted"],
        "jarvis_forward_event_kinds": ["quant_strategy_promoted"],
    }))

    pkt = make_packet("promotion_packet", "sigma", "Test promotion", strategy_id="test-001")
    result = emit_quant_event(pkt, root=tmp_path)
    assert result["owner_channel_id"] == "sigma_ch"
    assert result["worklog_mirrored"] is True
    assert result["jarvis_forwarded"] is True


def test_emit_quant_event_execution(tmp_path):
    """Execution event should route to kitt channel (executor routes through kitt)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for d in [tmp_path / "state" / "dispatch_events", tmp_path / "state" / "discord_outbox"]:
        d.mkdir(parents=True)
    (config_dir / "agent_channel_map.json").write_text(json.dumps({
        "agents": {"kitt": {"channel_id": "kitt_ch", "voice_only": False}},
        "logical_channels": {"worklog": {"channel_id": "wl_ch"}, "jarvis": {"channel_id": "j_ch"}},
        "voice_only_event_kinds": [],
        "worklog_mirror_event_kinds": ["quant_execution_status"],
        "jarvis_forward_event_kinds": [],
    }))

    pkt = make_packet("execution_status_packet", "executor", "Filled",
                      strategy_id="test-001", execution_mode="paper",
                      approval_ref="approval-001")
    result = emit_quant_event(pkt, root=tmp_path)
    assert result["owner_channel_id"] == "kitt_ch"


def test_emit_skips_unmapped_packet_type(tmp_path):
    """Unmapped packet types should be skipped gracefully."""
    pkt = make_packet("research_packet", "hermes", "Research")
    # research_packet IS mapped, but let's test with a packet that has no mapping
    pkt.packet_type = "dataset_packet"
    result = emit_quant_event(pkt, root=tmp_path)
    assert result.get("skipped") is True


def test_render_quant_promotion():
    """Quant promotion event should render cleanly."""
    payload = {
        "agent_id": "sigma",
        "detail": "[test-001] Strategy promoted",
        "strategy_id": "test-001",
        "packet_type": "promotion_packet",
    }
    text = _render_status_text("quant_strategy_promoted", payload)
    assert "Sigma" in text
    assert "promoted" in text
    assert "test-001" in text


def test_render_quant_rejection():
    """Quant rejection event should render cleanly."""
    payload = {
        "agent_id": "sigma",
        "detail": "[test-001] Strategy rejected: PF too low",
        "strategy_id": "test-001",
        "packet_type": "strategy_rejection_packet",
    }
    text = _render_status_text("quant_strategy_rejected", payload)
    assert "Sigma" in text
    assert "rejected" in text


def test_render_quant_papertrade_request():
    """Papertrade request should include #review instruction."""
    payload = {
        "agent_id": "kitt",
        "detail": "[test-001] Requesting paper trade",
        "strategy_id": "test-001",
    }
    text = _render_status_text("quant_papertrade_request", payload)
    assert "Kitt" in text
    assert "#review" in text


def test_render_quant_execution_fill():
    """Execution fill should render cleanly."""
    payload = {
        "agent_id": "kitt",
        "detail": "[test-001] Filled at 18250",
        "strategy_id": "test-001",
    }
    text = _render_status_text("quant_execution_status", payload)
    assert "Executor" in text
    assert "fill" in text


# ---------------------------------------------------------------------------
# Atlas / Fish owner-channel routing
# ---------------------------------------------------------------------------

def _make_channel_map(tmp_path, extra_agents=None):
    """Helper: write a channel map with atlas/fish and return tmp_path."""
    agents = {
        "kitt": {"channel_id": "kitt_ch", "voice_only": False},
        "sigma": {"channel_id": "sigma_ch", "voice_only": False},
        "atlas": {"channel_id": "atlas_ch", "voice_only": False},
        "fish": {"channel_id": "fish_ch", "voice_only": False},
    }
    if extra_agents:
        agents.update(extra_agents)
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    for d in [tmp_path / "state" / "dispatch_events", tmp_path / "state" / "discord_outbox"]:
        d.mkdir(parents=True, exist_ok=True)
    (config_dir / "agent_channel_map.json").write_text(json.dumps({
        "agents": agents,
        "logical_channels": {"worklog": {"channel_id": "wl_ch"}, "jarvis": {"channel_id": "j_ch"}},
        "voice_only_event_kinds": [],
        "worklog_mirror_event_kinds": [],
        "jarvis_forward_event_kinds": [],
    }))
    return tmp_path


def test_atlas_candidate_routes_to_atlas_channel(tmp_path):
    """candidate_packet from atlas lane must create outbox for atlas owner channel."""
    root = _make_channel_map(tmp_path)
    pkt = make_packet("candidate_packet", "atlas", "NQ mean-reversion candidate",
                      strategy_id="atlas-test-001")
    result = emit_quant_event(pkt, root=root)
    assert result["owner_channel_id"] == "atlas_ch"
    # Verify outbox entry written
    outbox_files = list((root / "state" / "discord_outbox").glob("outbox_*.json"))
    assert len(outbox_files) >= 1
    entry = json.loads(outbox_files[0].read_text())
    assert entry["channel_id"] == "atlas_ch"


def test_fish_scenario_routes_to_fish_channel(tmp_path):
    """scenario_packet from fish lane must create outbox for fish owner channel."""
    root = _make_channel_map(tmp_path)
    pkt = make_packet("scenario_packet", "fish", "NQ consolidation breakout scenario")
    result = emit_quant_event(pkt, root=root)
    assert result["owner_channel_id"] == "fish_ch"
    outbox_files = list((root / "state" / "discord_outbox").glob("outbox_*.json"))
    assert len(outbox_files) >= 1
    entry = json.loads(outbox_files[0].read_text())
    assert entry["channel_id"] == "fish_ch"


def test_scenario_packet_has_event_mapping():
    """scenario_packet must be in _PACKET_TO_EVENT_KIND (was missing before fix)."""
    assert "scenario_packet" in _PACKET_TO_EVENT_KIND
    assert _PACKET_TO_EVENT_KIND["scenario_packet"] == "quant_scenario_submitted"


def test_scenario_event_has_emoji():
    """quant_scenario_submitted must have an emoji defined."""
    assert "quant_scenario_submitted" in _EMOJI


def test_delivery_health_includes_atlas_fish(tmp_path, monkeypatch):
    """check_delivery_health must report atlas and fish channels."""
    # Write a fake secrets.env
    secrets = tmp_path / "secrets.env"
    secrets.write_text(
        "JARVIS_DISCORD_WEBHOOK_KITT=https://ok\n"
        "JARVIS_DISCORD_WEBHOOK_SIGMA=https://ok\n"
        "JARVIS_DISCORD_WEBHOOK_ATLAS=https://ok\n"
        "JARVIS_DISCORD_WEBHOOK_FISH=https://ok\n"
        "REVIEW_WEBHOOK_URL=https://ok\n"
        "JARVIS_DISCORD_WEBHOOK_WORKLOG=https://ok\n"
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path.parent)
    # Trick: secrets.env lives at home/.openclaw/secrets.env
    ocdir = tmp_path.parent / ".openclaw"
    ocdir.mkdir(exist_ok=True)
    (ocdir / "secrets.env").write_text(secrets.read_text())
    health = check_delivery_health()
    assert "atlas" in health
    assert "fish" in health
    assert health["atlas"] == "ok"
    assert health["fish"] == "ok"
