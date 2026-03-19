#!/usr/bin/env python3
"""Tests for discord_event_router message formatting.

Verifies emoji-first, glanceable message shapes for all major event kinds.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.core.discord_event_router import _render_status_text, _clean_detail, _EMOJI


def _payload(**kw) -> dict:
    return {"agent_id": "hal", "task_id": "task_abc123def456", "detail": "", "target": "", "reviewer_id": "", "artifact_id": "", **kw}


# ---------------------------------------------------------------------------
# Message shape tests — emoji prefix, bold agent, no [LABEL] blocks
# ---------------------------------------------------------------------------

def test_task_completed_emoji_shape():
    text = _render_status_text("task_completed", _payload(detail="Built walk-forward module"))
    assert text.startswith("\u2705")  # ✅
    assert "**HAL**" in text
    assert "`abc123`" in text
    assert "walk-forward" in text
    assert "[RESULT]" not in text  # no old label


def test_task_failed_emoji_shape():
    text = _render_status_text("task_failed", _payload(detail="ModuleNotFoundError: pandas not installed"))
    assert text.startswith("\u274c")  # ❌
    assert "**HAL**" in text
    assert "failed" in text
    assert "\U0001f4cc" in text  # 📌 next step
    assert "[ALERT]" not in text


def test_task_blocked_has_pin():
    text = _render_status_text("task_blocked", _payload(detail="Waiting for operator approval"))
    assert "\U0001f6ab" in text  # 🚫
    assert "blocked" in text
    assert "\U0001f4cc" in text  # 📌


def test_review_requested_enriched():
    text = _render_status_text("review_requested", _payload(
        agent_id="ralph",
        detail="EMA crossover signal function — needs code review",
        reviewer_id="archimedes",
        title="Write EMA crossover signal function",
        source_lane="code",
        task_type="code",
        risk_level="normal",
        execution_backend="ralph_adapter",
        artifact_ids=["art_abc123def456"],
        review_id="rev_test123",
    ))
    assert "\U0001f440" in text  # 👀
    assert "**Review needed**" in text
    assert "EMA crossover" in text
    assert "Archimedes" in text
    assert "Ralph" in text
    assert "code" in text
    assert "art_abc123def456" in text
    assert "approve" in text.lower()


def test_review_requested_minimal():
    """Even with no enriched fields, review_requested renders usably."""
    text = _render_status_text("review_requested", _payload(
        agent_id="hal",
        detail="Review new validation module",
    ))
    assert "**Review needed**" in text
    assert "approve" in text.lower()


def test_review_completed_approved_enriched():
    text = _render_status_text("review_completed", _payload(
        reviewer_id="archimedes",
        detail="verdict: approved. Clean implementation, good test coverage.",
        title="Write EMA crossover signal function",
        source_lane="code",
        task_type="code",
        review_id="rev_test123",
    ))
    assert "\u2705" in text  # ✅
    assert "Archimedes" in text
    assert "APPROVED" in text
    assert "EMA crossover" in text
    assert "Clean implementation" in text
    assert "code" in text


def test_review_completed_rejected():
    text = _render_status_text("review_completed", _payload(
        reviewer_id="archimedes",
        detail="verdict: rejected. Missing edge case handling.",
    ))
    assert "\u274c" in text  # ❌
    assert "REJECTED" in text


def test_approval_requested_enriched():
    text = _render_status_text("approval_requested", _payload(
        agent_id="ralph",
        detail="Deploy EMA strategy to paper trading",
        reviewer_id="operator",
        title="Deploy EMA crossover to paper",
        source_lane="quant",
        task_type="deploy",
        risk_level="high",
        approval_id="apr_test123456",
        artifact_ids=["art_abc123def456"],
    ))
    assert "\U0001f510" in text  # 🔐
    assert "**Approval needed**" in text
    assert "EMA crossover" in text or "EMA" in text
    assert "apr_test123456" in text
    assert "quant" in text
    assert "high" in text.lower()
    assert "approve" in text.lower()
    assert "reject" in text.lower()


def test_approval_requested_minimal():
    """Even with no enriched fields, approval_requested renders usably."""
    text = _render_status_text("approval_requested", _payload(
        detail="Deploy strategy to paper trading",
    ))
    assert "**Approval needed**" in text
    assert "approve" in text.lower()


def test_approval_completed_enriched():
    text = _render_status_text("approval_completed", _payload(
        detail="decision: approved. Looks good.",
        reviewer_id="operator",
        title="Deploy EMA crossover to paper",
        source_lane="quant",
        task_type="deploy",
        approval_id="apr_test123456",
    ))
    assert "\u2705" in text  # ✅
    assert "APPROVED" in text
    assert "EMA crossover" in text or "EMA" in text
    assert "Operator" in text
    assert "quant" in text


def test_browser_result():
    text = _render_status_text("browser_result", _payload(
        agent_id="bowser",
        target="https://finance.yahoo.com/quote/NQ=F",
        detail="Navigated to page, extracted 2500 chars",
    ))
    assert "\U0001f310" in text  # 🌐
    assert "**Bowser**" in text
    assert "browsed" in text


def test_kitt_brief_completed():
    text = _render_status_text("kitt_brief_completed", _payload(
        agent_id="kitt",
        detail="kitt_brief_abc123: MARKET STATE NQ at 20100",
    ))
    assert "\U0001f9e0" in text  # 🧠
    assert "**Kitt**" in text
    assert "brief ready" in text


def test_warning_compact():
    text = _render_status_text("warning", _payload(agent_id="ralph", detail="model_backend: connection timed out"))
    assert "\u26a0\ufe0f" in text  # ⚠️
    assert "**Ralph**" in text
    assert "connection timed out" in text
    assert "[WARNING]" not in text


def test_error_has_pin():
    text = _render_status_text("error", _payload(agent_id="jarvis", detail="Gateway unreachable"))
    assert "\U0001f534" in text  # 🔴
    assert "\U0001f4cc" in text  # 📌
    assert "Investigate" in text


def test_delegation_sent():
    text = _render_status_text("delegation_sent", _payload(target="archimedes"))
    assert "\U0001f500" in text  # 🔀
    assert "delegated" in text
    assert "\u2192" in text  # →


def test_voice_compact():
    text = _render_status_text("voice_session_started", _payload(agent_id="cadence"))
    assert "\U0001f399" in text  # 🎙️
    assert "**Cadence**" in text
    assert "session started" in text


def test_agent_online():
    text = _render_status_text("agent_online", _payload(agent_id="scout"))
    assert "\U0001f7e2" in text  # 🟢
    assert "online" in text


def test_profile_changed():
    text = _render_status_text("profile_changed", _payload(
        agent_id="jarvis",
        detail="hybrid — Orchestration on Kimi 2.5, coders local",
    ))
    assert "\U0001f504" in text  # 🔄
    assert "Profile switched" in text
    assert "hybrid" in text


def test_models_status():
    text = _render_status_text("models_status", _payload(
        agent_id="jarvis",
        detail="✅ **Jarvis** — `lmstudio/qwen3.5-35b`",
    ))
    assert "\U0001f4ca" in text  # 📊
    assert "Model status" in text
    assert "Jarvis" in text


def test_fallback_unknown_kind():
    text = _render_status_text("some_unknown_kind", _payload(detail="test fallback"))
    assert "\u2139" in text  # ℹ️
    assert "some_unknown_kind" in text


# ---------------------------------------------------------------------------
# Noise stripping preserved
# ---------------------------------------------------------------------------

def test_noise_stripping_tab_hashes():
    text = _clean_detail("Navigated to example.com; tab ECBD52325D568DBD385B6764C81AC804; snapshot nodes=8")
    assert "ECBD52" not in text
    assert "snapshot nodes" not in text
    assert "example.com" in text


def test_noise_stripping_cycle_ids():
    text = _clean_detail("cycle rcycle_abc123def456 completed with 3 tasks")
    assert "rcycle_" not in text


# ---------------------------------------------------------------------------
# No old [LABEL] blocks in any event kind
# ---------------------------------------------------------------------------

def test_no_old_labels_in_any_kind():
    """No event kind should produce the old **[LABEL]** format."""
    for kind in _EMOJI:
        text = _render_status_text(kind, _payload(detail="test detail", target="https://example.com"))
        for label in ["[STATUS]", "[RESULT]", "[ALERT]", "[ACTION REQUIRED]", "[WARNING]", "[ERROR]", "[INFO]"]:
            assert label not in text, f"{kind} still produces old label {label}"


# ---------------------------------------------------------------------------
# Jarvis channel noise filtering — routine events must NOT forward to #jarvis
# ---------------------------------------------------------------------------

from runtime.core.discord_event_router import emit_event, _load_channel_map


def test_review_requests_route_to_review_channel(tmp_path):
    """review_requested and approval_requested must land in #review (archimedes channel)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    channel_map = _load_channel_map()
    (config_dir / "agent_channel_map.json").write_text(json.dumps(channel_map))
    (tmp_path / "state" / "dispatch_events").mkdir(parents=True)
    (tmp_path / "state" / "discord_outbox").mkdir(parents=True)

    review_ch = channel_map["agents"]["archimedes"]["channel_id"]

    for kind in ["review_requested", "approval_requested"]:
        result = emit_event(
            kind, "hal",
            task_id="task_test123456",
            detail="test review request",
            root=tmp_path,
        )
        assert result["owner_channel_id"] == review_ch, (
            f"{kind} did not route to #review"
        )


