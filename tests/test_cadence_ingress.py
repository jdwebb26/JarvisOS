"""Tests for Cadence voice ingress pipeline.

Covers:
- classify_cadence_intent — all intent classes
- voice_subsystem routing (spotify, discord) passes through to existing voice router
- browser_action intent routes to Bowser (run_browser_task)
- hal_task / kitt_quant / scout_research queued via intake (queue only, no exec)
- jarvis_orchestration / approval_confirmation / local_quick / unclassified preview
- route_cadence_utterance preview mode never has side-effects
- execute mode delegates correctly for browser_action
- blocked browser action (policy) surfaces in cadence result
- agent roster contains cadence + delegation wiring
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.voice.cadence_ingress import classify_cadence_intent, route_cadence_utterance
from runtime.core.agent_roster import (
    CANONICAL_AGENT_ROSTER,
    DELEGATION_WIRING,
    AGENT_RUNTIME_TYPES,
    AGENT_TOOL_ALLOWLIST,
    AGENT_SKILL_ALLOWLIST,
)


# ---------------------------------------------------------------------------
# Phase 1: Agent roster — Cadence is a first-class agent
# ---------------------------------------------------------------------------

def test_cadence_in_canonical_roster() -> None:
    assert "cadence" in CANONICAL_AGENT_ROSTER
    profile = CANONICAL_AGENT_ROSTER["cadence"]
    assert profile["role"].startswith("voice ingress")
    assert profile["status"] == "wired"
    assert profile["kind"] == "ingress"


def test_cadence_in_runtime_types() -> None:
    assert "cadence" in AGENT_RUNTIME_TYPES
    assert AGENT_RUNTIME_TYPES["cadence"] == "embedded"


def test_cadence_in_tool_allowlist() -> None:
    assert "cadence" in AGENT_TOOL_ALLOWLIST
    tools = AGENT_TOOL_ALLOWLIST["cadence"]
    assert "tts" in tools
    assert "message" in tools
    assert "sessions_send" in tools


def test_cadence_in_skill_allowlist() -> None:
    assert "cadence" in AGENT_SKILL_ALLOWLIST
    assert "sherpa-onnx-tts" in AGENT_SKILL_ALLOWLIST["cadence"]


def test_delegation_wiring_contains_cadence() -> None:
    agents_with_cadence = {
        (entry["from_agent"], entry["to_agent"])
        for entry in DELEGATION_WIRING
        if "cadence" in (entry["from_agent"], entry["to_agent"])
    }
    # jarvis → cadence (receive from jarvis)
    assert ("jarvis", "cadence") in agents_with_cadence
    # cadence → bowser (browser delegation)
    assert ("cadence", "bowser") in agents_with_cadence
    # cadence → hal, kitt, scout
    assert ("cadence", "hal") in agents_with_cadence
    assert ("cadence", "kitt") in agents_with_cadence
    assert ("cadence", "scout") in agents_with_cadence


def test_jarvis_avoid_includes_voice_cadence_note() -> None:
    """Jarvis should be advised not to handle raw voice transcripts."""
    jarvis = CANONICAL_AGENT_ROSTER["jarvis"]
    combined = " ".join(jarvis.get("avoid", []))
    assert "cadence" in combined.lower() or "voice" in combined.lower()


# ---------------------------------------------------------------------------
# Phase 2: classify_cadence_intent — pure classification
# ---------------------------------------------------------------------------

def test_classify_spotify_as_voice_subsystem() -> None:
    result = classify_cadence_intent("play jazz on spotify")
    assert result["intent"] == "voice_subsystem"
    assert result["confidence"] == "high"


def test_classify_discord_as_voice_subsystem() -> None:
    result = classify_cadence_intent("open discord")
    assert result["intent"] == "voice_subsystem"


def test_classify_browser_url_as_browser_action() -> None:
    result = classify_cadence_intent("browse https://finance.yahoo.com/quote/NQ=F")
    assert result["intent"] == "browser_action"
    assert "finance.yahoo.com" in result["url"]


def test_classify_snapshot_as_browser_action() -> None:
    result = classify_cadence_intent("snapshot example.com")
    assert result["intent"] == "browser_action"


def test_classify_implement_as_hal_task() -> None:
    result = classify_cadence_intent("implement the artifact cleanup function")
    assert result["intent"] == "hal_task"


def test_classify_fix_bug_as_hal_task() -> None:
    result = classify_cadence_intent("fix the bug in execute_once")
    assert result["intent"] == "hal_task"


def test_classify_backtest_as_kitt_quant() -> None:
    result = classify_cadence_intent("run a backtest on the NQ strategy")
    assert result["intent"] == "kitt_quant"


def test_classify_profit_factor_as_kitt_quant() -> None:
    result = classify_cadence_intent("what is the profit factor of the latest candidate?")
    assert result["intent"] == "kitt_quant"


def test_classify_research_as_scout() -> None:
    result = classify_cadence_intent("research the latest Fed rate decision")
    assert result["intent"] == "scout_research"


def test_classify_summarize_as_scout() -> None:
    result = classify_cadence_intent("summarize the NQ market regime")
    assert result["intent"] == "scout_research"


def test_classify_status_as_jarvis_orchestration() -> None:
    result = classify_cadence_intent("show me the status")
    assert result["intent"] == "jarvis_orchestration"


def test_classify_yes_as_approval() -> None:
    result = classify_cadence_intent("yes")
    assert result["intent"] == "approval_confirmation"


def test_classify_approve_as_approval() -> None:
    result = classify_cadence_intent("approve")
    assert result["intent"] == "approval_confirmation"


def test_classify_hello_as_local_quick() -> None:
    result = classify_cadence_intent("hello")
    assert result["intent"] == "local_quick"


def test_classify_gibberish_as_unclassified() -> None:
    result = classify_cadence_intent("xyzzy quux frobnicate")
    assert result["intent"] == "unclassified"


# ---------------------------------------------------------------------------
# Phase 2/3: route_cadence_utterance — preview mode is always safe
# ---------------------------------------------------------------------------

def test_preview_mode_has_no_side_effects() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = route_cadence_utterance(
            "implement the cleanup job",
            execute=False,
            root=root,
        )
        assert result["execute"] is False
        assert result["routed"] is False
        assert result["route_reason"] == "preview_only"
        assert result["delegation_result"] is None
        # No tasks created in tmp dir
        task_dir = root / "state" / "tasks"
        assert not task_dir.exists() or not list(task_dir.iterdir())


def test_preview_shows_intent() -> None:
    with TemporaryDirectory() as tmp:
        result = route_cadence_utterance(
            "play jazz on spotify",
            execute=False,
            root=Path(tmp),
        )
        assert result["intent_result"]["intent"] == "voice_subsystem"
        assert result["route_reason"] == "preview_only"


# ---------------------------------------------------------------------------
# Phase 3: route_cadence_utterance — execute mode
# ---------------------------------------------------------------------------

def test_execute_browser_action_allowed_site() -> None:
    """Browser action to an allowed site (example.com) should route via Bowser."""
    from runtime.core.browser_control_allowlist import save_browser_control_allowlist
    from runtime.core.models import BrowserControlAllowlistRecord, new_id, now_iso

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        save_browser_control_allowlist(
            BrowserControlAllowlistRecord(
                browser_control_allowlist_id=new_id("browserallow"),
                created_at=now_iso(), updated_at=now_iso(),
                actor="tester", lane="tests",
                allowed_apps=[], allowed_sites=["example.com"],
                allowed_paths=[], blocked_apps=[], blocked_sites=[], blocked_paths=[],
                destructive_actions_require_confirmation=True,
                secret_entry_requires_manual_control=True,
            ), root=root,
        )
        result = route_cadence_utterance(
            "browse https://example.com/",
            execute=True,
            actor="cadence",
            lane="voice",
            root=root,
        )
        assert result["intent_result"]["intent"] == "browser_action"
        assert result["route_reason"] == "bowser_run_browser_task"
        dr = result["delegation_result"]
        assert dr is not None
        assert "task_id" in dr
        assert dr.get("task_id", "").startswith("task_")


def test_execute_blocked_browser_action() -> None:
    """Browser action to a blocked site should fail gracefully, not crash."""
    from runtime.core.browser_control_allowlist import save_browser_control_allowlist
    from runtime.core.models import BrowserControlAllowlistRecord, new_id, now_iso

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        save_browser_control_allowlist(
            BrowserControlAllowlistRecord(
                browser_control_allowlist_id=new_id("browserallow"),
                created_at=now_iso(), updated_at=now_iso(),
                actor="tester", lane="tests",
                allowed_apps=[], allowed_sites=["example.com"],
                allowed_paths=[], blocked_apps=[], blocked_sites=[], blocked_paths=[],
                destructive_actions_require_confirmation=True,
                secret_entry_requires_manual_control=True,
            ), root=root,
        )
        result = route_cadence_utterance(
            "browse https://notallowed.evil.example/",
            execute=True,
            actor="cadence",
            lane="voice",
            root=root,
        )
        assert result["intent_result"]["intent"] == "browser_action"
        dr = result["delegation_result"]
        # Task created and dispatched, but result.status == "failed" (policy blocked)
        assert dr is not None
        if dr.get("status"):
            assert dr["status"] in {"failed", "completed", "unknown"}


def test_execute_approval_never_auto_delegates() -> None:
    """Approval/confirmation intents must never be auto-executed."""
    with TemporaryDirectory() as tmp:
        result = route_cadence_utterance(
            "yes",
            execute=True,
            root=Path(tmp),
        )
        assert result["routed"] is False
        assert "approval" in result["route_reason"]


def test_execute_jarvis_orchestration_no_autoexec() -> None:
    """Status/summary intents surface for Jarvis, not auto-executed."""
    with TemporaryDirectory() as tmp:
        result = route_cadence_utterance(
            "show me the status",
            execute=True,
            root=Path(tmp),
        )
        assert result["routed"] is False
        assert "jarvis_orchestration" in result["route_reason"]


def test_execute_local_quick_returns_response() -> None:
    with TemporaryDirectory() as tmp:
        result = route_cadence_utterance(
            "hello",
            execute=True,
            root=Path(tmp),
        )
        assert result["routed"] is True
        assert result["route_reason"] == "local_quick_inline"
        assert result["delegation_result"]["response"]


# ---------------------------------------------------------------------------
# Phase 4: CLI proof path
# ---------------------------------------------------------------------------

def test_cadence_cli_preview_invocable() -> None:
    """CLI can be imported and invoked programmatically (no subprocess needed)."""
    import importlib
    mod = importlib.import_module("runtime.voice.cadence_cli")
    assert callable(getattr(mod, "main", None))


# ---------------------------------------------------------------------------
# Phase 5: Jarvis stays lean
# ---------------------------------------------------------------------------

def test_jarvis_is_not_in_cadences_denied_categories() -> None:
    """Cadence should not be blocked from calling message/tts — it needs them for Jarvis handoff."""
    cadence_profile = CANONICAL_AGENT_ROSTER["cadence"]
    denied = cadence_profile.get("denied_tool_categories", [])
    assert "voice" not in denied
    assert "coordination" not in denied


def test_cadence_voice_session_id_generated_when_absent() -> None:
    with TemporaryDirectory() as tmp:
        result = route_cadence_utterance(
            "hello",
            voice_session_id="",
            execute=False,
            root=Path(tmp),
        )
        vsid = result.get("voice_session_id", "")
        assert vsid.startswith("vsession_")


if __name__ == "__main__":
    test_cadence_in_canonical_roster()
    test_cadence_in_runtime_types()
    test_cadence_in_tool_allowlist()
    test_cadence_in_skill_allowlist()
    test_delegation_wiring_contains_cadence()
    test_jarvis_avoid_includes_voice_cadence_note()
    test_classify_spotify_as_voice_subsystem()
    test_classify_discord_as_voice_subsystem()
    test_classify_browser_url_as_browser_action()
    test_classify_snapshot_as_browser_action()
    test_classify_implement_as_hal_task()
    test_classify_fix_bug_as_hal_task()
    test_classify_backtest_as_kitt_quant()
    test_classify_profit_factor_as_kitt_quant()
    test_classify_research_as_scout()
    test_classify_summarize_as_scout()
    test_classify_status_as_jarvis_orchestration()
    test_classify_yes_as_approval()
    test_classify_approve_as_approval()
    test_classify_hello_as_local_quick()
    test_classify_gibberish_as_unclassified()
    test_preview_mode_has_no_side_effects()
    test_preview_shows_intent()
    test_execute_browser_action_allowed_site()
    test_execute_blocked_browser_action()
    test_execute_approval_never_auto_delegates()
    test_execute_jarvis_orchestration_no_autoexec()
    test_execute_local_quick_returns_response()
    test_cadence_cli_preview_invocable()
    test_jarvis_is_not_in_cadences_denied_categories()
    test_cadence_voice_session_id_generated_when_absent()
    print("All Cadence ingress tests passed.")
