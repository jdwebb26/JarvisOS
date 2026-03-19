"""Tests for the Strategy Factory operator_packet adapter."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.integrations.factory_packet_adapter import (
    FactoryPacketError,
    _discover_newest_packet,
    build_downstream_payload,
    consume_factory_packet,
    emit_factory_weekly,
    load_operator_packet,
    render_discord_message,
    render_kitt_handoff,
    render_worklog_entry,
    write_downstream_artifact,
)


SAMPLE_PACKET = {
    "cycle_id": "weekly_fb83344a",
    "generated_at": "2026-03-19T03:41:24.078130+00:00",
    "priority_family": "ema_crossover",
    "monitor_family": "breakout",
    "drop_family": None,
    "review_worthy_now": True,
    "strongest_dataset": "NQ_daily",
    "weakest_dataset": "NQ_hourly",
    "notable_change": "degraded: 497bcffb1bdb08fd dropped 36.7%",
    "degraded_count": 4,
    "honest_failures": [],
    "top_ideas": [
        {
            "signature": "04ea295aab08d8ea",
            "family": "breakout",
            "best_score": 1.1327,
            "appearances": 24,
            "distinct_runs": 21,
            "classification": "evidence_capped",
        },
        {
            "signature": "e0b90b1d4bb32fac",
            "family": "ema_crossover",
            "best_score": 0.7166,
            "appearances": 15,
            "distinct_runs": 15,
            "classification": "evidence_capped",
        },
        {
            "signature": "c1fa1ef696116d94",
            "family": "breakout",
            "best_score": 1.1561,
            "appearances": 13,
            "distinct_runs": 10,
            "classification": "evidence_capped",
        },
    ],
    "action_recommendation": "Review ema_crossover candidates this week.",
    "operator_status": "review",
    "supporting_artifacts": {
        "forward_validation": "forward_validation.json",
        "weekly_report": "weekly_report.md",
    },
}


def _write_packet(root: Path, date: str, packet: dict | None = None) -> Path:
    d = root / date
    d.mkdir(parents=True, exist_ok=True)
    p = d / "operator_packet.json"
    p.write_text(json.dumps(packet or SAMPLE_PACKET))
    return p


# ── discovery ────────────────────────────────────────────────────────


def test_discover_newest_packet(tmp_path: Path):
    _write_packet(tmp_path, "2026-03-17")
    _write_packet(tmp_path, "2026-03-19")
    _write_packet(tmp_path, "2026-03-18")
    result = _discover_newest_packet(tmp_path)
    assert result.parent.name == "2026-03-19"


def test_discover_skips_missing_packet(tmp_path: Path):
    # newest dir has no packet; should fall back to older one
    _write_packet(tmp_path, "2026-03-17")
    (tmp_path / "2026-03-19").mkdir()
    result = _discover_newest_packet(tmp_path)
    assert result.parent.name == "2026-03-17"


def test_discover_no_packets_raises(tmp_path: Path):
    (tmp_path / "2026-03-17").mkdir()
    try:
        _discover_newest_packet(tmp_path)
        assert False, "expected FactoryPacketError"
    except FactoryPacketError:
        pass


def test_discover_missing_root_raises(tmp_path: Path):
    try:
        _discover_newest_packet(tmp_path / "nonexistent")
        assert False, "expected FactoryPacketError"
    except FactoryPacketError:
        pass


# ── load ─────────────────────────────────────────────────────────────


def test_load_explicit_path(tmp_path: Path):
    p = _write_packet(tmp_path, "2026-03-19")
    result = load_operator_packet(path=p)
    assert result["cycle_id"] == "weekly_fb83344a"
    assert "_source_path" in result


def test_load_auto_discover(tmp_path: Path):
    _write_packet(tmp_path, "2026-03-19")
    result = load_operator_packet(root=tmp_path)
    assert result["cycle_id"] == "weekly_fb83344a"


def test_load_invalid_json(tmp_path: Path):
    d = tmp_path / "2026-03-19"
    d.mkdir()
    (d / "operator_packet.json").write_text("not json")
    try:
        load_operator_packet(root=tmp_path)
        assert False, "expected FactoryPacketError"
    except FactoryPacketError as exc:
        assert "failed to read" in str(exc)


def test_load_missing_cycle_id(tmp_path: Path):
    _write_packet(tmp_path, "2026-03-19", {"foo": "bar"})
    try:
        load_operator_packet(root=tmp_path)
        assert False, "expected FactoryPacketError"
    except FactoryPacketError as exc:
        assert "missing cycle_id" in str(exc)


# ── downstream payload ───────────────────────────────────────────────


def test_build_downstream_payload():
    packet = dict(SAMPLE_PACKET)
    packet["_source_path"] = "/artifacts/strategy_factory/2026-03-19/operator_packet.json"
    payload = build_downstream_payload(packet)

    assert payload["cycle_id"] == "weekly_fb83344a"
    assert payload["operator_status"] == "review"
    assert payload["priority_family"] == "ema_crossover"
    assert payload["monitor_family"] == "breakout"
    assert payload["drop_family"] is None
    assert payload["strongest_dataset"] == "NQ_daily"
    assert payload["weakest_dataset"] == "NQ_hourly"
    assert payload["degraded_count"] == 4
    assert payload["honest_failures"] == []
    assert payload["action_recommendation"] == "Review ema_crossover candidates this week."
    assert payload["source_date"] == "2026-03-19"
    assert len(payload["top_ideas"]) == 3
    # extra fields stripped from ideas
    assert "appearances" not in payload["top_ideas"][0]
    assert "distinct_runs" not in payload["top_ideas"][0]


def test_payload_truncates_ideas_to_3():
    packet = dict(SAMPLE_PACKET)
    packet["top_ideas"] = SAMPLE_PACKET["top_ideas"] * 3  # 9 ideas
    packet["_source_path"] = "/artifacts/strategy_factory/2026-03-19/op.json"
    payload = build_downstream_payload(packet)
    assert len(payload["top_ideas"]) == 3


def test_payload_handles_empty_ideas():
    packet = dict(SAMPLE_PACKET)
    packet["top_ideas"] = []
    packet["_source_path"] = "/x/2026-03-19/op.json"
    payload = build_downstream_payload(packet)
    assert payload["top_ideas"] == []


# ── rendering ────────────────────────────────────────────────────────


def _sample_payload() -> dict:
    packet = dict(SAMPLE_PACKET)
    packet["_source_path"] = "/artifacts/strategy_factory/2026-03-19/operator_packet.json"
    return build_downstream_payload(packet)


def test_render_discord_message():
    msg = render_discord_message(_sample_payload())
    assert "Strategy Factory Weekly" in msg
    assert "weekly_fb83344a" in msg
    assert "REVIEW" in msg
    assert "ema_crossover" in msg
    assert "breakout" in msg
    assert "NQ_daily" in msg
    assert "04ea295a" in msg
    assert "Review ema_crossover candidates" in msg
    assert "2026-03-19" in msg


def test_render_worklog_entry():
    entry = render_worklog_entry(_sample_payload())
    assert entry.startswith("[2026-03-19]")
    assert "weekly_fb83344a" in entry
    assert "status=review" in entry
    assert "priority=ema_crossover" in entry
    assert "degraded=4" in entry


# ── full pipeline ────────────────────────────────────────────────────


def test_consume_factory_packet(tmp_path: Path):
    _write_packet(tmp_path, "2026-03-19")
    result = consume_factory_packet(root=tmp_path)
    assert "payload" in result
    assert "discord_message" in result
    assert "worklog_entry" in result
    assert result["payload"]["cycle_id"] == "weekly_fb83344a"
    assert isinstance(result["discord_message"], str)
    assert isinstance(result["worklog_entry"], str)


def test_consume_no_packet_raises(tmp_path: Path):
    try:
        consume_factory_packet(root=tmp_path / "empty")
        assert False, "expected FactoryPacketError"
    except FactoryPacketError:
        pass


# ── kitt handoff ────────────────────────────────────────────────────


def test_render_kitt_handoff():
    payload = _sample_payload()
    handoff = render_kitt_handoff(payload)
    assert handoff["source"] == "strategy_factory"
    assert handoff["cycle_id"] == "weekly_fb83344a"
    assert handoff["operator_status"] == "review"
    assert handoff["priority_family"] == "ema_crossover"
    assert handoff["source_date"] == "2026-03-19"
    assert "ema_crossover" in handoff["context_summary"]
    assert "NQ_daily" in handoff["context_summary"]
    assert len(handoff["top_idea_lines"]) == 3
    assert "04ea295a" in handoff["top_idea_lines"][0]
    assert "breakout" in handoff["top_idea_lines"][0]


def test_kitt_handoff_empty_ideas():
    packet = dict(SAMPLE_PACKET)
    packet["top_ideas"] = []
    packet["_source_path"] = "/x/2026-03-19/op.json"
    payload = build_downstream_payload(packet)
    handoff = render_kitt_handoff(payload)
    assert handoff["top_idea_lines"] == []


# ── artifact writer ─────────────────────────────────────────────────


def test_write_downstream_artifact(tmp_path: Path):
    _write_packet(tmp_path, "2026-03-19")
    result = consume_factory_packet(root=tmp_path)
    out = write_downstream_artifact(result, root=tmp_path)
    assert out.name == "factory_downstream.json"
    assert out.parent.name == "2026-03-19"
    assert out.is_file()
    written = json.loads(out.read_text())
    assert written["cycle_id"] == "weekly_fb83344a"
    assert written["source_date"] == "2026-03-19"


def test_write_artifact_no_date_raises():
    result = {"payload": {"cycle_id": "x"}}
    try:
        write_downstream_artifact(result)
        assert False, "expected FactoryPacketError"
    except FactoryPacketError as exc:
        assert "no source_date" in str(exc)


# ── consume includes kitt_handoff ───────────────────────────────────


def test_consume_includes_kitt_handoff(tmp_path: Path):
    _write_packet(tmp_path, "2026-03-19")
    result = consume_factory_packet(root=tmp_path)
    assert "kitt_handoff" in result
    assert result["kitt_handoff"]["source"] == "strategy_factory"
    assert result["kitt_handoff"]["cycle_id"] == "weekly_fb83344a"


# ── emit_factory_weekly (runtime wiring) ───────────────────────────


def _setup_runtime(tmp_path: Path) -> tuple[Path, Path]:
    """Create minimal artifact + runtime dirs for emit_factory_weekly tests."""
    art_root = tmp_path / "artifacts"
    _write_packet(art_root, "2026-03-19")

    rt_root = tmp_path / "runtime"
    # emit_event needs config/agent_channel_map.json
    cfg = rt_root / "config"
    cfg.mkdir(parents=True)
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
    return art_root, rt_root


def test_emit_factory_weekly_full_pipeline(tmp_path: Path):
    art_root, rt_root = _setup_runtime(tmp_path)
    result = emit_factory_weekly(artifact_root=art_root, runtime_root=rt_root)

    # payload present
    assert result["payload"]["cycle_id"] == "weekly_fb83344a"

    # event emitted
    ev = result["event_result"]
    assert ev["kind"] == "factory_weekly_summary"
    assert ev["event_id"].startswith("devt_")
    assert ev["owner_channel_id"] == "111111"  # sigma
    assert ev["worklog_mirrored"] is True
    assert ev["jarvis_forwarded"] is True

    # outbox entries written (owner + worklog + jarvis)
    outbox_dir = rt_root / "state" / "discord_outbox"
    outbox_files = list(outbox_dir.glob("outbox_*.json"))
    assert len(outbox_files) == 3
    labels = set()
    for f in outbox_files:
        entry = json.loads(f.read_text())
        assert entry["event_kind"] == "factory_weekly_summary"
        assert entry["status"] == "pending"
        labels.add(entry["label"])
    assert labels == {"owner", "worklog", "jarvis_fwd"}

    # dispatch event record written
    dispatch_dir = rt_root / "state" / "dispatch_events"
    devt_files = list(dispatch_dir.glob("devt_*.json"))
    assert len(devt_files) == 1
    devt = json.loads(devt_files[0].read_text())
    assert devt["kind"] == "factory_weekly_summary"
    assert "Strategy Factory Weekly" in devt["text"]

    # kitt brief written
    brief_path = Path(result["kitt_brief_path"])
    assert brief_path.is_file()
    brief = json.loads(brief_path.read_text())
    assert brief["source"] == "strategy_factory"
    assert brief["cycle_id"] == "weekly_fb83344a"
    assert brief["actor"] == "factory_adapter"
    assert brief["lane"] == "quant"
    assert len(brief.get("top_idea_lines", [])) == 3

    # downstream artifact written
    art_path = Path(result["artifact_path"])
    assert art_path.is_file()
    assert art_path.name == "factory_downstream.json"


def test_emit_factory_weekly_discord_message_passthrough(tmp_path: Path):
    """The rich factory message must arrive in outbox un-truncated."""
    art_root, rt_root = _setup_runtime(tmp_path)
    result = emit_factory_weekly(artifact_root=art_root, runtime_root=rt_root)

    outbox_dir = rt_root / "state" / "discord_outbox"
    owner_entries = [
        json.loads(f.read_text())
        for f in outbox_dir.glob("outbox_*.json")
        if json.loads(f.read_text())["label"] == "owner"
    ]
    assert len(owner_entries) == 1
    text = owner_entries[0]["text"]
    # Full multi-line message preserved (not truncated to 200 chars)
    assert "**Strategy Factory Weekly**" in text
    assert "**Top ideas:**" in text
    assert "04ea295a" in text
    assert "Review ema_crossover candidates" in text


def test_emit_factory_weekly_no_packet_raises(tmp_path: Path):
    _, rt_root = _setup_runtime(tmp_path)
    empty_root = tmp_path / "empty_artifacts"
    empty_root.mkdir()
    try:
        emit_factory_weekly(artifact_root=empty_root, runtime_root=rt_root)
        assert False, "expected FactoryPacketError"
    except FactoryPacketError:
        pass


def test_emit_factory_weekly_discovers_newest(tmp_path: Path):
    art_root, rt_root = _setup_runtime(tmp_path)
    # Add an older packet with different cycle_id
    older = dict(SAMPLE_PACKET)
    older["cycle_id"] = "weekly_old"
    _write_packet(art_root, "2026-03-10", older)

    result = emit_factory_weekly(artifact_root=art_root, runtime_root=rt_root)
    # Should pick up the 2026-03-19 packet, not the older one
    assert result["payload"]["cycle_id"] == "weekly_fb83344a"