def test_quant_approval_events_route_to_review_channel(tmp_path):
    """quant_papertrade_request and quant_pulse_proposal must land in #review."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    channel_map = _load_channel_map()
    (config_dir / "agent_channel_map.json").write_text(json.dumps(channel_map))
    (tmp_path / "state" / "dispatch_events").mkdir(parents=True)
    (tmp_path / "state" / "discord_outbox").mkdir(parents=True)

    review_ch = channel_map["agents"]["archimedes"]["channel_id"]

    for kind in ["quant_papertrade_request", "quant_pulse_proposal"]:
        result = emit_event(
            kind, "kitt",
            task_id="task_test123456",
            detail="test quant approval",
            root=tmp_path,
        )
        assert result["owner_channel_id"] == review_ch, (
            f"{kind} did not route to #review"
        )


def test_review_completions_route_to_worklog(tmp_path):
    """review_completed and approval_completed must land in #worklog, NOT #review."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    channel_map = _load_channel_map()
    (config_dir / "agent_channel_map.json").write_text(json.dumps(channel_map))
    (tmp_path / "state" / "dispatch_events").mkdir(parents=True)
    (tmp_path / "state" / "discord_outbox").mkdir(parents=True)

    worklog_ch = channel_map["logical_channels"]["worklog"]["channel_id"]
    review_ch = channel_map["agents"]["archimedes"]["channel_id"]

    for kind in ["review_completed", "approval_completed"]:
        result = emit_event(
            kind, "archimedes",
            task_id="task_test123456",
            detail="verdict: approved. Looks good.",
            root=tmp_path,
        )
        assert result["owner_channel_id"] == worklog_ch, (
            f"{kind} did not route to #worklog (got {result['owner_channel_id']})"
        )
        assert result["owner_channel_id"] != review_ch, (
            f"{kind} still routes to #review"
        )


