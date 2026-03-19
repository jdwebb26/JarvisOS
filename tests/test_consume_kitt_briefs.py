"""Tests for the factory-origin Kitt brief consumer."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "scripts"))

from scripts.consume_kitt_briefs import (
    _is_factory_origin,
    _is_consumed,
    find_pending,
    consume_pending,
    status,
)


FACTORY_BRIEF = {
    "brief_id": "kitt_brief_test001",
    "task_id": "factory_weekly_abc",
    "created_at": "2026-03-19T00:00:00+00:00",
    "actor": "factory_adapter",
    "lane": "quant",
    "source": "strategy_factory",
    "cycle_id": "weekly_abc",
    "operator_status": "review",
    "source_date": "2026-03-19",
    "priority_family": "ema_crossover",
    "action_recommendation": "Review ema_crossover.",
    "context_summary": "Factory status=review.",
    "top_idea_lines": ["sig1 (breakout) score=1.1 [evidence_capped]"],
}

LLM_BRIEF = {
    "brief_id": "kitt_brief_llm001",
    "task_id": "kitt_task_xyz",
    "created_at": "2026-03-19T00:00:00+00:00",
    "actor": "kitt",
    "lane": "quant",
    "brief_text": "Some LLM-generated text.",
    "model_used": "moonshotai/kimi-k2.5",
}


def _setup(tmp_path: Path, briefs: list[dict] | None = None) -> Path:
    """Create a minimal runtime root with briefs and channel map."""
    rt = tmp_path / "runtime"
    bd = rt / "state" / "kitt_briefs"
    bd.mkdir(parents=True)
    cfg = rt / "config"
    cfg.mkdir(parents=True)
    (cfg / "agent_channel_map.json").write_text(json.dumps({
        "version": "1.1",
        "agents": {"kitt": {"channel_id": "444", "purpose": "quant_lead", "voice_only": False}},
        "logical_channels": {"worklog": {"channel_id": "555"}, "jarvis": {"channel_id": "666"}},
        "voice_only_event_kinds": [],
        "worklog_mirror_event_kinds": ["kitt_brief_completed"],
        "jarvis_forward_event_kinds": [],
    }))
    for b in (briefs or []):
        (bd / f"{b['brief_id']}.json").write_text(json.dumps(b))
    return rt


def test_is_factory_origin():
    assert _is_factory_origin(FACTORY_BRIEF) is True
    assert _is_factory_origin(LLM_BRIEF) is False
    assert _is_factory_origin({}) is False


def test_find_pending_only_factory(tmp_path: Path):
    rt = _setup(tmp_path, [FACTORY_BRIEF, LLM_BRIEF])
    pending = find_pending(rt)
    assert len(pending) == 1
    assert pending[0][1]["brief_id"] == "kitt_brief_test001"


def test_find_pending_empty_dir(tmp_path: Path):
    rt = _setup(tmp_path, [])
    assert find_pending(rt) == []


def test_consume_creates_outputs(tmp_path: Path):
    rt = _setup(tmp_path, [FACTORY_BRIEF])
    summary = consume_pending(rt)
    assert summary["pending"] == 1
    assert summary["processed"] == 1
    r = summary["results"][0]
    assert r["action"] == "consumed"
    assert r["event_id"].startswith("devt_")
    assert r["outbox_entries"] == 2  # kitt + worklog

    # Consumed marker exists
    marker = rt / "state" / "kitt_briefs_consumed" / "kitt_brief_test001.json"
    assert marker.is_file()
    m = json.loads(marker.read_text())
    assert m["cycle_id"] == "weekly_abc"

    # Dispatch event created
    devt_dir = rt / "state" / "dispatch_events"
    devt_files = list(devt_dir.glob("devt_*.json"))
    assert len(devt_files) == 1
    devt = json.loads(devt_files[0].read_text())
    assert devt["kind"] == "kitt_brief_completed"
    assert devt["agent_id"] == "kitt"

    # Outbox entries created
    outbox_dir = rt / "state" / "discord_outbox"
    outbox_files = list(outbox_dir.glob("outbox_*.json"))
    assert len(outbox_files) == 2
    labels = {json.loads(f.read_text())["label"] for f in outbox_files}
    assert labels == {"owner", "worklog"}


def test_idempotent_second_run(tmp_path: Path):
    rt = _setup(tmp_path, [FACTORY_BRIEF])
    consume_pending(rt)
    second = consume_pending(rt)
    assert second["pending"] == 0
    assert second["processed"] == 0


def test_dry_run_no_side_effects(tmp_path: Path):
    rt = _setup(tmp_path, [FACTORY_BRIEF])
    summary = consume_pending(rt, dry_run=True)
    assert summary["processed"] == 1
    assert summary["results"][0]["action"] == "dry_run"
    # No consumed marker
    assert not (rt / "state" / "kitt_briefs_consumed" / "kitt_brief_test001.json").exists()
    # No dispatch events
    devt_dir = rt / "state" / "dispatch_events"
    assert not devt_dir.exists() or len(list(devt_dir.glob("devt_*.json"))) == 0


def test_status_counts(tmp_path: Path):
    rt = _setup(tmp_path, [FACTORY_BRIEF, LLM_BRIEF])
    s = status(rt)
    assert s == {"total_factory": 1, "consumed": 0, "pending": 1}
    consume_pending(rt)
    s2 = status(rt)
    assert s2 == {"total_factory": 1, "consumed": 1, "pending": 0}


def test_multiple_briefs_consumed_independently(tmp_path: Path):
    b2 = dict(FACTORY_BRIEF, brief_id="kitt_brief_test002", cycle_id="weekly_def")
    rt = _setup(tmp_path, [FACTORY_BRIEF, b2])
    # Consume first run
    s1 = consume_pending(rt)
    assert s1["processed"] == 2
    # Both consumed
    s2 = consume_pending(rt)
    assert s2["pending"] == 0
