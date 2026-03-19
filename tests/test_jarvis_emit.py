"""Tests for the jarvis_emit bridge module."""
import json
import sys
from pathlib import Path

# Ensure jarvis-v5 is on path for the runtime imports
_JARVIS_ROOT = Path.home() / ".openclaw" / "workspace" / "jarvis-v5"
if str(_JARVIS_ROOT) not in sys.path:
    sys.path.insert(0, str(_JARVIS_ROOT))

from strategy_factory.jarvis_emit import emit_factory_summary


SAMPLE_PACKET = {
    "cycle_id": "weekly_test1234",
    "generated_at": "2026-03-19T03:41:24.078130+00:00",
    "priority_family": "ema_crossover",
    "monitor_family": "breakout",
    "drop_family": None,
    "review_worthy_now": True,
    "strongest_dataset": "NQ_daily",
    "weakest_dataset": "NQ_hourly",
    "notable_change": "test change",
    "degraded_count": 1,
    "honest_failures": [],
    "top_ideas": [
        {
            "signature": "aaaa1111bbbb2222",
            "family": "breakout",
            "best_score": 1.05,
            "appearances": 10,
            "distinct_runs": 8,
            "classification": "evidence_capped",
        },
    ],
    "action_recommendation": "Test recommendation.",
    "operator_status": "review",
    "supporting_artifacts": {},
}


def _write_packet(root: Path, date: str) -> Path:
    d = root / date
    d.mkdir(parents=True, exist_ok=True)
    p = d / "operator_packet.json"
    p.write_text(json.dumps(SAMPLE_PACKET))
    return p


def _make_channel_map(rt_root: Path) -> None:
    cfg = rt_root / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "agent_channel_map.json").write_text(json.dumps({
        "version": "1.1",
        "agents": {
            "sigma": {"channel_id": "111111", "purpose": "quant_validation", "voice_only": False},
        },
        "logical_channels": {
            "worklog": {"channel_id": "222222"},
            "jarvis": {"channel_id": "333333"},
        },
        "voice_only_event_kinds": [],
        "worklog_mirror_event_kinds": ["factory_weekly_summary"],
        "jarvis_forward_event_kinds": ["factory_weekly_summary"],
    }))


def test_emit_factory_summary_from_bridge(tmp_path: Path, monkeypatch):
    """The bridge module should produce events, outbox, brief, and artifact."""
    art_root = tmp_path / "artifacts"
    packet_path = _write_packet(art_root, "2026-03-19")

    rt_root = tmp_path / "runtime"
    _make_channel_map(rt_root)

    # Patch the jarvis root and adapter defaults so we write to tmp_path
    import strategy_factory.jarvis_emit as bridge_mod
    monkeypatch.setattr(bridge_mod, "_JARVIS_ROOT", rt_root)

    from runtime.integrations import factory_packet_adapter as adapter_mod
    monkeypatch.setattr(adapter_mod, "FACTORY_ARTIFACT_ROOT", art_root)

    result = emit_factory_summary(packet_path)

    # Event emitted
    ev = result["event_result"]
    assert ev["kind"] == "factory_weekly_summary"
    assert ev["event_id"].startswith("devt_")
    assert len(ev.get("outbox_entries", [])) == 3

    # Kitt brief written
    brief_path = Path(result["kitt_brief_path"])
    assert brief_path.is_file()
    brief = json.loads(brief_path.read_text())
    assert brief["cycle_id"] == "weekly_test1234"

    # Downstream artifact written
    art_path = Path(result["artifact_path"])
    assert art_path.is_file()
    assert art_path.name == "factory_downstream.json"

    # Discord message preserved in full
    assert "Strategy Factory Weekly" in result["discord_message"]
    assert "aaaa1111" in result["discord_message"]


def test_emit_factory_summary_missing_packet(tmp_path: Path, monkeypatch):
    """Bridge should raise FactoryPacketError for missing packet."""
    import strategy_factory.jarvis_emit as bridge_mod
    monkeypatch.setattr(bridge_mod, "_JARVIS_ROOT", tmp_path)

    from runtime.integrations.factory_packet_adapter import FactoryPacketError

    missing = tmp_path / "nonexistent" / "operator_packet.json"
    try:
        emit_factory_summary(missing)
        assert False, "expected FactoryPacketError"
    except FactoryPacketError:
        pass
