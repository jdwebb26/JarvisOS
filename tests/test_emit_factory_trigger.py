"""Tests for the idempotent factory packet emit trigger (scripts/emit_factory_packet.py)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "scripts"))

from scripts.emit_factory_packet import _already_emitted


SAMPLE_PACKET = {
    "cycle_id": "weekly_test_trigger",
    "generated_at": "2026-03-19T00:00:00+00:00",
    "priority_family": "ema_crossover",
    "monitor_family": "breakout",
    "drop_family": None,
    "strongest_dataset": "NQ_daily",
    "weakest_dataset": "NQ_hourly",
    "notable_change": "test",
    "degraded_count": 0,
    "honest_failures": [],
    "top_ideas": [],
    "action_recommendation": "Test.",
    "operator_status": "hold",
    "supporting_artifacts": {},
}


def _write_packet(root: Path, date: str, cycle_id: str = "weekly_test_trigger") -> Path:
    d = root / date
    d.mkdir(parents=True, exist_ok=True)
    pkt = dict(SAMPLE_PACKET, cycle_id=cycle_id)
    p = d / "operator_packet.json"
    p.write_text(json.dumps(pkt))
    return p


def _make_channel_map(rt_root: Path) -> None:
    cfg = rt_root / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "agent_channel_map.json").write_text(json.dumps({
        "version": "1.1",
        "agents": {"sigma": {"channel_id": "111", "purpose": "test", "voice_only": False}},
        "logical_channels": {
            "worklog": {"channel_id": "222"},
            "jarvis": {"channel_id": "333"},
        },
        "voice_only_event_kinds": [],
        "worklog_mirror_event_kinds": ["factory_weekly_summary"],
        "jarvis_forward_event_kinds": ["factory_weekly_summary"],
    }))


def test_already_emitted_false_no_downstream(tmp_path: Path):
    pkt_path = _write_packet(tmp_path, "2026-03-19")
    assert _already_emitted(pkt_path) is False


def test_already_emitted_false_wrong_cycle(tmp_path: Path):
    pkt_path = _write_packet(tmp_path, "2026-03-19", cycle_id="weekly_aaa")
    ds = pkt_path.parent / "factory_downstream.json"
    ds.write_text(json.dumps({"cycle_id": "weekly_bbb"}))
    assert _already_emitted(pkt_path) is False


def test_already_emitted_true_matching_cycle(tmp_path: Path):
    pkt_path = _write_packet(tmp_path, "2026-03-19", cycle_id="weekly_match")
    ds = pkt_path.parent / "factory_downstream.json"
    ds.write_text(json.dumps({"cycle_id": "weekly_match"}))
    assert _already_emitted(pkt_path) is True


def test_already_emitted_corrupt_downstream(tmp_path: Path):
    pkt_path = _write_packet(tmp_path, "2026-03-19")
    ds = pkt_path.parent / "factory_downstream.json"
    ds.write_text("not json")
    assert _already_emitted(pkt_path) is False


def test_full_emit_then_idempotent(tmp_path: Path):
    """emit_factory_weekly should create downstream; second check sees it as emitted."""
    from runtime.integrations.factory_packet_adapter import emit_factory_weekly

    art_root = tmp_path / "artifacts"
    pkt_path = _write_packet(art_root, "2026-03-19")
    rt_root = tmp_path / "runtime"
    _make_channel_map(rt_root)

    result = emit_factory_weekly(path=pkt_path, artifact_root=art_root, runtime_root=rt_root)
    assert result["event_result"]["kind"] == "factory_weekly_summary"

    # Now _already_emitted should return True
    assert _already_emitted(pkt_path) is True