def test_approval_requested_does_not_forward_to_jarvis(tmp_path):
    """approval_requested is routine — must NOT forward to #jarvis."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    channel_map = _load_channel_map()
    (config_dir / "agent_channel_map.json").write_text(json.dumps(channel_map))
    (tmp_path / "state" / "dispatch_events").mkdir(parents=True)
    (tmp_path / "state" / "discord_outbox").mkdir(parents=True)

    result = emit_event(
        "approval_requested", "hal",
        task_id="task_test123456",
        detail="test approval",
        root=tmp_path,
    )
    assert result["jarvis_forwarded"] is False, (
        "approval_requested still forwarded to #jarvis"
    )
    labels = [e["label"] for e in result["outbox_entries"]]
    assert "jarvis_fwd" not in labels


def test_routine_events_skip_jarvis_but_hit_worklog(tmp_path):
    """Routine lifecycle events must land in lane + worklog, NOT in #jarvis."""
    # Write channel map to tmp_path so emit_event uses it
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    channel_map = _load_channel_map()
    (config_dir / "agent_channel_map.json").write_text(json.dumps(channel_map))

    # Also need runtime.core.models accessible — create state dirs
    (tmp_path / "state" / "dispatch_events").mkdir(parents=True)
    (tmp_path / "state" / "discord_outbox").mkdir(parents=True)

    # These are routine events that were removed from jarvis_forward_event_kinds
    routine_events = [
        ("artifact_promoted", "hal"),
        ("kitt_brief_completed", "kitt"),
        ("delegation_sent", "jarvis"),
        ("quant_strategy_promoted", "sigma"),
        ("quant_execution_status", "kitt"),
    ]

    for kind, agent in routine_events:
        result = emit_event(
            kind, agent,
            task_id="task_test123456",
            detail="routine test event",
            root=tmp_path,
        )
        # Must NOT forward to #jarvis
        assert result["jarvis_forwarded"] is False, (
            f"{kind} still forwarded to #jarvis"
        )
        # Must still have an owner channel (lane channel)
        assert result["owner_channel_id"] is not None, (
            f"{kind} lost its owner channel"
        )
        # Must still mirror to worklog (these are all in worklog_mirror_event_kinds)
        assert result["worklog_mirrored"] is True, (
            f"{kind} lost worklog mirror"
        )
        # Verify outbox entries: should have owner + worklog, but no jarvis_fwd
        labels = [e["label"] for e in result["outbox_entries"]]
        assert "jarvis_fwd" not in labels, (
            f"{kind} has jarvis_fwd outbox entry"
        )


def test_critical_events_still_forward_to_jarvis(tmp_path):
    """Operator-action-needed events must still forward to #jarvis."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    channel_map = _load_channel_map()
    (config_dir / "agent_channel_map.json").write_text(json.dumps(channel_map))

    (tmp_path / "state" / "dispatch_events").mkdir(parents=True)
    (tmp_path / "state" / "discord_outbox").mkdir(parents=True)

    critical_events = [
        ("task_failed", "hal"),
        ("task_blocked", "hal"),
        ("error", "hal"),
        ("warning", "ralph"),
        ("quant_alert", "kitt"),
    ]

    for kind, agent in critical_events:
        result = emit_event(
            kind, agent,
            task_id="task_test123456",
            detail="critical test event",
            root=tmp_path,
        )
        assert result["jarvis_forwarded"] is True, (
            f"{kind} no longer forwards to #jarvis"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
