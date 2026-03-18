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


def test_review_requested_has_pin():
    text = _render_status_text("review_requested", _payload(agent_id="hal", detail="Review new validation module"))
    assert "\U0001f440" in text  # 👀
    assert "needs review" in text
    assert "\U0001f4cc" in text  # 📌


def test_review_completed_approved():
    text = _render_status_text("review_completed", _payload(
        reviewer_id="archimedes",
        detail="verdict: approved. Clean implementation, good test coverage.",
    ))
    assert "\u2705" in text  # ✅
    assert "**Archimedes**" in text
    assert "APPROVED" in text
    assert "Clean implementation" in text


def test_review_completed_rejected():
    text = _render_status_text("review_completed", _payload(
        reviewer_id="archimedes",
        detail="verdict: rejected. Missing edge case handling.",
    ))
    assert "\u274c" in text  # ❌
    assert "REJECTED" in text


def test_approval_requested_has_pin():
    text = _render_status_text("approval_requested", _payload(detail="Deploy strategy to paper trading"))
    assert "\U0001f510" in text  # 🔐
    assert "\U0001f4cc" in text  # 📌
    assert "approve/reject" in text


def test_approval_completed_approved():
    text = _render_status_text("approval_completed", _payload(detail="decision: approved. Looks good."))
    assert "\u2705" in text  # ✅
    assert "APPROVED" in text


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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
